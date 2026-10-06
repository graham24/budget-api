import datetime
from typing import Any, Optional
import requests
from dateutil.relativedelta import relativedelta

from pydantic import BaseModel, ConfigDict, Field, field_validator
import simplefin

from models.account import Account as DBAccount
from models.transaction import Transaction as DBTransaction


class Transaction(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    id: str
    posted: datetime.datetime
    amount: float
    description: str
    payee: str
    memo: str
    transacted_at: datetime.datetime
    mcc: Optional[str]

    @field_validator("posted", "transacted_at", mode="after")
    def to_naive_utc(cls, value: datetime.datetime) -> datetime.datetime:
        # SimpleFin returns tz-aware datetimes; every other datetime in this
        # app is naive UTC (models.db.utcnow()) — normalize here so stored
        # transaction dates aren't silently off by the original UTC offset,
        # and so downstream date math (e.g. dedup matching) doesn't have to
        # special-case aware vs. naive.
        if value.tzinfo is not None:
            return value.astimezone(datetime.timezone.utc).replace(tzinfo=None)
        return value


class Transactions(BaseModel):
    transactions: Optional[list[Transaction]] = []


class Bank(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    domain: str
    name: str
    sfin_url: str = Field(alias="sfin-url")
    url: str
    id: str


class Account(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    id: str
    name: str
    currency: str
    balance: float
    available_balance: float = Field(alias="available-balance")
    balance_date: datetime.datetime = Field(alias="balance-date")
    transactions: Optional[list[Transaction]] = []
    holdings: Optional[list[Any]] = []
    org: Bank

    @field_validator("balance_date", mode="before")
    def convert_date(balance_date):
        return datetime.datetime.fromtimestamp(balance_date)


class Accounts(BaseModel):
    accounts: list[Account]
    errors: list[str] = []


class SimpleFinTransaction:
    @classmethod
    def create_transactions(cls, transactions: Transactions, account: DBAccount) -> tuple[list[DBTransaction], list[DBTransaction]]:
        created = []
        skipped = []
        existing_transactions = DBTransaction.load_by_filter(
            column=DBTransaction.external_id,
            values=[transaction.id for transaction in transactions.transactions],
            limit=None,
        )
        db_external_ids = [transaction.external_id for transaction in existing_transactions]

        # CSV-imported transactions have no external_id, so they never match
        # the external_id check above, and their description/date rarely
        # matches SimpleFin's normalized text closely enough to trip the DB
        # unique constraint either. Match unclaimed (external_id IS NULL)
        # rows on this account by amount + a nearby date instead, and link
        # the SimpleFin id onto the existing row rather than creating a
        # duplicate — future syncs then match it cleanly via external_id.
        unclaimed_transactions = list(
            DBTransaction.load_by_filter(
                DBTransaction.account_id == account.id,
                DBTransaction.external_id.is_(None),
                limit=None,
            )
        )

        for record in transactions.transactions:
            if record.id in db_external_ids:
                # print(f"Transaction Skipped (duplicate): {record.transacted_at} | {record.description} | {record.amount}")
                continue
            existing_manual_transaction = next(
                (
                    existing
                    for existing in unclaimed_transactions
                    if existing.amount == record.amount
                    and abs((existing.date - record.transacted_at).days) <= 3
                ),
                None,
            )
            if existing_manual_transaction:
                existing_manual_transaction.external_id = record.id
                result = existing_manual_transaction.save()
                unclaimed_transactions.remove(existing_manual_transaction)
                skipped.append(result)
                continue
            transaction = DBTransaction(
                external_id=record.id,
                description=(record.description or record.payee).strip(),
                date=record.transacted_at,
                amount=record.amount,
                need=True,
                account_id=account.id,
            )
            result = transaction.create()
            if not result:
                # print(f"Transaction Skipped (duplicate): {transaction.date} | {transaction.description} | {transaction.amount}")
                skipped.append(transaction)
                continue
            created.append(result)

        return created, skipped


class SimpeFinConnector:
    # A single bank connection that hangs shouldn't stall the whole cron
    # run — every household is imported in the same process, one after the
    # other, so an unbounded request blocks every household behind it.
    REQUEST_TIMEOUT_SECONDS = 60

    def __init__(self, access_url: str):
        self.access_url = access_url
        self.client = simplefin.SimpleFINClient(access_url)

    def get_transactions(
        self, account_id: str, start_date: datetime.datetime = None
    ) -> Transactions:
        if not start_date:
            # Use the first day of the month
            start_date = datetime.datetime.now().replace(
                day=1, hour=0, minute=0, second=0, microsecond=0
            )
        return Transactions(
            transactions=self.client.get_transactions(
                account_id=account_id, start_date=start_date.date()
            )
        )

    def get_account(self, account_id) -> Account:
        return Account.model_validate(self.client.get_account(account_id))

    def get_accounts(self) -> Accounts:
        return Accounts(accounts=self.client.get_accounts())

    def get_info(self):
        return self.client.get_info()

    def get_accounts_and_transactions(
        self, start_date: datetime.datetime = None
    ) -> Accounts:
        start_date = datetime.datetime.now().replace(
            hour=0, minute=0, second=0, microsecond=0
        ) - relativedelta(days=7)
        unix_date = start_date.timestamp()
        request = requests.get(
            f"{self.access_url}/accounts?start-date={int(unix_date)}",
            timeout=self.REQUEST_TIMEOUT_SECONDS,
        )
        request.raise_for_status()
        response = request.json()
        return Accounts(accounts=response['accounts'], errors=response.get('errors', []))

    def get_accounts_and_transactions_for(
        self, account_ids: list[str], start_date: datetime.datetime = None
    ) -> Accounts:
        """Balances + transactions for a specific set of accounts.

        Same endpoint as get_accounts_and_transactions, narrowed with a
        repeated `account` filter (`?account=a&account=b`).

        Callers group the ids by connection — SimpleFin refreshes a whole
        connection per request, so asking for one account at a time makes
        the bridge redo that same work once per account. One request per
        connection asks for everything that connection would have fetched
        anyway, while still keeping a broken connection from taking the
        rest of the household down with it.

        Returns the `Accounts` envelope rather than bare accounts so the
        `errors` SimpleFin reports for an unreachable institution are still
        surfaced to the caller.
        """
        if not account_ids:
            return Accounts(accounts=[], errors=[])
        if not start_date:
            start_date = datetime.datetime.now().replace(
                hour=0, minute=0, second=0, microsecond=0
            ) - relativedelta(days=14)
        request = requests.get(
            f"{self.access_url}/accounts",
            params={
                "start-date": int(start_date.timestamp()),
                "account": account_ids,
            },
            timeout=self.REQUEST_TIMEOUT_SECONDS,
        )
        request.raise_for_status()
        response = request.json()
        # Filter by id rather than trusting the server to have honoured the
        # `account` params — if they're ignored we'd otherwise treat every
        # account in the household as part of this connection.
        requested = set(account_ids)
        accounts = [
            account
            for account in response.get("accounts", [])
            if account.get("id") in requested
        ]
        return Accounts(accounts=accounts, errors=response.get("errors", []))
