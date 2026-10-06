import datetime

from flask import Blueprint, request, jsonify
from pydantic import ValidationError
from dateutil.relativedelta import relativedelta

from auth_utils import block_demo_writes, require_auth, require_household
from importers.importer import Importer
from importers.simplefin_importer import SimpeFinConnector, Transactions as SimpleFinTransactions
from models.account import Account, Accounts
from models.end_points.simplefin import (
    SimplefinAccountLinkRequest,
    SimplefinAccountRefreshRequest,
    SimplefinAccountsRequest,
    SimplefinImportRequest,
)
from models.household import Household, HouseholdUsers
from models.net_worth_item import NetWorthItem
from models.simplefin import SimpleFinAccount, SimpleFinAccounts

simplefin_bp = Blueprint("simplefin", __name__)


def simplefin_account_dict(sf_account: SimpleFinAccount, remote_account=None, linked_account: Account = None):
    data = {
        "id": sf_account.id,
        "simplefin_account_id": sf_account.simplefin_account_id,
        "bank_account_id": sf_account.bank_account_id,
        "name": remote_account.name if remote_account else None,
        "balance": remote_account.balance if remote_account else None,
        "currency": remote_account.currency if remote_account else None,
        "org_name": remote_account.org.name if remote_account else None,
        "linked_account": linked_account.model_dump() if linked_account else None,
    }
    return data


@simplefin_bp.route("/accounts/", methods=["POST"])
@require_auth
@block_demo_writes
def fetch_accounts():
    try:
        accounts_request = SimplefinAccountsRequest.model_validate_json(
            request.data
        )
        forbidden = require_household(accounts_request.household_id)
        if forbidden:
            return forbidden
        household = Household.load(accounts_request.household_id)
        if not household:
            return jsonify({"message": "Household not found", "status": 0}), 404
        if not household.simplefin_access_url:
            return (
                jsonify(
                    {
                        "message": "SimpleFin isn't connected for this household yet",
                        "status": 0,
                    }
                ),
                400,
            )

        try:
            remote_accounts = SimpeFinConnector(
                household.get_simplefin_url()
            ).get_accounts()
        except Exception as e:
            return jsonify({"message": str(e), "status": 0}), 400

        existing_sf_accounts = SimpleFinAccounts.load_by_simplefin_account_ids(
            [remote_account.id for remote_account in remote_accounts.accounts]
        ).accounts
        first_fetch = not any(
            sf.bank_account_id is not None for sf in existing_sf_accounts
        )

        results = []
        for remote_account in remote_accounts.accounts:
            sf_account = next(
                (
                    sf
                    for sf in existing_sf_accounts
                    if sf.simplefin_account_id == remote_account.id
                ),
                None,
            )
            if not sf_account:
                sf_account = SimpleFinAccount(
                    simplefin_account_id=remote_account.id,
                ).create()
                if not sf_account:
                    # Lost a create race against a duplicate simplefin_account_id
                    sf_account = SimpleFinAccount.load_by_filter(
                        SimpleFinAccount.simplefin_account_id == remote_account.id,
                        limit=1,
                    )[0]

            linked_account = (
                Account.load(sf_account.bank_account_id)
                if sf_account.bank_account_id
                else None
            )
            results.append(
                simplefin_account_dict(sf_account, remote_account, linked_account)
            )

        return jsonify({"accounts": results, "first_fetch": first_fetch})
    except ValidationError as e:
        print(e)
        return (
            jsonify({"errors": e.errors(), "message": "Error", "status": 0}),
            400,
        )


@simplefin_bp.route("/import/", methods=["POST"])
@require_auth
@block_demo_writes
def import_transactions():
    try:
        import_request = SimplefinImportRequest.model_validate_json(request.data)
        forbidden = require_household(import_request.household_id)
        if forbidden:
            return forbidden
        household = Household.load(import_request.household_id)
        if not household:
            return jsonify({"message": "Household not found", "status": 0}), 404
        if not household.simplefin_access_url:
            return (
                jsonify(
                    {
                        "message": "SimpleFin isn't connected for this household yet",
                        "status": 0,
                    }
                ),
                400,
            )

        try:
            result = Importer.import_household_from_simplefin(household)
        except Exception as e:
            return jsonify({"message": str(e), "status": 0}), 400

        return jsonify(result)
    except ValidationError as e:
        print(e)
        return (
            jsonify({"errors": e.errors(), "message": "Error", "status": 0}),
            400,
        )


@simplefin_bp.route("/accounts/<int:id>/link", methods=["PUT"])
@require_auth
@block_demo_writes
def link_account(id):
    try:
        link_request = SimplefinAccountLinkRequest.model_validate_json(
            request.data
        )
        forbidden = require_household(link_request.household_id)
        if forbidden:
            return forbidden

        sf_account = SimpleFinAccount.load(id)
        if not sf_account:
            return (
                jsonify({"message": "SimpleFin account not found", "status": 0}),
                404,
            )
        household = Household.load(link_request.household_id)
        if not household or not household.simplefin_access_url:
            return jsonify({"message": "Household not found", "status": 0}), 404
        try:
            remote_accounts = SimpeFinConnector(
                household.get_simplefin_url()
            ).get_accounts()
        except Exception as e:
            return jsonify({"message": str(e), "status": 0}), 400
        if not any(
            remote_account.id == sf_account.simplefin_account_id
            for remote_account in remote_accounts.accounts
        ):
            return (
                jsonify({"message": "SimpleFin account not found", "status": 0}),
                404,
            )

        if link_request.new_account:
            household_user_ids = {
                hu.user_id
                for hu in HouseholdUsers.load_by_household_id(
                    link_request.household_id
                ).household_users
            }
            if link_request.new_account.user_id not in household_user_ids:
                return (
                    jsonify(
                        {
                            "message": "That user isn't a member of this household",
                            "status": 0,
                        }
                    ),
                    400,
                )
            account = Account(
                description=link_request.new_account.description.strip(),
                type=link_request.new_account.type.strip(),
                bank=link_request.new_account.bank,
                user_id=link_request.new_account.user_id,
            ).create()
            if not account:
                return (
                    jsonify(
                        {"message": "Could not create the account", "status": 0}
                    ),
                    409,
                )
            sf_account.bank_account_id = account.id
        elif link_request.bank_account_id is not None:
            account = Account.load(link_request.bank_account_id)
            household_account_ids = {
                a.id
                for a in Accounts.load_by_household_id(
                    link_request.household_id
                ).accounts
            }
            if not account or account.id not in household_account_ids:
                return (
                    jsonify({"message": "Account not found", "status": 0}),
                    404,
                )
            sf_account.bank_account_id = account.id
        else:
            sf_account.bank_account_id = None

        sf_account.save()
        linked_account = (
            Account.load(sf_account.bank_account_id)
            if sf_account.bank_account_id
            else None
        )

        return jsonify(simplefin_account_dict(sf_account, None, linked_account))
    except ValidationError as e:
        print(e)
        return (
            jsonify({"errors": e.errors(), "message": "Error", "status": 0}),
            400,
        )


@simplefin_bp.route("/accounts/<int:id>/refresh", methods=["PUT"])
@require_auth
@block_demo_writes
def refresh_account_transactions(id):
    """Manually pull the last 3 months of transactions for one linked
    SimpleFin account — e.g. a per-account "Refresh Transactions" button,
    versus /import/ which runs every linked account in the household."""
    try:
        refresh_request = SimplefinAccountRefreshRequest.model_validate_json(
            request.data
        )
        forbidden = require_household(refresh_request.household_id)
        if forbidden:
            return forbidden

        sf_account = SimpleFinAccount.load(id)
        if not sf_account:
            return (
                jsonify({"message": "SimpleFin account not found", "status": 0}),
                404,
            )
        if not sf_account.bank_account_id:
            return (
                jsonify(
                    {
                        "message": "This SimpleFin account isn't linked to an account yet",
                        "status": 0,
                    }
                ),
                400,
            )
        account = Account.load(sf_account.bank_account_id)
        if not account:
            return jsonify({"message": "Account not found", "status": 0}), 404
        household = Household.load(refresh_request.household_id)
        if not household or not household.simplefin_access_url:
            return jsonify({"message": "Household not found", "status": 0}), 404

        try:
            # /accounts narrowed to this one account returns its balance
            # alongside the transactions, so one request covers both.
            connector = SimpeFinConnector(household.get_simplefin_url())
            fetched = connector.get_accounts_and_transactions_for(
                [sf_account.simplefin_account_id],
                start_date=datetime.datetime.now().replace(
                    hour=0, minute=0, second=0, microsecond=0
                )
                - relativedelta(days=89),
            )
            sf_account_fetch = next(
                (
                    remote
                    for remote in fetched.accounts
                    if remote.id == sf_account.simplefin_account_id
                ),
                None,
            )
            if not sf_account_fetch:
                message = "; ".join(fetched.errors) or "No data returned from SimpleFin for this account"
                return jsonify({"message": message, "status": 0}), 400

            Importer.apply_simplefin_bank_name(account, sf_account_fetch)
            balance = None
            net_worth_item = next(
                iter(
                    NetWorthItem.load_by_filter(
                        NetWorthItem.household_id == refresh_request.household_id,
                        NetWorthItem.account_id == account.id,
                        limit=1,
                    )
                ),
                None,
            )
            if net_worth_item:
                balance = Importer.record_simplefin_balance(
                    net_worth_item, sf_account_fetch
                )

            result = Importer.import_from_simplefin(
                SimpleFinTransactions(transactions=sf_account_fetch.transactions),
                account,
            )
        except Exception as e:
            return jsonify({"message": str(e), "status": 0}), 400

        sf_account.last_fetched = datetime.datetime.now()
        sf_account.save()

        return jsonify(
            {
                **simplefin_account_dict(sf_account, None, account),
                "imported": len(result.get("imported")),
                "duplicates": len(result.get("duplicates")),
                "balance": balance,
            }
        )
    except ValidationError as e:
        print(e)
        return (
            jsonify({"errors": e.errors(), "message": "Error", "status": 0}),
            400,
        )