import os

import stripe
from flask import Blueprint, request, jsonify, g
from pydantic import ValidationError

from auth_utils import require_auth, require_household
from models.end_points.billing import (
    BillingCheckoutSessionRequest,
    BillingPortalSessionRequest,
)
from models.household import Household
from models.user import User

billing_bp = Blueprint("billing", __name__)

stripe.api_key = os.environ["STRIPE_SECRET_KEY"]
STRIPE_PRICE_ID = os.environ["STRIPE_PRICE_ID"]
STRIPE_WEBHOOK_SECRET = os.environ["STRIPE_WEBHOOK_SECRET"]
# Where Checkout/the Billing Portal send the browser back to when done.
FRONTEND_URL = os.environ.get("FRONTEND_URL", "http://localhost:5173")
# Free-trial length granted to first-time subscribers. Set here rather than
# on the Stripe Price/Product so the behaviour lives with the code that
# creates the session; 0 disables trials entirely.
STRIPE_TRIAL_DAYS = int(os.environ.get("STRIPE_TRIAL_DAYS", "30"))


def _get_or_create_customer(household: Household, email: str = None) -> str:
    if household.stripe_customer_id:
        try:
            stripe.Customer.retrieve(household.stripe_customer_id)
            return household.stripe_customer_id
        except stripe.InvalidRequestError:
            # Stale reference — e.g. a customer created under a different
            # Stripe mode (test vs. live) than the key currently in use, or
            # deleted directly in the Dashboard. Fall through and mint a
            # fresh one rather than erroring out.
            pass
    customer = stripe.Customer.create(
        name=household.name,
        email=email,
        metadata={"household_id": household.id},
    )
    household.stripe_customer_id = customer.id
    household.save()
    return customer.id


@billing_bp.route("/checkout-session/", methods=["POST"])
@require_auth
def create_checkout_session():
    try:
        checkout_request = BillingCheckoutSessionRequest.model_validate_json(
            request.data
        )
        # allow_unsubscribed=True: a household has to be able to reach
        # Checkout before it has a subscription at all.
        forbidden = require_household(checkout_request.household_id, allow_unsubscribed=True)
        if forbidden:
            return forbidden
        household = Household.load(checkout_request.household_id)
        if not household:
            return jsonify({"message": "Household not found", "status": 0}), 404
        user = User.load(g.user_id)

        # Only ever trial a household that has never subscribed — otherwise
        # cancelling and re-subscribing would hand out a fresh free month
        # every time. Both fields are set by the webhook on first successful
        # checkout, and stripe_subscription_id is never cleared afterwards
        # (a cancellation only moves subscription_status to "canceled"), so
        # together they're a durable record of prior billing history.
        is_first_subscription = (
            household.stripe_subscription_id is None
            and household.subscription_status is None
        )

        session_kwargs = {}
        if STRIPE_TRIAL_DAYS and is_first_subscription:
            session_kwargs["subscription_data"] = {
                "trial_period_days": STRIPE_TRIAL_DAYS,
                # No card is collected up front (see below), so Stripe needs
                # to be told what to do when the trial ends without one.
                # "cancel" ends the subscription, which the webhook writes
                # through as subscription_status="canceled" — the household
                # simply loses access and can subscribe again (without a
                # trial the second time, per the gate above). The
                # alternatives are worse here: "create_invoice" would bill
                # someone who never entered a payment method, and "pause"
                # leaves a state nothing else in the app understands.
                "trial_settings": {
                    "end_behavior": {"missing_payment_method": "cancel"}
                },
            }
            # Skip card collection for the trial. "if_required" only skips it
            # when the total due is 0, which for us only happens because of
            # the trial — a non-trial checkout still collects a card — but
            # it's set inside this branch anyway so the paid path is
            # untouched and keeps Stripe's "always" default.
            session_kwargs["payment_method_collection"] = "if_required"

        session = stripe.checkout.Session.create(
            mode="subscription",
            customer=_get_or_create_customer(household, email=user.email if user else None),
            line_items=[{"price": STRIPE_PRICE_ID, "quantity": 1}],
            success_url=f"{FRONTEND_URL}/dashboard?checkout=success",
            cancel_url=f"{FRONTEND_URL}/dashboard?checkout=cancelled",
            client_reference_id=str(household.id),
            **session_kwargs,
        )
        return jsonify({"url": session.url})
    except ValidationError as e:
        print(e)
        return (
            jsonify({"errors": e.errors(), "message": "Error", "status": 0}),
            400,
        )


@billing_bp.route("/portal-session/", methods=["POST"])
@require_auth
def create_portal_session():
    try:
        portal_request = BillingPortalSessionRequest.model_validate_json(
            request.data
        )
        forbidden = require_household(portal_request.household_id, allow_unsubscribed=True)
        if forbidden:
            return forbidden
        household = Household.load(portal_request.household_id)
        if not household or not household.stripe_customer_id:
            return (
                jsonify({"message": "This household has no billing account yet", "status": 0}),
                400,
            )

        try:
            session = stripe.billing_portal.Session.create(
                customer=household.stripe_customer_id,
                return_url=f"{FRONTEND_URL}/dashboard",
            )
        except stripe.InvalidRequestError:
            # Stale customer reference (e.g. created under a different
            # Stripe mode) — there's nothing to open a portal session for.
            return (
                jsonify({"message": "This household has no billing account yet", "status": 0}),
                400,
            )
        return jsonify({"url": session.url})
    except ValidationError as e:
        print(e)
        return (
            jsonify({"errors": e.errors(), "message": "Error", "status": 0}),
            400,
        )


@billing_bp.route("/webhook/", methods=["POST"])
def stripe_webhook():
    """Stripe -> us. Unauthenticated (Stripe can't send our JWT) — trust is
    established entirely by verifying the signature below. This is the only
    place subscription_status is ever written; never trust the client."""
    payload = request.data
    sig_header = request.headers.get("Stripe-Signature", "")
    try:
        event = stripe.Webhook.construct_event(payload, sig_header, STRIPE_WEBHOOK_SECRET)
    except (ValueError, stripe.SignatureVerificationError) as e:
        print(e)
        return jsonify({"message": "Invalid signature", "status": 0}), 400

    obj = event["data"]["object"]
    event_type = event["type"]

    if event_type == "checkout.session.completed":
        household_id = obj["client_reference_id"] if "client_reference_id" in obj else None
        household = Household.load(int(household_id)) if household_id else None
        if household and obj["subscription"]:
            subscription = stripe.Subscription.retrieve(obj["subscription"])
            household.stripe_customer_id = subscription.customer
            household.stripe_subscription_id = subscription.id
            household.subscription_status = subscription.status
            household.save()
    elif event_type in ("customer.subscription.updated", "customer.subscription.deleted"):
        households = Household.load_by_filter(
            Household.stripe_subscription_id == obj["id"], limit=1
        )
        if households:
            household = households[0]
            household.subscription_status = obj["status"]
            household.save()

    return jsonify({"status": 1})
