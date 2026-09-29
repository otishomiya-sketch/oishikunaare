"""Monthly plans with Stripe (Checkout for sign-up, Customer Portal for changes).

Streamlit cannot receive Stripe webhooks, so the app asks Stripe directly:
after Checkout it reads the session, and later it checks the subscription's
status and price (cached for a few minutes) to know the store's current plan.

Secrets:
    STRIPE_SECRET_KEY    sk_live_... / sk_test_...
    STRIPE_PRICE_LIGHT   price_... (monthly, 1,980 JPY), or the product's prod_...
    STRIPE_PRICE_STANDARD
    STRIPE_PRICE_PRO
    STRIPE_TAX_RATE_ID   txr_... (10% exclusive consumption tax)
"""

import requests
import streamlit as st

STRIPE_API = "https://api.stripe.com/v1"
TAX = 0.10

# Price is before tax. Order is cheapest first.
PLANS = [
    {"key": "light", "name": "ライト", "quota": 10, "price": 1980, "secret": "STRIPE_PRICE_LIGHT"},
    {"key": "standard", "name": "スタンダード", "quota": 20, "price": 2980, "secret": "STRIPE_PRICE_STANDARD"},
    {"key": "pro", "name": "プロ", "quota": 30, "price": 3980, "secret": "STRIPE_PRICE_PRO"},
]

# Stripe statuses that still allow editing. past_due keeps working while Stripe retries the card.
PAID_STATUSES = {"active", "trialing", "past_due"}


class BillingError(RuntimeError):
    pass


def _secret(name):
    try:
        return str(st.secrets[name]).strip()
    except Exception:
        return ""


def enabled():
    """True when every Stripe setting is in Secrets."""
    return all(_secret(n) for n in ["STRIPE_SECRET_KEY", "STRIPE_TAX_RATE_ID"] + [p["secret"] for p in PLANS])


def price_with_tax(plan):
    return round(plan["price"] * (1 + TAX))


def plan_by_key(key):
    return next((p for p in PLANS if p["key"] == key), None)


@st.cache_data(ttl=3600, show_spinner=False)
def _price_id(configured):
    """A price_... as is; for a product's prod_..., the product's default price."""
    if not configured.startswith("prod_"):
        return configured
    product = _request("GET", f"products/{configured}")
    price = product.get("default_price")
    if isinstance(price, dict):
        price = price.get("id")
    if not price:
        raise BillingError("料金プランの価格が設定されていません。")
    return price


def plan_price(plan):
    return _price_id(_secret(plan["secret"]))


def _plan_by_price(price_id, product_id=""):
    for p in PLANS:
        configured = _secret(p["secret"])
        if configured in (price_id, product_id) and configured:
            return p
    return None


def _request(method, path, data=None, params=None):
    try:
        response = requests.request(
            method,
            f"{STRIPE_API}/{path}",
            auth=(_secret("STRIPE_SECRET_KEY"), ""),
            data=data,
            params=params,
            timeout=30,
        )
    except requests.RequestException as exc:
        raise BillingError("決済サービスに接続できませんでした。") from exc
    if not response.ok:
        try:
            message = response.json()["error"]["message"]
        except Exception:
            message = response.text[:300]
        raise BillingError(f"決済サービスでエラーが起きました（{message}）")
    return response.json()


def create_checkout(code, plan, app_url):
    """URL of the Stripe page where the store enters its card for `plan`."""
    session = _request(
        "POST",
        "checkout/sessions",
        data={
            "mode": "subscription",
            "line_items[0][price]": plan_price(plan),
            "line_items[0][quantity]": 1,
            "line_items[0][tax_rates][0]": _secret("STRIPE_TAX_RATE_ID"),
            "client_reference_id": code,
            "metadata[code]": code,
            "subscription_data[metadata][code]": code,
            "locale": "ja",
            "success_url": f"{app_url}/?code={code}&session_id={{CHECKOUT_SESSION_ID}}",
            "cancel_url": f"{app_url}/?code={code}",
        },
    )
    return session["id"], session["url"]


def completed_checkout(session_id, code):
    """(subscription_id, customer_id) once the store has paid, else None."""
    session = _request("GET", f"checkout/sessions/{session_id}")
    if session.get("client_reference_id") != code:
        return None
    if session.get("status") != "complete" or not session.get("subscription"):
        return None
    return session["subscription"], session.get("customer") or ""


@st.cache_data(ttl=300, show_spinner=False)
def subscription_plan(subscription_id):
    """{'plan': plan dict or None, 'status': str} for a subscription, cached for 5 minutes."""
    sub = _request("GET", f"subscriptions/{subscription_id}")
    try:
        price = sub["items"]["data"][0]["price"]
        price_id = price["id"]
        product_id = price.get("product") or ""
        if isinstance(product_id, dict):
            product_id = product_id.get("id", "")
    except (KeyError, IndexError, TypeError):
        price_id = product_id = ""
    status = sub.get("status", "")
    plan = _plan_by_price(price_id, product_id) if status in PAID_STATUSES else None
    return {"plan": plan, "status": status}


def portal_url(customer_id, code, app_url):
    """Stripe's page where the store changes plan, updates its card or cancels."""
    session = _request(
        "POST",
        "billing_portal/sessions",
        data={"customer": customer_id, "return_url": f"{app_url}/?code={code}&portal=1", "locale": "ja"},
    )
    return session["url"]


def find_subscription(code):
    """(subscription_id, customer_id) of the store's live subscription, found by its code.

    Used when a store paid but closed the page before coming back from Stripe.
    """
    if not code.replace("-", "").isalnum():
        return None
    found = _request(
        "GET",
        "subscriptions/search",
        params={"query": f"metadata['code']:'{code}'", "limit": 10},
    )
    for sub in found.get("data", []):
        if sub.get("status") in PAID_STATUSES:
            return sub["id"], sub.get("customer", "")
    return None
