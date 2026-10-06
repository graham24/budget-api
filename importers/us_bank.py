import datetime
import csv

from models.account import Account
from models.transaction import Transaction


class USBankTransaction:
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
        headers = ['Date', 'Transaction', 'Name', 'Memo', 'Amount']
        with open(file, 'r') as file:
            dict_reader = csv.DictReader(file, fieldnames=headers)
            next(dict_reader)  # Skip the first row
            for row in dict_reader:
                transaction = Transaction(
                    description=row['Name'].strip(),
                    date=datetime.datetime.strptime(row['Date'], "%Y-%m-%d"),
                    amount=float(row['Amount']),
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
