"""Demo limits per store and in total, kept in a Google Sheet.

First worksheet (row 1 is the header), one row per store:
    A: お店  B: コード  C: 上限  D: 使用枚数  E: 最終利用日時  F: デモ用リンク  G: メモ

Worksheet "設定" (created on first use):
    B1: 全店合計の上限   B2: 自動登録したお店の上限

Codes starting with "otis-" are internal test accounts: they are not counted
toward, or limited by, the overall total.
"""

import secrets
from datetime import datetime, timedelta, timezone

import gspread
import streamlit as st

COL_STORE = 1
COL_CODE = 2
COL_LIMIT = 3
COL_USED = 4

SETTINGS_SHEET = "設定"
DEFAULT_TOTAL_LIMIT = 3000
DEFAULT_STORE_LIMIT = 10
INTERNAL_PREFIX = "otis-"
CODE_ALPHABET = "abcdefghjkmnpqrstuvwxyz23456789"

JST = timezone(timedelta(hours=9))


class QuotaError(RuntimeError):
    pass


@st.cache_resource(show_spinner=False)
def _spreadsheet():
    try:
        client = gspread.service_account_from_dict(dict(st.secrets["gcp_service_account"]))
        return client.open_by_key(str(st.secrets["DEMO_SHEET_ID"]).strip())
    except Exception as exc:
        raise QuotaError("デモ利用の管理表に接続できませんでした。") from exc


def _stores():
    return _spreadsheet().get_worksheet(0)


def _now():
    return datetime.now(JST).strftime("%Y-%m-%d %H:%M")


def _to_int(value, default=0):
    try:
        return int(str(value).replace(",", "").strip())
    except ValueError:
        return default


@st.cache_data(ttl=300, show_spinner=False)
def settings():
    """{'total_limit', 'store_limit'} from the 設定 sheet (cached for 5 minutes)."""
    try:
        book = _spreadsheet()
        try:
            sheet = book.worksheet(SETTINGS_SHEET)
        except gspread.WorksheetNotFound:
            sheet = book.add_worksheet(SETTINGS_SHEET, rows=10, cols=3)
            sheet.update(
                range_name="A1:C2",
                values=[
                    ["全店合計の上限", DEFAULT_TOTAL_LIMIT, "全店の使用枚数の合計がこの枚数に達すると、デモを終了します"],
                    ["自動登録したお店の上限", DEFAULT_STORE_LIMIT, "LINEのリンクから登録したお店に最初に付く枚数です"],
                ],
            )
        values = sheet.get("B1:B2")
    except QuotaError:
        raise
    except Exception as exc:
        raise QuotaError("デモ利用の設定を読み込めませんでした。") from exc

    cell = lambda i, default: _to_int(values[i][0], default) if len(values) > i and values[i] else default
    return {
        "total_limit": cell(0, DEFAULT_TOTAL_LIMIT),
        "store_limit": cell(1, DEFAULT_STORE_LIMIT),
    }


def _read():
    """(rows, total_used). One read per call keeps inside the Sheets API quota."""
    try:
        rows = _stores().get_all_values()
    except QuotaError:
        raise
    except Exception as exc:
        raise QuotaError("デモ利用の管理表を読み込めませんでした。") from exc

    rows = [row + [""] * 7 for row in rows]
    total_used = sum(
        _to_int(row[COL_USED - 1])
        for row in rows[1:]
        if row[COL_CODE - 1].strip() and not row[COL_CODE - 1].strip().startswith(INTERNAL_PREFIX)
    )
    return rows, total_used


def _account(rows, total_used, code):
    for row_number, row in enumerate(rows, start=1):
        if row_number > 1 and row[COL_CODE - 1].strip() == code:
            limit = _to_int(row[COL_LIMIT - 1])
            used = _to_int(row[COL_USED - 1])
            store_left = max(0, limit - used)
            if code.startswith(INTERNAL_PREFIX):
                total_left = store_left
            else:
                total_left = max(0, settings()["total_limit"] - total_used)
            return {
                "row": row_number,
                "store": row[COL_STORE - 1].strip(),
                "limit": limit,
                "used": used,
                "remaining": min(store_left, total_left),
                "total_exhausted": total_left == 0,
            }
    return None


def _write_used(row_number, used):
    try:
        _stores().update(range_name=f"D{row_number}:E{row_number}", values=[[used, _now()]])
    except Exception as exc:
        raise QuotaError("デモ利用の管理表に書き込めませんでした。") from exc


def total_remaining():
    _, total_used = _read()
    return max(0, settings()["total_limit"] - total_used)


def get_account(code):
    """The store's limits for a valid code, else None."""
    if not code:
        return None
    rows, total_used = _read()
    return _account(rows, total_used, code)


def register(store_name, app_url):
    """Add a store with the default limit and return its new code."""
    rows, _ = _read()
    taken = {row[COL_CODE - 1].strip() for row in rows}
    code = "demo-" + "".join(secrets.choice(CODE_ALPHABET) for _ in range(6))
    while code in taken:
        code = "demo-" + "".join(secrets.choice(CODE_ALPHABET) for _ in range(6))

    try:
        # RAW input stores the name as plain text, never as a formula.
        _stores().append_row(
            [store_name, code, settings()["store_limit"], 0, _now(), f"{app_url}/?code={code}", "LINEのリンクから自動登録"],
            value_input_option="RAW",
        )
    except Exception as exc:
        raise QuotaError("お店の登録に失敗しました。") from exc
    return code


def reserve(code, count):
    """Set aside up to `count` photos before editing. Returns how many were granted."""
    rows, total_used = _read()
    account = _account(rows, total_used, code)
    if not account:
        return 0
    granted = max(0, min(count, account["remaining"]))
    if granted:
        _write_used(account["row"], account["used"] + granted)
    return granted


def release(code, count):
    """Give back photos that were reserved but failed to edit."""
    if count <= 0:
        return
    rows, total_used = _read()
    account = _account(rows, total_used, code)
    if account:
        _write_used(account["row"], max(0, account["used"] - count))
