import datetime
import csv
from models.account import Account
from models.transaction import Transaction


class WellsFargoTransaction:
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
        with open(file, "r") as file:
            reader = csv.DictReader(file)
            for row in reader:
                transaction = Transaction(
                    description=row["DESCRIPTION"].strip(),
                    date=datetime.datetime.strptime(row["DATE"], "%m/%d/%Y"),
                    amount=float(row["AMOUNT"]),
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
