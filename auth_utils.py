import datetime
import os
from functools import wraps

import jwt
from flask import g, jsonify, request

from models.household import Household, HouseholdUser

jwt_secret = os.environ["JWT_SECRET"]

JWT_ALGORITHM = "HS256"
JWT_EXPIRY = datetime.timedelta(days=30)

# Fixed user_id for the seeded demo account (see scripts/seed_demo_data.sql).
# Negative so it's permanently outside the real auto-increment range (a
# positive placeholder like 999999 forces AUTO_INCREMENT to jump straight
# past it the moment it's inserted — every real signup after that starts at
# the placeholder + 1 instead of 1).
DEMO_USER_ID = -1

# Stripe subscription statuses that count as "paid up" for gating access.
ACTIVE_SUBSCRIPTION_STATUSES = {"active", "trialing"}


def generate_token(user_id: int) -> str:
    payload = {
        "user_id": user_id,
        "exp": datetime.datetime.now(datetime.timezone.utc) + JWT_EXPIRY,
    }
    return jwt.encode(payload, jwt_secret, algorithm=JWT_ALGORITHM)


def decode_token(token: str):
    try:
        payload = jwt.decode(token, jwt_secret, algorithms=[JWT_ALGORITHM])
        return payload["user_id"]
    except jwt.PyJWTError:
        return None


def require_auth(view):
    @wraps(view)
    def wrapped(*args, **kwargs):
        auth_header = request.headers.get("Authorization", "")
        if not auth_header.startswith("Bearer "):
            return jsonify({"message": "Missing or invalid token", "status": 0}), 401
        user_id = decode_token(auth_header[len("Bearer "):])
        if user_id is None:
            return jsonify({"message": "Missing or invalid token", "status": 0}), 401
        g.user_id = user_id
        return view(*args, **kwargs)

    return wrapped


def block_demo_writes(view):
    """403s any mutating route when called as the demo account. Place below
    @require_auth (so it runs after g.user_id is set) on every route that
    creates/updates/deletes data — the demo household is otherwise a normal,
    fully-authorized household and would happily accept writes."""
    @wraps(view)
    def wrapped(*args, **kwargs):
        if g.user_id == DEMO_USER_ID:
            return jsonify({"message": "The demo account is read-only", "status": 0}), 403
        return view(*args, **kwargs)

    return wrapped


def require_household(household_id: int, allow_unsubscribed: bool = False):
    """Returns a (response, status) tuple if the current user isn't a member
    of household_id, or (unless allow_unsubscribed) the household doesn't
    have an active Stripe subscription, else None. Callers should `return`
    early on a non-None result.

    allow_unsubscribed=True is for the billing routes themselves (a
    household has to be able to start a Checkout session before it's
    subscribed). The demo household is exempt from billing entirely."""
    household_users = HouseholdUser.load_by_filter(HouseholdUser.user_id == g.user_id)
    if not any(hu.house_hold_id == household_id for hu in household_users):
        return jsonify({"message": "Forbidden", "status": 0}), 403
    if not allow_unsubscribed and g.user_id != DEMO_USER_ID:
        household = Household.load(household_id)
        if not household or household.subscription_status not in ACTIVE_SUBSCRIPTION_STATUSES:
            return (
                jsonify(
                    {
                        "message": "An active subscription is required",
                        "status": 0,
                        "subscription_required": True,
                    }
                ),
                402,
            )
    return None


def resolve_household_from_account(account_id: int):
    """Account -> owning user -> household. Returns None if any link is missing."""
    household = Household.load_by_account_id(account_id)
    return household.id if household else None
