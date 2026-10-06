import httpx
from flask import Blueprint, request, jsonify, g
from pydantic import ValidationError
from simplefin import SimpleFINClient

from auth_utils import block_demo_writes, require_auth, require_household
from models.end_points.household import (
    HouseholdMemberAddRequest,
    HouseholdRequest,
    HouseholdSecretsRequest,
    HouseholdSimplefinClaimRequest,
    HouseholdUpdateRequest,
)
from models.household import Household, HouseholdUser
from models.user import User

household_bp = Blueprint("household", __name__)


def household_dict(household: Household):
    """Household dict for API responses. anthropic_api_key and
    simplefin_access_url are write-only — never serialized in full, only
    whether they're set and their last 4 characters (for identification)."""
    data = household.model_dump(
        exclude={
            "anthropic_api_key",
            "simplefin_access_url",
            "stripe_customer_id",
            "stripe_subscription_id",
        }
    )
    data["anthropic_api_key_set"] = bool(household.anthropic_api_key)
    data["anthropic_api_key_suffix"] = (household.anthropic_api_key or "")[-4:]
    data["simplefin_access_url_set"] = bool(household.simplefin_access_url)
    data["simplefin_access_url_suffix"] = (household.simplefin_access_url or "")[-4:]
    data["stripe_customer_id_set"] = bool(household.stripe_customer_id)
    return data


@household_bp.route("/", methods=["POST"])
@require_auth
def get_household():
    try:
        household = None
        household_request = HouseholdRequest.model_validate_json(request.data)
        if household_request.user_id != g.user_id:
            return jsonify({"message": "Forbidden", "status": 0}), 403
        household_users = HouseholdUser.load_by_filter(
            HouseholdUser.user_id == household_request.user_id
        )
        if household_users:
            household_user = household_users[0]
            household = Household.load(household_user.house_hold_id)

        return jsonify({"household": household_dict(household) if household else None})
    except ValidationError as e:
        print(e)
        return (
            jsonify({"errors": e.errors(), "message": "Error", "status": 0}),
            400,
        )


@household_bp.route("/<int:household_id>", methods=["PUT"])
@require_auth
@block_demo_writes
def update_household(household_id):
    try:
        forbidden = require_household(household_id)
        if forbidden:
            return forbidden
        update_request = HouseholdUpdateRequest.model_validate_json(
            request.data
        )
        household = Household.load(household_id)
        if not household:
            return (
                jsonify({"message": "Household not found", "status": 0}),
                404,
            )
        # save() doesn't catch IntegrityError, so pre-check name uniqueness
        name = update_request.name.strip()
        existing = Household.load_by_filter(Household.name == name, limit=1)
        if existing and existing[0].id != household.id:
            return (
                jsonify(
                    {
                        "message": "A household with that name already exists",
                        "status": 0,
                    }
                ),
                409,
            )
        household.name = name
        household.save()

        return jsonify({"household": household_dict(household)})
    except ValidationError as e:
        print(e)
        return (
            jsonify({"errors": e.errors(), "message": "Error", "status": 0}),
            400,
        )


@household_bp.route("/<int:household_id>/members/", methods=["POST"])
@require_auth
@block_demo_writes
def add_member(household_id):
    """
    Add a user to the household by email. Unknown emails get a placeholder
    user (blank names) so they land in this household when they first log in.
    """
    try:
        forbidden = require_household(household_id)
        if forbidden:
            return forbidden
        member_request = HouseholdMemberAddRequest.model_validate_json(
            request.data
        )
        household = Household.load(household_id)
        if not household:
            return (
                jsonify({"message": "Household not found", "status": 0}),
                404,
            )
        user = User.load_by_email(email=member_request.email)
        if not user:
            user = User(
                first_name="",
                last_name="",
                email=member_request.email,
            ).create()
        household_user = household.add_user(user)
        if not household_user:
            return (
                jsonify(
                    {
                        "message": "That user is already a member of this household",
                        "status": 0,
                    }
                ),
                409,
            )

        return jsonify({"user": user.model_dump()})
    except ValidationError as e:
        print(e)
        return (
            jsonify({"errors": e.errors(), "message": "Error", "status": 0}),
            400,
        )


@household_bp.route("/<int:household_id>/secrets", methods=["PUT"])
@require_auth
@block_demo_writes
def update_secrets(household_id):
    """
    Set the household's own Anthropic API key and/or SimpleFin access URL.
    Only the fields provided are updated; the raw values are never returned
    (here or anywhere else) — only whether each is set.
    """
    try:
        forbidden = require_household(household_id)
        if forbidden:
            return forbidden
        secrets_request = HouseholdSecretsRequest.model_validate_json(
            request.data
        )
        household = Household.load(household_id)
        if not household:
            return (
                jsonify({"message": "Household not found", "status": 0}),
                404,
            )
        updates = secrets_request.model_dump(exclude_unset=True)
        for field, value in updates.items():
            setattr(household, field, value)
        household.save()

        return jsonify(
            {
                "anthropic_api_key_set": bool(household.anthropic_api_key),
                "anthropic_api_key_suffix": (household.anthropic_api_key or "")[-4:],
                "simplefin_access_url_set": bool(household.simplefin_access_url),
                "simplefin_access_url_suffix": (household.simplefin_access_url or "")[-4:],
            }
        )
    except ValidationError as e:
        print(e)
        return (
            jsonify({"errors": e.errors(), "message": "Error", "status": 0}),
            400,
        )


@household_bp.route("/<int:household_id>/simplefin-claim", methods=["POST"])
@require_auth
@block_demo_writes
def claim_simplefin_token(household_id):
    """
    Exchange a one-time SimpleFin setup token for a permanent access URL and
    store it. The setup token and access URL are never returned to the
    client — only whether the access URL is now set.
    """
    try:
        forbidden = require_household(household_id)
        if forbidden:
            return forbidden
        claim_request = HouseholdSimplefinClaimRequest.model_validate_json(
            request.data
        )
        household = Household.load(household_id)
        if not household:
            return (
                jsonify({"message": "Household not found", "status": 0}),
                404,
            )
        try:
            access_url = SimpleFINClient.get_access_url(
                claim_request.setup_token.strip()
            )
        except httpx.HTTPStatusError as e:
            return (
                jsonify(
                    {
                        "message": f"SimpleFin rejected the setup token: {e}",
                        "status": 0,
                    }
                ),
                400,
            )
        except Exception as e:
            return jsonify({"message": str(e), "status": 0}), 400

        household.simplefin_access_url = access_url
        household.save()

        return jsonify(
            {
                "simplefin_access_url_set": bool(household.simplefin_access_url),
                "simplefin_access_url_suffix": (household.simplefin_access_url or "")[-4:],
            }
        )
    except ValidationError as e:
        print(e)
        return (
            jsonify({"errors": e.errors(), "message": "Error", "status": 0}),
            400,
        )
