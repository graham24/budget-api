from flask import Blueprint, request, jsonify
from pydantic import ValidationError
from sqlalchemy import func

from auth_utils import DEMO_USER_ID, generate_token
from models.end_points.auth import EmailLoginRequest
from models.user import User

auth_bp = Blueprint("auth", __name__)


@auth_bp.route("/email/", methods=["POST"])
def email_login():
    """
    Log in by email alone — no password or third-party check. Deliberate:
    this is a local-only app on a trusted home network, so anyone who can
    reach the API and knows a user's email can act as that user. Unknown
    emails 404 rather than creating an account.
    """
    try:
        login_request = EmailLoginRequest.model_validate_json(request.data)
    except ValidationError as e:
        print(e)
        return (
            jsonify({"errors": e.errors(), "message": "Error", "status": 0}),
            400,
        )

    email = login_request.email.strip().lower()
    users = User.load_by_filter(func.lower(User.email) == email, limit=1)
    if not users:
        return jsonify({"message": "No account with that email", "status": 0}), 404

    token = generate_token(users[0].id)
    return jsonify({"user": users[0].model_dump(), "token": token})


@auth_bp.route("/demo/", methods=["POST"])
def demo_login():
    """
    Unauthenticated login for the seeded demo account (scripts/seed_demo_data.sql)
    — no Google credential needed. The demo user can fully read/write within
    its own sandboxed household like any other account; nothing here makes it
    read-only. 404s if the
    demo user hasn't been seeded, so this is a no-op unless someone has
    deliberately run that script against the DB.
    """
    user = User.load(DEMO_USER_ID)
    if not user:
        return jsonify({"message": "Demo account not available", "status": 0}), 404

    token = generate_token(user.id)
    return jsonify({"user": user.model_dump(), "token": token})
