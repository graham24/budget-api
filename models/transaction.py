import datetime
from typing import List, Optional

from models.account import Account
from models.db import DBModel, utcnow
from pydantic import BaseModel, computed_field
from sqlalchemy import event
from sqlmodel import Field, UniqueConstraint


class Transaction(DBModel, table=True):
    __table_args__ = (
        UniqueConstraint(
            "description",
            "date",
            "amount",
            "account_id",
            "import_sequence",
        ),
    )
    id: Optional[int] = Field(default=None, primary_key=True)
    external_id: Optional[str] = None
    description: str
    date: datetime.datetime
    amount: float
    need: bool
    # True for real earnings (pay, interest, gifts), False for spending and
    # for money coming back against spending (refunds, returns,
    # reimbursements), so a refund nets down its expense category instead
    # of counting as income. Optional only in Python: importers build rows
    # without it and the before_insert hook below fills in the sign-based
    # default; the column itself is NOT NULL.
    income: Optional[bool] = Field(default=None, nullable=False)
    account_id: int = Field(foreign_key="account.id")
    import_sequence: int = Field(default=0)
    category: Optional[str] = "Unknown"
    sub_category: Optional[str] = "Unknown"
    created: datetime.datetime = Field(default_factory=utcnow)
    modified: datetime.datetime = Field(default_factory=utcnow)

    @computed_field
    @property
    def type(self) -> str:
        if self.category and self.category.lower() == "transfer":
            return "Transfers"
        elif self.is_income:
            return "Income"
        else:
            return "Expenses"


    @property
    def is_income(self) -> bool:
        # Rows that haven't been inserted yet (e.g. skipped duplicates
        # returned from an import) may not have the flag set.
        if self.income is None:
            return float(self.amount) >= 0
        return self.income


@event.listens_for(Transaction, "before_insert")
def default_income(mapper, connection, transaction: Transaction):
    """Every import path constructs Transaction rows without `income` —
    default it from the sign here, once, and let category rules / AI
    categorization overwrite it afterwards."""
    if transaction.income is None:
        transaction.income = float(transaction.amount) >= 0


class Transactions(BaseModel):
    transactions: List[Transaction]

    @classmethod
    def load_all_by_account(cls, account: Account):
        transactions = Transaction.load_by_filter(
            Transaction.account_id == account.id
        )
        return cls(transactions=transactions)

    @classmethod
    def load_all(cls):
        transactions = Transaction.load_by_filter()
        return cls(transactions=transactions)
