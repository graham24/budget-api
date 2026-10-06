from flask import Blueprint, request, jsonify
from pydantic import ValidationError

from auth_utils import block_demo_writes, require_auth, require_household
from models.end_points.user import UsersRequest, UserUpdateRequest
from models.household import HouseholdUser
from models.user import User

users_bp = Blueprint("users", __name__)


@users_bp.route("/", methods=["GET"])
@require_auth
def get_users():
    try:
        users_request = UsersRequest.model_validate(request.args.to_dict())
        forbidden = require_household(users_request.house_hold_id)
        if forbidden:
            return forbidden
        household_users = HouseholdUser.load_by_filter(
            HouseholdUser.house_hold_id == users_request.house_hold_id
        )
        users = User.load_by_filter(
            column=User.id,
            values=[
                household_user.user_id for household_user in household_users
            ],
        )

        return jsonify({"users": [user.model_dump() for user in users]})
    except ValidationError as e:
        print(e)
        return (
            jsonify({"errors": e.errors(), "message": "Error", "status": 0}),
            400,
        )


@users_bp.route("/<int:user_id>", methods=["PUT"])
@require_auth
@block_demo_writes
def update_user(user_id):
    try:
        update_request = UserUpdateRequest.model_validate_json(request.data)
        user = User.load(user_id)
        if not user:
            return (
                jsonify({"message": "User not found", "status": 0}),
                404,
            )
        household_users = HouseholdUser.load_by_filter(
            HouseholdUser.user_id == user_id
        )
        if not household_users:
            return jsonify({"message": "Forbidden", "status": 0}), 403
        forbidden = require_household(household_users[0].house_hold_id)
        if forbidden:
            return forbidden
        # save() doesn't catch IntegrityError, so pre-check email uniqueness
        if update_request.email and update_request.email != user.email:
            existing = User.load_by_email(email=update_request.email)
            if existing and existing.id != user.id:
                return (
                    jsonify(
                        {
                            "message": "That email is already in use",
                            "status": 0,
                        }
                    ),
                    409,
                )
        updates = update_request.model_dump(
            exclude_unset=True, exclude_none=True
        )
        for field, value in updates.items():
            setattr(user, field, value)
        user.save()

        return jsonify({"user": user.model_dump()})
    except ValidationError as e:
        print(e)
        return (
            jsonify({"errors": e.errors(), "message": "Error", "status": 0}),
            400,
        )
