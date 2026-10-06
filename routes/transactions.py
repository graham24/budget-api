import datetime
import os
import tempfile
from dateutil.relativedelta import relativedelta
from flask import Blueprint, request, jsonify
from pydantic import ValidationError

from auth_utils import block_demo_writes, require_auth, require_household, resolve_household_from_account
from importers.importer import Importer
from models.account import Account, Accounts
from models.category_rule import CategoryRules
from models.household import HouseholdUser
from analyze import TransactionAnalyzer
from models.end_points.transaction import (
    ForceImportRequest,
    TransactionSaveRequest,
    TransactionsRequest,
    TransactionsSummaryRequest,
)
from models.transaction import Transaction

transactions_bp = Blueprint("transactions", __name__)


@transactions_bp.route("/", methods=["GET"])
@require_auth
def get_transactions():
    try:
        transaction_request = TransactionsRequest.model_validate(
            request.args.to_dict()
        )
        forbidden = require_household(transaction_request.household_id)
        if forbidden:
            return forbidden
        accounts = Accounts.load_by_household_id(
            transaction_request.household_id
        ).accounts

        transactions = Transaction.load_by_filter(
            (
                Transaction.date >= transaction_request.from_date
                if transaction_request.from_date
                else True
            ),
            (
                Transaction.date < transaction_request.to_date
                if transaction_request.to_date
                else True
            ),
            (
                Transaction.date
                >= datetime.datetime.now().replace(day=1, hour=0, minute=0, second=0, microsecond=0) - relativedelta(months=3)
                if not transaction_request.from_date
                else True
            ),
            column=Transaction.account_id,
            values=[account.id for account in accounts],
            limit=None,
        )
        return jsonify(
            {
                "all_transactions": [
                    transaction.model_dump() for transaction in transactions
                ],
                # "transfers": [
                #     transaction.model_dump()
                #     for transaction in transactions
                #     if transaction.category.lower() == "transfer"
                # ],
                # "expenses": [
                #     transaction.model_dump()
                #     for transaction in transactions
                #     if transaction.amount < 0
                #     and transaction.category.lower() != "transfer"
                # ],
                # "income": [
                #     transaction.model_dump()
                #     for transaction in transactions
                #     if transaction.amount >= 0
                #     and transaction.category.lower() != "transfer"
                # ],
            }
        )
    except ValidationError as e:
        print(e)
        return (
            jsonify({"errors": e.errors(), "message": "Error", "status": 0}),
            400,
        )


@transactions_bp.route("/summary/", methods=["GET"])
@require_auth
def get_summary():
    """
    Return a summary of transactions, net income and categories.

    Data returned is for the last three months.
    """
    try:
        net_incomes = []
        categories = []
        transaction_request = TransactionsSummaryRequest.model_validate(
            request.args.to_dict()
        )
        forbidden = require_household(transaction_request.household_id)
        if forbidden:
            return forbidden
        accounts = Accounts.load_by_household_id(
            transaction_request.household_id
        ).accounts
        start_date = datetime.datetime.now().replace(
            day=1, hour=0, minute=0, second=0, microsecond=0
        ) - relativedelta(months=3)
        while start_date < datetime.datetime.now() - relativedelta(
            months=1
        ):  # Don't return current month, as it is not complete.
            net_income = 0
            income = 0
            expenses = 0
            month_income_categories = []
            month_expense_categories = []
            end_date = start_date + relativedelta(months=1)
            transactions = Transaction.load_by_filter(
                Transaction.date >= start_date,
                Transaction.date < end_date,
                Transaction.category != "Transfer",
                column=Transaction.account_id,
                values=[account.id for account in accounts],
                limit=None,
            )
            for transaction in transactions:
                net_income += transaction.amount
                # Refunds (income=False, positive amount) land in expenses
                # and reduce them, rather than counting as income.
                if transaction.income:
                    income += transaction.amount
                    if not any(
                        cat.get("category") == transaction.category
                        for cat in month_income_categories
                    ):
                        month_income_categories.append(
                            {
                                "category": transaction.category,
                                "amount": transaction.amount,
                            }
                        )
                    else:
                        for cat in month_income_categories:
                            if cat.get("category") == transaction.category:
                                cat["amount"] += transaction.amount
                else:
                    expenses -= transaction.amount
                    if not any(
                        cat.get("category") == transaction.category
                        for cat in month_expense_categories
                    ):
                        month_expense_categories.append(
                            {
                                "category": transaction.category,
                                "amount": transaction.amount,
                            }
                        )
                    else:
                        for cat in month_expense_categories:
                            if cat.get("category") == transaction.category:
                                cat["amount"] += transaction.amount
            categories.append(
                {
                    "date": start_date.isoformat(),
                    "income": month_income_categories,
                    "expenses": month_expense_categories,
                }
            )

            net_incomes.append(
                {
                    "date": start_date.isoformat(),
                    "net": round(net_income, 2),
                    "income": round(income, 2),
                    "expenses": round(expenses, 2),
                }
            )
            start_date = end_date
        categories.sort(key=lambda x: x["date"], reverse=True)
        net_incomes.sort(key=lambda x: x["date"], reverse=True)
        return jsonify({"net_incomes": net_incomes, "categories": categories})
    except ValidationError as e:
        print(e)
        return (
            jsonify({"errors": e.errors(), "message": "Error", "status": 0}),
            400,
        )


@transactions_bp.route("/save", methods=["PUT"])
@require_auth
@block_demo_writes
def save_transaction():
    try:
        transaction_request = TransactionSaveRequest.model_validate_json(
            request.data
        )
        transaction = Transaction.load(transaction_request.id)
        if not transaction:
            return jsonify({"message": "Transaction not found", "status": 0}), 404
        household_id = resolve_household_from_account(transaction.account_id)
        forbidden = require_household(household_id) if household_id else (
            jsonify({"message": "Forbidden", "status": 0}), 403
        )
        if forbidden:
            return forbidden
        transaction.category = transaction_request.category
        transaction.sub_category = transaction_request.sub_category
        transaction.need = transaction_request.need
        if transaction_request.income is not None:
            transaction.income = transaction_request.income
        transaction.save()
        return jsonify({"transaction": transaction.model_dump()})
    except ValidationError as e:
        return (
            jsonify({"errors": e.errors(), "message": "Error", "status": 0}),
            400,
        )


@transactions_bp.route("/upload/", methods=["POST"])
@require_auth
@block_demo_writes
def upload_transactions():
    try:
        account_id = request.values["accountId"]
        account = Account.load(account_id)
        if not account:
            return jsonify({"message": "Account not found", "status": 0}), 404
        household_id = resolve_household_from_account(account_id)
        forbidden = require_household(household_id) if household_id else (
            jsonify({"message": "Forbidden", "status": 0}), 403
        )
        if forbidden:
            return forbidden
        file = request.files["importFile"]

        if file.filename == "":
            return (
                jsonify(
                    {"message": "No file selected for uploading", "status": 0}
                ),
                400,
            )

        # Read the binary file and decode it to a CSV
        csv_content = file.stream.read().decode("utf-8")
        fd, file_path = tempfile.mkstemp(suffix=".csv")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                f.write(csv_content.strip())
            result = Importer.import_from_file(file=file_path, account=account)
        finally:
            os.remove(file_path)

        return jsonify(
            {
                "imported_transactions": [
                    t.model_dump() for t in result["imported"]
                ],
                "duplicate_transactions": [
                    t.model_dump() for t in result["duplicates"]
                ],
            }
        )
    except Exception as e:
        print(e)
        return (
            jsonify(
                {
                    "errors": str(e),
                    "message": "Error processing file",
                    "status": 0,
                }
            ),
            400,
        )


@transactions_bp.route("/force-import/", methods=["POST"])
@require_auth
@block_demo_writes
def force_import_transaction():
    try:
        body = ForceImportRequest.model_validate_json(request.data)

        household_id = resolve_household_from_account(body.account_id)
        forbidden = require_household(household_id) if household_id else (
            jsonify({"message": "Forbidden", "status": 0}), 403
        )
        if forbidden:
            return forbidden

        # Find how many existing transactions match on the core fields
        existing = Transaction.load_by_filter(
            Transaction.description == body.description,
            Transaction.date == body.date,
            Transaction.amount == body.amount,
            Transaction.account_id == body.account_id,
            limit=None,
        )
        next_sequence = len(existing)

        transaction = Transaction(
            description=body.description,
            date=body.date,
            amount=body.amount,
            need=True,
            account_id=body.account_id,
            import_sequence=next_sequence,
        )
        transaction = transaction.create()
        if not transaction:
            return (
                jsonify(
                    {
                        "message": "Transaction already force-imported",
                        "status": 0,
                    }
                ),
                409,
            )

        # Category rules take precedence over AI categorization
        account = Account.load(body.account_id)
        household_user = HouseholdUser.load_by_filter(
            HouseholdUser.user_id == account.user_id
        )
        rules = CategoryRules.load_by_household_id(
            household_user[0].house_hold_id
        )
        rule = rules.find_matching(transaction.description)
        if rule:
            transaction.category = rule.category
            transaction.sub_category = rule.sub_category
            transaction.need = rule.need
            transaction.income = rule.income
        else:
            response = TransactionAnalyzer(transaction=transaction).analyze_transaction()
            transaction.category = response["category"].strip()
            transaction.sub_category = response["sub_category"].strip()
            transaction.need = True if response["need"].strip() == "1" else False
            transaction.income = response["income"]
        transaction.save()

        return jsonify(transaction.model_dump())
    except ValidationError as e:
        return jsonify({"errors": e.errors(), "message": "Error", "status": 0}), 400
    except Exception as e:
        print(e)
        return jsonify({"errors": str(e), "message": "Error force importing", "status": 0}), 400
