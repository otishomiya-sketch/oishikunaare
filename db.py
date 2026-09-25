"""Member and ticket storage in Supabase (via its REST API).

Tables and functions are created by supabase_setup.sql.
"""

import requests
import streamlit as st


class DatabaseError(RuntimeError):
    pass


def _config():
    url = str(st.secrets["SUPABASE_URL"]).strip().rstrip("/")
    key = str(st.secrets["SUPABASE_SERVICE_KEY"]).strip()
    headers = {"apikey": key, "Content-Type": "application/json"}
    # Legacy service_role keys are JWTs and also go in Authorization.
    # New sb_secret_ keys must only be sent as apikey.
    if key.startswith("eyJ"):
        headers["Authorization"] = f"Bearer {key}"
    return url + "/rest/v1", headers


def _request(method, path, ok_statuses=(), **kwargs):
    base, headers = _config()
    headers.update(kwargs.pop("headers", {}))
    try:
        response = requests.request(
            method, f"{base}/{path}", headers=headers, timeout=20, **kwargs
        )
    except requests.RequestException as exc:
        raise DatabaseError("データベースに接続できませんでした。") from exc

    if response.status_code in ok_statuses:
        return response
    if not response.ok:
        raise DatabaseError(
            f"Database error {response.status_code}: {response.text[:300]}"
        )
    return response


def _json(response):
    return response.json() if response.content else None


def _rpc(name, **params):
    return _json(_request("POST", f"rpc/{name}", json=params))


def get_user(user_id):
    rows = _json(
        _request(
            "GET",
            "app_users",
            params={
                "user_id": f"eq.{user_id}",
                "select": "user_id,password_hash,credits",
            },
        )
    )
    return rows[0] if rows else None


def create_user(user_id, password_hash):
    """Return False when the ID is already taken."""
    response = _request(
        "POST",
        "app_users",
        ok_statuses=(409,),
        json={"user_id": user_id, "password_hash": password_hash},
        headers={"Prefer": "return=minimal"},
    )
    return response.status_code != 409


def get_credits(user_id):
    user = get_user(user_id)
    return user["credits"] if user else 0


def use_credit(user_id):
    """Take one ticket. Return the remaining count, or None if none were left."""
    return _rpc("use_credit", p_user_id=user_id)


def add_credits(user_id, amount):
    return _rpc("add_credits", p_user_id=user_id, p_amount=amount)


def add_pending_purchase(session_id, user_id, credits):
    _request(
        "POST",
        "purchases",
        json={"session_id": session_id, "user_id": user_id, "credits": credits},
        headers={"Prefer": "return=minimal"},
    )


def pending_purchases(user_id):
    rows = _json(
        _request(
            "GET",
            "purchases",
            params={
                "user_id": f"eq.{user_id}",
                "status": "eq.pending",
                "select": "session_id",
            },
        )
    )
    return [row["session_id"] for row in rows or []]


def complete_purchase(session_id):
    """Add the purchase's tickets once. Return False if already done or unknown."""
    return bool(_rpc("complete_purchase", p_session_id=session_id))


def expire_purchase(session_id):
    _request(
        "PATCH",
        "purchases",
        params={"session_id": f"eq.{session_id}", "status": "eq.pending"},
        json={"status": "expired"},
        headers={"Prefer": "return=minimal"},
    )


def list_users():
    return _json(
        _request(
            "GET",
            "app_users",
            params={
                "select": "user_id,credits,created_at",
                "order": "created_at.desc",
            },
        )
    ) or []
