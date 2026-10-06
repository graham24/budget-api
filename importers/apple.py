import datetime
import csv

from models.account import Account
from models.transaction import Transaction


class AppleTransaction:
    @classmethod
    def create_transaction(cls, data: str, account: Account) -> Transaction:
        data_list = [item.strip().strip('"') for item in data.split(",")]
        result = Transaction(
            description=data_list[4],
            date=datetime.datetime.strptime(data_list[0], "%m/%d/%Y"),
            amount=float(data_list[1]),
            need=True,
            account_id=account.id,
        ).create()
        if result:
            return result
        else:
            return False

    @classmethod
    def create_transactions(cls, file, account: Account) -> tuple[list[Transaction], list[Transaction]]:
        created = []
        skipped = []
        credit_headers = [
            "Transaction Date",
            "Clearing Date",
            "Description",
            "Merchant",
            "Category",
            "Type",
            "Amount (USD)",
            "Purchased By",
        ]
        savings_headers = [
            "Transaction Date",
            "Posted Date",
            "Activity Type",
            "Transaction Type",
            "Description",
            "Currency Code",
            "Amount",
        ]
        with open(file, "r") as file:
            dict_reader = csv.DictReader(
                file,
                fieldnames=(
                    credit_headers
                    if account.type == "Credit Card"
                    else savings_headers
                ),
            )
            next(dict_reader)  # Skip the first row
            for row in dict_reader:
                if account.type == "Savings":
                    transaction = Transaction(
                        description=row["Description"].strip(),
                        date=datetime.datetime.strptime(
                            row["Transaction Date"], "%m/%d/%Y"
                        ),
                        amount=float(row["Amount"])
                        * (-1 if row["Transaction Type"] == "Debit" else 1),
                        need=True,
                        account_id=account.id,
                    )
                elif account.type == "Credit Card":
                    transaction = Transaction(
                        description=row["Description"].strip(),
                        date=datetime.datetime.strptime(
                            row["Transaction Date"], "%m/%d/%Y"
                        ),
                        amount=float(row["Amount (USD)"]) * -1,
                        need=True,
                        account_id=account.id,
                    )
                result = transaction.create()
                if not result:
                    print(f"Transaction Skipped (duplicate): {transaction.date} | {transaction.description} | {transaction.amount}")
                    skipped.append(transaction)
                    continue
                created.append(result)
        return created, skipped
