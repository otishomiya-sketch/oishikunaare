"""Ticket purchases with Stripe Checkout (via its REST API)."""

import requests
import streamlit as st

STRIPE_API = "https://api.stripe.com/v1"


class BillingError(RuntimeError):
    pass


def _request(method, path, data=None):
    key = str(st.secrets["STRIPE_SECRET_KEY"]).strip()
    try:
        response = requests.request(
            method, f"{STRIPE_API}/{path}", auth=(key, ""), data=data, timeout=30
        )
    except requests.RequestException as exc:
        raise BillingError("決済サービスに接続できませんでした。") from exc

    if not response.ok:
        try:
            message = response.json()["error"]["message"]
        except Exception:
            message = response.text[:300]
        raise BillingError(f"Stripe error {response.status_code}: {message}")
    return response.json()


def get_plans():
    """Ticket packs from the [[plans]] tables in Secrets."""
    try:
        return [
            {
                "name": str(plan["name"]),
                "credits": int(plan["credits"]),
                "price_id": str(plan["price_id"]),
            }
            for plan in st.secrets["plans"]
        ]
    except Exception:
        return []


@st.cache_data(ttl=3600, show_spinner=False)
def price_label(price_id):
    price = _request("GET", f"prices/{price_id}")
    amount = price.get("unit_amount") or 0
    currency = price.get("currency", "").lower()
    if currency == "jpy":
        return f"¥{amount:,}"
    return f"{amount / 100:,.2f} {currency.upper()}"


def create_checkout(user_id, plan):
    """Return (session_id, url) of a new Stripe Checkout page."""
    app_url = str(st.secrets["APP_URL"]).strip().rstrip("/")
    session = _request(
        "POST",
        "checkout/sessions",
        data={
            "mode": "payment",
            "line_items[0][price]": plan["price_id"],
            "line_items[0][quantity]": 1,
            "client_reference_id": user_id,
            "metadata[user_id]": user_id,
            "metadata[credits]": plan["credits"],
            "locale": "ja",
            "success_url": f"{app_url}/?session_id={{CHECKOUT_SESSION_ID}}",
            "cancel_url": f"{app_url}/",
        },
    )
    return session["id"], session["url"]


def checkout_status(session_id):
    """Return 'paid', 'expired', or 'open'."""
    session = _request("GET", f"checkout/sessions/{session_id}")
    if session.get("payment_status") == "paid":
        return "paid"
    if session.get("status") == "expired":
        return "expired"
    return "open"
