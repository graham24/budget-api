import datetime
from dateutil.relativedelta import relativedelta
from analyze import BatchTransactionAnalyzer
from importers.apple import AppleTransaction
from importers.chase import ChaseTransaction
from importers.rmr import RMRTransaction
from importers.simplefin_importer import SimpeFinConnector, SimpleFinTransaction, Transactions as SimpleFinTransactions
from importers.us_bank import USBankTransaction
from importers.wells_fargo import WellsFargoTransaction
from models.account import Account, Accounts
from models.balance_entry import BalanceEntry
from models.category_rule import CategoryRules
from models.household import HouseholdUser, Household
from models.import_error import ImportErrorLog
from models.net_worth_item import NetWorthItem
from models.simplefin import SimpleFinAccount
from models.transaction import Transaction
from models.user import User


class Importer:
    @staticmethod
    def get_transaction_classes():
        return {
            "Wells Fargo": WellsFargoTransaction,
            "Chase": ChaseTransaction,
            "US Bank": USBankTransaction,
            "Apple": AppleTransaction,
            "RMR": RMRTransaction,
        }

    @classmethod
    def import_from_file(cls, file, account: Account):
        transaction_class = cls.get_transaction_classes().get(account.bank)
        if not transaction_class:
            raise ValueError(f"No importer for bank '{account.bank}'")
        return cls.import_transactions(transaction_class, file, account)

    @classmethod
    def import_from_simplefin(cls, transactions: SimpleFinTransactions, account: Account):
        return cls.import_transactions(
            SimpleFinTransaction, transactions, account
        )

    @classmethod
    def import_all_from_simplefin(cls, transactions_dict: dict):
        return cls.import_all_transactions(
            SimpleFinTransaction, transactions_dict
        )

    @staticmethod
    def apply_simplefin_bank_name(account: Account, sf_account_fetch) -> None:
        """SimpleFin is the source of truth for a linked account's bank: keep
        Account.bank equal to the institution name SimpleFin reports
        (org.name). It's half of the (user_id, bank) connection grouping key,
        so a user-typed or stale name would split or merge connections
        wrongly. Any manual edit to a linked account's bank is overwritten on
        its next sync."""
        org_name = (sf_account_fetch.org.name or "").strip()[:100]
        if org_name and account.bank != org_name:
            account.bank = org_name
            account.save()

    @staticmethod
    def record_simplefin_balance(net_worth_item: NetWorthItem, sf_account_fetch) -> float:
        """Write a BalanceEntry on a net-worth item from a SimpleFin account
        fetch. Balances are stored positive; assets prefer the available
        balance when SimpleFin reports one."""
        balance = abs(sf_account_fetch.balance)
        if net_worth_item.kind == 'asset' and sf_account_fetch.available_balance:
            balance = abs(sf_account_fetch.available_balance)
        BalanceEntry(
            item_id=net_worth_item.id,
            balance=balance,
            effective_date=sf_account_fetch.balance_date,
        ).create()
        print(
            f"{datetime.datetime.now()}: {net_worth_item.name}: balance updated to {balance}"
        )
        return balance

    @classmethod
    def import_household_from_simplefin(cls, household: Household):
        """Import every linked SimpleFin account's transactions + latest balance
        for a household. Shared by the daily cron entrypoint
        (importers/cron_importer.py) and the manual "Import Now" route
        (POST /api/simplefin/import/). Returns a summary (per-account
        imported/duplicate counts plus any connection errors) so callers can
        report on the run."""
        results = []
        household_users = HouseholdUser.load_by_filter(
            HouseholdUser.house_hold_id == household.id, limit=None
        )
        household_bank_accounts = Account.load_by_filter(
            column=Account.user_id,
            values=[household_user.user_id for household_user in household_users],
            limit=None,
        )
        sf_accounts = SimpleFinAccount.load_by_filter(
            column=SimpleFinAccount.bank_account_id,
            values=[bank.id for bank in household_bank_accounts],
            limit=None,
        )
        net_worth_items = NetWorthItem.load_by_filter(
            NetWorthItem.household_id == household.id, limit=None
        )
        connector = SimpeFinConnector(household.get_simplefin_url())
        connection_errors = []
        transactions_dict = {}
        sf_account_by_account_id = {}
        # One request per *connection* rather than one for the whole
        # household or one per account. SimpleFin refreshes an entire
        # connection whenever it's asked for any account on it, so a
        # per-account fetch makes the bridge redo that same work once per
        # account; asking for the connection's accounts together gets
        # everything it would have fetched anyway in a single request. A
        # connection is one person's login at one institution, so
        # (user_id, bank) is the grouping key.
        connections = {}
        for sf_account in sf_accounts:
            account = next(
                (
                    bank_account
                    for bank_account in household_bank_accounts
                    if bank_account.id == sf_account.bank_account_id
                ),
                None,
            )
            if not account:
                print(
                    f"Unable to find internal account for {sf_account.simplefin_account_id}"
                )
                continue
            connections.setdefault((account.user_id, account.bank), []).append(
                (sf_account, account)
            )

        user_names = {
            user.id: user.first_name or user.email
            for user in User.load_by_filter(
                column=User.id,
                values=[household_user.user_id for household_user in household_users],
                limit=None,
            )
        }
        # Computed here (same 14-day window as the connector's default) so the
        # log can say what range each fetch covers.
        start_date = datetime.datetime.now().replace(
            hour=0, minute=0, second=0, microsecond=0
        ) - relativedelta(days=14)
        for (user_id, bank), members in connections.items():
            print(
                f"{datetime.datetime.now()}: Fetching {bank} transactions for {user_names.get(user_id, f'user {user_id}')} since {start_date:%Y-%m-%d}"
            )
            try:
                fetched = connector.get_accounts_and_transactions_for(
                    [sf_account.simplefin_account_id for sf_account, _ in members],
                    start_date=start_date,
                )
            except Exception as e:
                # The whole connection failed — record it against every
                # account on it so the household can see what's stale.
                message = f"Couldn't reach SimpleFin for {bank} (user {user_id}): {e}"
                print(message)
                connection_errors.append(message)
                for _, account in members:
                    results.append(
                        {"account": account.description, "error": str(e)}
                    )
                continue
            # Errors SimpleFin reports for the institution itself, as
            # opposed to the request failing outright above.
            connection_errors.extend(fetched.errors)

            for sf_account, account in members:
                sf_account_fetch = next(
                    (
                        remote
                        for remote in fetched.accounts
                        if remote.id == sf_account.simplefin_account_id
                    ),
                    None,
                )
                if not sf_account_fetch:
                    # Nothing came back for this account — any explanation
                    # is already in fetched.errors and logged below.
                    print(
                        f"No SimpleFin data returned for {account.description} ({sf_account.simplefin_account_id})"
                    )
                    continue
                try:
                    cls.apply_simplefin_bank_name(account, sf_account_fetch)
                    net_worth_item = next(
                        (
                            item
                            for item in net_worth_items
                            if item.account_id == sf_account.bank_account_id
                        ),
                        None,
                    )
                    if not net_worth_item:
                        print(
                            f"Unable to find net worth item for {sf_account_fetch.name} ({sf_account_fetch.id}). Internal Simplefin data:"
                        )
                        print(sf_account.model_dump_json())
                    if net_worth_item:
                        cls.record_simplefin_balance(net_worth_item, sf_account_fetch)
                    transactions = SimpleFinTransactions(transactions=sf_account_fetch.transactions)
                    if not transactions.transactions:
                        print(
                            f"No transactions found for {account.description} ({sf_account.simplefin_account_id})"
                        )
                        continue
                    transactions_dict[account] = transactions
                    sf_account_by_account_id[account.id] = sf_account
                except Exception as e:
                    print(e)
                    print(f"Error processing account {sf_account_fetch.id}: {e}")
                    results.append(
                        {
                            "account": sf_account_fetch.name,
                            "error": str(e),
                        }
                    )

        # Several accounts can sit behind one institution, and each of their
        # responses repeats that institution's error — dedupe so a single
        # broken connection is one row, not one per account. dict.fromkeys
        # keeps the original order.
        connection_errors = list(dict.fromkeys(connection_errors))

        # Replace this household's error log with the current run's state —
        # a resolved connection drops out automatically instead of needing
        # to be manually dismissed, and a still-broken one doesn't pile up
        # a duplicate row every run. Done after the fetch loop rather than
        # before it, so a crash mid-run leaves the previous errors in place
        # instead of silently clearing them.
        for existing_error in ImportErrorLog.load_by_filter(
            ImportErrorLog.household_id == household.id, limit=None
        ):
            existing_error.delete()
        for connection_error in connection_errors:
            print(f"SimpleFin connection error: {connection_error}")
            ImportErrorLog(
                household_id=household.id,
                message=connection_error,
            ).create()

        imported = cls.import_all_from_simplefin(transactions_dict)
        imported_by_account = {}
        for transaction in imported["imported"]:
            imported_by_account.setdefault(transaction.account_id, []).append(transaction)
        duplicates_by_account = {}
        for transaction in imported["duplicates"]:
            duplicates_by_account.setdefault(transaction.account_id, []).append(transaction)

        for account, transactions in transactions_dict.items():
            sf_account = sf_account_by_account_id[account.id]
            sf_account.last_fetched = datetime.datetime.now()
            sf_account.save()
            account_imported = imported_by_account.get(account.id, [])
            account_duplicates = duplicates_by_account.get(account.id, [])
            print(
                f"{datetime.datetime.now()}: {account.description}: {len(account_imported)} imported, {len(account_duplicates)} duplicates."
            )
            results.append(
                {
                    "account": account.description,
                    "imported": len(account_imported),
                    "duplicates": len(account_duplicates),
                }
            )

        return {
            "results": results,
            "errors": connection_errors,
        }

    @classmethod
    def import_transactions(cls, transaction_class, source, account: Account, months: int = 12):
        months_ago = datetime.datetime.now() - relativedelta(months=months)
        household_user = HouseholdUser.load_by_filter(
            HouseholdUser.user_id == account.user_id,
            limit=None
        )
        accounts = Accounts.load_by_household_id(
            household_id=household_user[0].house_hold_id
        )
        account_transactions = Transaction.load_by_filter(
            Transaction.date >= months_ago,
            column=Transaction.account_id,
            values=[account.id for account in accounts.accounts],
            limit=None,
        )

        transactions, duplicate_transactions = transaction_class.create_transactions(source, account)

        imported_transactions = []

        # Apply user-defined category rules first; only unmatched
        # transactions are sent to the AI for categorization.
        rules = CategoryRules.load_by_household_id(
            household_user[0].house_hold_id
        )
        needs_ai = []
        for transaction in transactions:
            rule = rules.find_matching(transaction.description)
            if rule:
                transaction.category = rule.category
                transaction.sub_category = rule.sub_category
                transaction.need = rule.need
                transaction.income = rule.income
                transaction.save()
                account_transactions.append(transaction)
                imported_transactions.append(transaction)
            else:
                needs_ai.append(transaction)
        if needs_ai:
            analyzer = BatchTransactionAnalyzer(account=account)

            for i in range(0, len(needs_ai), 50):
                batch = needs_ai[i:i + 50]
                results = analyzer.analyze_batch(batch, reference_transactions=account_transactions)
                for transaction, response in zip(batch, results):
                    transaction.category = response["category"].strip()
                    transaction.sub_category = response["sub_category"].strip()
                    transaction.need = True if response["need"].strip() == "1" else False
                    transaction.income = response["income"]
                    transaction.save()
                    account_transactions.append(transaction)
                    imported_transactions.append(transaction)

        return {"imported": imported_transactions, "duplicates": duplicate_transactions}

    @classmethod
    def import_all_transactions(cls, transaction_class, transactions_dict: dict, months: int = 12):
        """Same as import_transactions, but for several accounts at once —
        transactions_dict maps Account -> source transactions for that
        account. AI categorization still runs per-account (the prompt names
        the account), but transactions across the whole household are
        created up front so category rules and the reference pool see
        everything together."""
        if not transactions_dict:
            return {"imported": [], "duplicates": []}

        accounts = list(transactions_dict.keys())
        months_ago = datetime.datetime.now() - relativedelta(months=months)
        household_user = HouseholdUser.load_by_filter(
            HouseholdUser.user_id == accounts[0].user_id,
            limit=None
        )
        household_accounts = Accounts.load_by_household_id(
            household_id=household_user[0].house_hold_id
        )
        account_transactions = Transaction.load_by_filter(
            Transaction.date >= months_ago,
            column=Transaction.account_id,
            values=[account.id for account in household_accounts.accounts],
            limit=None,
        )

        imported_transactions = []
        duplicate_transactions = []
        for account, source in transactions_dict.items():
            created, skipped = transaction_class.create_transactions(source, account)
            imported_transactions.extend(created)
            duplicate_transactions.extend(skipped)

        # Apply user-defined category rules first; only unmatched
        # transactions are sent to the AI for categorization.
        rules = CategoryRules.load_by_household_id(
            household_user[0].house_hold_id
        )
        needs_ai_by_account_id = {}
        for transaction in imported_transactions:
            rule = rules.find_matching(transaction.description)
            if rule:
                transaction.category = rule.category
                transaction.sub_category = rule.sub_category
                transaction.need = rule.need
                transaction.income = rule.income
                transaction.save()
                account_transactions.append(transaction)
            else:
                needs_ai_by_account_id.setdefault(transaction.account_id, []).append(transaction)

        household = Household.load(household_user[0].house_hold_id)
        if household.anthropic_api_key:
            for account in accounts:
                needs_ai = needs_ai_by_account_id.get(account.id, [])
                if not needs_ai:
                    continue
                analyzer = BatchTransactionAnalyzer(account=account)
                for i in range(0, len(needs_ai), 50):
                    batch = needs_ai[i:i + 50]
                    results = analyzer.analyze_batch(batch, reference_transactions=account_transactions)
                    for transaction, response in zip(batch, results):
                        transaction.category = response["category"].strip()
                        transaction.sub_category = response["sub_category"].strip()
                        transaction.need = True if response["need"].strip() == "1" else False
                        transaction.income = response["income"]
                        transaction.save()
                        account_transactions.append(transaction)

        return {"imported": imported_transactions, "duplicates": duplicate_transactions}
