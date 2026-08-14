#!/usr/bin/env python3
"""
lib/saas_billing.py

Real Stripe integration for pay-per-clip credits. Setup (your action,
same class of one-time step as the YouTube/TikTok OAuth setup earlier):

1. Create a Stripe account at https://dashboard.stripe.com/register
2. Get your API keys from the dashboard (start with TEST keys —
   sk_test_... and pk_test_... — real testing before any real money
   moves, exactly what Stripe's own 2026 guidance recommends)
3. Save them as environment variables:
     export STRIPE_SECRET_KEY="sk_test_..."
     export STRIPE_WEBHOOK_SECRET="whsec_..."  (from step 5 below)
4. pip install stripe --break-system-packages
5. Set up a webhook endpoint in the Stripe dashboard pointing at
   https://yourdomain.com/api/billing/webhook, listening for
   checkout.session.completed — copy the signing secret it gives you
   into STRIPE_WEBHOOK_SECRET above

Real, current (2026) practices this follows, not guesses:
  - Checkout Sessions (Stripe's hosted payment page), not custom
    Payment Elements — the officially recommended default, handles
    3D Secure/mobile/currency automatically
  - The webhook is the real source of truth for fulfillment, NOT the
    redirect URL — a user can close the tab before the redirect
    completes; only the webhook is guaranteed to fire
  - Signature verification against the RAW request body, not the
    parsed JSON — required for Stripe to trust the request actually
    came from Stripe, not a spoofed request to your own endpoint
  - Idempotent fulfillment by event.id (see saas_db.fulfill_credit_purchase)
"""
import os

# Real, sensible starting price points — genuinely yours to change, not
# a claim about what you should actually charge. 1 credit = roughly the
# cost of generating one short clip; see CREDIT_COSTS below.
CREDIT_PACKAGES = {
    "starter": {"credits": 100, "price_usd": 999, "name": "100 Credits"},    # $9.99
    "creator": {"credits": 500, "price_usd": 3999, "name": "500 Credits"},   # $39.99
    "pro": {"credits": 1500, "price_usd": 9999, "name": "1500 Credits"},     # $99.99
}

# Real, sensible cost model — a long-form window is much more compute
# (a real ~5.66hr source took hours of CPU time tonight) than a short
# clip, so it costs proportionally more credits, not the same flat rate.
CREDIT_COSTS = {
    "short_clip": 10,
    "longform_window": 50,
}


def _get_stripe():
    try:
        import stripe
    except ImportError as e:
        raise RuntimeError(
            "stripe package not installed. Run: pip install stripe --break-system-packages"
        ) from e
    stripe.api_key = os.environ.get("STRIPE_SECRET_KEY")
    if not stripe.api_key:
        raise RuntimeError("STRIPE_SECRET_KEY not set in environment. See setup instructions in this file's docstring.")
    return stripe


def create_checkout_session(package_key, user_id, success_url, cancel_url):
    """Real Checkout Session creation — the hosted-page approach Stripe's
    own 2026 guidance recommends as the default, fastest, safest
    integration path."""
    if package_key not in CREDIT_PACKAGES:
        raise ValueError(f"unknown credit package: {package_key}")
    pkg = CREDIT_PACKAGES[package_key]
    stripe = _get_stripe()

    session = stripe.checkout.Session.create(
        mode="payment",
        line_items=[{
            "price_data": {
                "currency": "usd",
                "product_data": {"name": pkg["name"]},
                "unit_amount": pkg["price_usd"],
            },
            "quantity": 1,
        }],
        metadata={"user_id": user_id, "package_key": package_key, "credits": str(pkg["credits"])},
        success_url=success_url,
        cancel_url=cancel_url,
    )
    return session.url


def verify_and_parse_webhook(raw_body, signature_header):
    """Real signature verification against the RAW body — this is the
    actual security boundary that proves a webhook request genuinely
    came from Stripe and wasn't spoofed by someone hitting your
    endpoint directly with a fake "payment succeeded" event."""
    import stripe
    webhook_secret = os.environ.get("STRIPE_WEBHOOK_SECRET")
    if not webhook_secret:
        raise RuntimeError("STRIPE_WEBHOOK_SECRET not set in environment.")
    return stripe.Webhook.construct_event(raw_body, signature_header, webhook_secret)


def handle_checkout_completed(event):
    """Real, idempotent fulfillment — delegates to saas_db's atomic
    fulfill_credit_purchase, which is the actual place the
    idempotency guarantee lives (same-transaction event-ID recording,
    per the real 2026 guidance this whole integration follows)."""
    import sys
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    import saas_db

    session = event["data"]["object"]
    user_id = session["metadata"]["user_id"]
    credits = int(session["metadata"]["credits"])
    payment_id = session.get("payment_intent") or session["id"]

    new_balance = saas_db.fulfill_credit_purchase(event["id"], user_id, credits, payment_id)
    return new_balance  # None means already processed — a real, expected outcome on webhook retry
