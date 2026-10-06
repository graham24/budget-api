import json
from datetime import datetime

from models.account import Account
from models.transaction import Transaction


class RMRTransaction:
    @classmethod
    def create_transactions(cls, file, account: Account) -> tuple[list[Transaction], list[Transaction]]:
        created = []
        skipped = []

        with open(file, "r") as f:
            records = json.load(f)

        for record in records:
            if record.get("status") != "Complete":
                continue

            transaction = Transaction(
                external_id=str(record["posting_id"]),
                description=record["memo"].strip(),
                date=datetime.fromisoformat(record["status_date"].replace("Z", "+00:00")).replace(tzinfo=None),
                amount=float(record["amount"]),
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
