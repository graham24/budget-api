from flask import Blueprint, g, request, jsonify
from pydantic import ValidationError

from auth_utils import block_demo_writes, require_auth, require_household, resolve_household_from_account
from models.account import Account, Accounts
from models.end_points.account import (
    AccountCreateRequest,
    AccountsRequest,
    AccountUpdateRequest,
)
from models.household import HouseholdUser

accounts_bp = Blueprint("accounts", __name__)


@accounts_bp.route("/", methods=["POST"])
@require_auth
def get_accounts():
    try:
        accounts = None
        AccountsRequest.model_validate_json(request.data)
        household_users = HouseholdUser.load_by_filter(
            HouseholdUser.user_id == g.user_id
        )
        if not household_users:
            return jsonify({"message": "User not found", "status": 0}), 404
        if household_users:
            household_user = household_users[0]
            accounts = Accounts.load_by_household_id(
                household_id=household_user.house_hold_id
            )

        return jsonify(
            {
                "accounts": [
                    account.model_dump() for account in accounts.accounts
                ] if accounts else []
            }
        )
    except ValidationError as e:
        print(e)
        return (
            jsonify({"errors": e.errors(), "message": "Error", "status": 0}),
            400,
        )


@accounts_bp.route("/create/", methods=["POST"])
@require_auth
@block_demo_writes
def create_account():
    try:
        create_request = AccountCreateRequest.model_validate_json(
            request.data
        )
        account = Account(
            description=create_request.description.strip(),
            type=create_request.type.strip(),
            bank=create_request.bank,
            user_id=g.user_id,
        ).create()
        if not account:
            return (
                jsonify(
                    {"message": "Could not create the account", "status": 0}
                ),
                409,
            )

        return jsonify({"account": account.model_dump()})
    except ValidationError as e:
        print(e)
        return (
            jsonify({"errors": e.errors(), "message": "Error", "status": 0}),
            400,
        )


@accounts_bp.route("/<int:account_id>", methods=["PUT"])
@require_auth
@block_demo_writes
def update_account(account_id):
    try:
        update_request = AccountUpdateRequest.model_validate_json(
            request.data
        )
        account = Account.load(account_id)
        if not account:
            return (
                jsonify({"message": "Account not found", "status": 0}),
                404,
            )
        household_id = resolve_household_from_account(account_id)
        forbidden = require_household(household_id) if household_id else (
            jsonify({"message": "Forbidden", "status": 0}), 403
        )
        if forbidden:
            return forbidden
        updates = update_request.model_dump(
            exclude_unset=True, exclude_none=True
        )
        if "user_id" in updates:
            household_user_ids = {
                hu.user_id
                for hu in HouseholdUser.load_by_filter(
                    HouseholdUser.house_hold_id == household_id
                )
            }
            if updates["user_id"] not in household_user_ids:
                return (
                    jsonify(
                        {
                            "message": "That user isn't a member of this household",
                            "status": 0,
                        }
                    ),
                    400,
                )
        for field, value in updates.items():
            setattr(account, field, value)
        account.save()

        return jsonify({"account": account.model_dump()})
    except ValidationError as e:
        print(e)
        return (
            jsonify({"errors": e.errors(), "message": "Error", "status": 0}),
            400,
        )
