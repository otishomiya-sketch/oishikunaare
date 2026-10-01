"""Admin page: https://<app>/admin

Only for the operator. Not linked from the store screens, and not available at
all until ADMIN_PASSWORD is set in Secrets. Plans are shown as last recorded in
the sheet (column H); the page never calls Stripe per store.
"""

import hmac
import html
import threading
import time
from datetime import datetime, timedelta

import streamlit as st

import billing
import demo_quota

st.set_page_config(page_title="管理画面 | Menu Photo Pro", page_icon="🔒", layout="centered")

st.markdown(
    """
<style>
.block-container { max-width: 760px; padding-top: 2rem; padding-bottom: 4rem; }
@media (max-width: 640px) { .block-container { padding-left: 14px; padding-right: 14px; padding-top: 1rem; } }
.adm-stats { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 8px; margin: 6px 0 12px; }
.adm-stat { background: #FFFFFF; border: 1px solid #D9CCB6; border-radius: 12px; padding: 10px 12px; }
.adm-stat small { display: block; font-size: 12px; color: #6A5D53; }
.adm-stat b { display: block; font-size: 22px; line-height: 1.3; color: #2A211C; }
.adm-stat span { display: block; font-size: 12px; color: #4A3F37; line-height: 1.5; }
.adm-name { font-size: 16px; font-weight: 700; color: #2A211C; }
.adm-badge { display: inline-block; font-size: 11px; font-weight: 700; padding: 1px 8px; border-radius: 999px; margin-left: 6px; vertical-align: 2px; }
.adm-paid { background: #B7412A; color: #FFFFFF; }
.adm-demo { background: #F3E7CF; color: #4A3F37; }
.adm-internal { background: #2A211C; color: #FFFFFF; }
.adm-line { font-size: 13px; color: #4A3F37; line-height: 1.7; }
.adm-line b { color: #2A211C; }
</style>
""",
    unsafe_allow_html=True,
)

MAX_FAILURES = 5
LOCK_SECONDS = 600
NEW_DAYS = 7


def _admin_password():
    try:
        return str(st.secrets.get("ADMIN_PASSWORD", "")).strip()
    except Exception:
        return ""


PASSWORD = _admin_password()
if not PASSWORD:
    # Without a password the page does not exist.
    st.markdown("ページが見つかりません。")
    st.stop()


# ---- Login ----

@st.cache_resource
def _failures():
    """Failed logins per client, shared by every session of this server."""
    return {"lock": threading.Lock(), "hits": {}}


def _client():
    ip = getattr(st.context, "ip_address", None)
    if not ip:
        forwarded = st.context.headers.get("X-Forwarded-For", "")
        ip = forwarded.split(",")[0].strip() if forwarded else "unknown"
    return ip


def _recent_failures(client):
    store = _failures()
    now = time.time()
    with store["lock"]:
        hits = [t for t in store["hits"].get(client, []) if now - t < LOCK_SECONDS]
        store["hits"][client] = hits
        return hits


def _record_failure(client):
    store = _failures()
    with store["lock"]:
        store["hits"].setdefault(client, []).append(time.time())


def login_screen():
    st.title("管理画面")
    with st.form("admin_login"):
        password = st.text_input("管理用パスワード", type="password")
        submitted = st.form_submit_button("ログイン", type="primary", width="stretch")
    if not submitted:
        st.stop()

    client = _client()
    if len(_recent_failures(client)) >= MAX_FAILURES:
        st.error("ログインの失敗が続いたため、10分ほどしてからお試しください。")
        st.stop()
    if hmac.compare_digest(password.encode("utf-8"), PASSWORD.encode("utf-8")):
        st.session_state["admin"] = True
        _failures()["hits"].pop(client, None)
        st.rerun()
    _record_failure(client)
    st.error("パスワードが違います。")
    st.stop()


if not st.session_state.get("admin"):
    login_screen()


# ---- Data ----

top_left, top_right = st.columns([3, 2], vertical_alignment="center")
with top_left:
    st.title("管理画面")
with top_right:
    b1, b2 = st.columns(2)
    if b1.button("更新", width="stretch"):
        st.rerun()
    if b2.button("ログアウト", width="stretch"):
        st.session_state.pop("admin", None)
        st.rerun()

try:
    snapshot = demo_quota.admin_snapshot()
except demo_quota.QuotaError as exc:
    st.error(f"{exc} 時間をおいて「更新」を押してください。")
    st.stop()

stores = snapshot["stores"]
settings = snapshot["settings"]
plans_by_name = {p["name"]: p for p in billing.PLANS}
demo_left_total = max(0, settings["total_limit"] - snapshot["demo_used"])


def status(store):
    if store["internal"]:
        return "internal"
    if store["plan_label"] in plans_by_name:
        return "paid"
    return "demo"


def parse_time(value):
    try:
        return datetime.strptime(value, "%Y-%m-%d %H:%M")
    except ValueError:
        return None


now = datetime.now(demo_quota.JST).replace(tzinfo=None)
new_count = sum(
    1 for s in stores
    if (t := parse_time(s["registered"])) and now - t <= timedelta(days=NEW_DAYS)
)
paid = [s for s in stores if status(s) == "paid"]
demo = [s for s in stores if status(s) == "demo"]
internal = [s for s in stores if status(s) == "internal"]
plan_counts = {name: sum(1 for s in paid if s["plan_label"] == name) for name in plans_by_name}
revenue = sum(plans_by_name[s["plan_label"]]["price"] for s in paid)
from_flyer = [s for s in stores if s["memo"] == demo_quota.SOURCE_NOTES["flyer"]]
from_outreach = [s for s in stores if s["memo"] == demo_quota.SOURCE_NOTES["outreach"]]
month_total = sum(s["count_month"] for s in stores)
all_total = sum(s["count_total"] for s in stores)
year, month = snapshot["month"].split("-")


def stat(label, value, note=""):
    return (
        f'<div class="adm-stat"><small>{label}</small><b>{value}</b>'
        f'{f"<span>{note}</span>" if note else ""}</div>'
    )


st.subheader(f"全体（{year}年{int(month)}月）")
breakdown = "　".join(f"{name} {n}" for name, n in plan_counts.items() if n) or "—"
st.markdown(
    '<div class="adm-stats">'
    + stat("登録したお店", f"{len(stores)}店", f"新規（{NEW_DAYS}日） {new_count}")
    + stat("有料", f"{len(paid)}店", breakdown)
    + stat("無料デモ", f"{len(demo)}店", f"使用 {snapshot['demo_used']:,} / 全体の上限 {settings['total_limit']:,}枚")
    + stat("社内用", f"{len(internal)}件")
    + stat("月の売上見込み", f"{revenue:,}円", "税別・契約中のプランから計算")
    + stat("仕上げた写真", f"今月 {month_total:,}枚", f"合計 {all_total:,}枚（利用履歴より）")
    + stat("チラシ（交流会）から", f"{len(from_flyer)}店",
           f"うち有料 {sum(1 for s in from_flyer if status(s) == 'paid')}店")
    + stat("営業メッセージから", f"{len(from_outreach)}店",
           f"うち有料 {sum(1 for s in from_outreach if status(s) == 'paid')}店")
    + "</div>",
    unsafe_allow_html=True,
)

# ---- Demo settings ----

with st.expander("無料デモの設定"):
    with st.form("demo_settings"):
        total_limit = st.number_input("全店合計の上限（枚）", min_value=0, step=100, value=settings["total_limit"])
        store_limit = st.number_input("新しく登録したお店の上限（枚）", min_value=0, step=1, value=settings["store_limit"])
        if st.form_submit_button("保存", type="primary"):
            try:
                demo_quota.save_settings(int(total_limit), int(store_limit))
            except demo_quota.QuotaError as exc:
                st.error(f"{exc} 時間をおいてもう一度お試しください。")
            else:
                st.session_state["settings_saved"] = True
                st.rerun()
    if st.session_state.pop("settings_saved", False):
        st.success("保存しました。")

# ---- Stores ----

st.subheader("お店の一覧")
query = st.text_input("検索", placeholder="お店の名前・コード・メモ", label_visibility="collapsed")
kind = st.segmented_control(
    "絞り込み", ["すべて", "有料", "無料デモ", "社内用"], default="すべて", label_visibility="collapsed"
) or "すべて"
wanted = {"有料": "paid", "無料デモ": "demo", "社内用": "internal"}.get(kind)

q = query.strip().lower()
shown = [
    s for s in stores
    if (not wanted or status(s) == wanted)
    and (not q or q in f"{s['store']} {s['code']} {s['memo']}".lower())
]
shown.sort(key=lambda s: s["last_used"] or s["registered"], reverse=True)
st.caption(f"{len(shown)}件")

BADGES = {"paid": ("adm-paid", None), "demo": ("adm-demo", "無料デモ"), "internal": ("adm-internal", "社内用")}

for s in shown:
    kind_of = status(s)
    css, label = BADGES[kind_of]
    label = label or f"有料・{s['plan_label']}"
    with st.container(border=True):
        st.markdown(
            f'<div class="adm-name">{html.escape(s["store"] or "（名前なし）")}'
            f'<span class="adm-badge {css}">{html.escape(label)}</span></div>',
            unsafe_allow_html=True,
        )
        st.code(s["code"], language=None)
        if s["memo"]:
            st.markdown(f'<div class="adm-line">メモ：{html.escape(s["memo"])}</div>', unsafe_allow_html=True)

        if kind_of == "paid":
            plan = plans_by_name[s["plan_label"]]
            balance = demo_quota.paid_balance(s, plan["quota"])
            left = (
                f'今月の残り <b>{balance["remaining"]}枚</b>'
                f'（{plan["name"]}・今月 {balance["used"]}枚使用・繰越 {balance["carry"]}枚）'
            )
        else:
            own_left = max(0, s["limit"] - s["used"])
            limit_note = "既定の上限" if not s["limit_raw"] else f"上限 {s['limit']}"
            if kind_of == "internal":
                left = f'残り <b>{own_left}枚</b>（使用 {s["used"]} / {limit_note}・全体の上限には数えない）'
            else:
                left = f'無料デモの残り <b>{min(own_left, demo_left_total)}枚</b>（使用 {s["used"]} / {limit_note}）'
        st.markdown(
            f'<div class="adm-line">{left}<br>'
            f'今月 {s["count_month"]}枚・合計 {s["count_total"]}枚　'
            f'最終利用 {html.escape(s["last_used"] or "—")}　登録 {html.escape(s["registered"] or "—")}</div>',
            unsafe_allow_html=True,
        )

        with st.expander("登録情報"):
            st.markdown(
                f'<div class="adm-line">'
                f'登録日時：{html.escape(s["registered"] or "記録なし")}<br>'
                f'有料プランの記録：{html.escape(s["plan_label"] or "なし")}<br>'
                f'StripeサブスクID：{html.escape(s["subscription_id"] or "—")}<br>'
                f'Stripe顧客ID：{html.escape(s["customer_id"] or "—")}<br>'
                f'管理表の行：{s["row"]}行目</div>',
                unsafe_allow_html=True,
            )
            if s["link"]:
                st.caption("デモ用リンク")
                st.code(s["link"], language=None)

        with st.expander("最近の利用"):
            if not s["history"]:
                st.caption("利用履歴はまだありません。")
            for h in s["history"][:10]:
                st.markdown(
                    f'<div class="adm-line">{html.escape(h["time"])}　{html.escape(h["kind"])}　{h["count"]}枚</div>',
                    unsafe_allow_html=True,
                )

        opened = st.session_state.get("admin_open") == s["code"]
        with st.expander("設定を変える", expanded=opened):
            with st.form(f"edit_{s['code']}"):
                is_internal = st.checkbox(
                    "社内用にする",
                    value=s["internal"],
                    disabled=s["internal_by_code"],
                    help="コードが otis- で始まるお店は、常に社内用です。" if s["internal_by_code"] else None,
                )
                limit_text = st.text_input(
                    "無料デモの上限（空欄なら既定の上限）",
                    value=s["limit_raw"],
                    placeholder=f"既定 {settings['store_limit']}",
                )
                used = st.number_input("無料デモの使用枚数", min_value=0, step=1, value=s["used"])
                memo = st.text_input("メモ", value=s["memo"], max_chars=200)
                if st.form_submit_button("保存", type="primary"):
                    limit_value = limit_text.strip()
                    if limit_value and not limit_value.isdigit():
                        st.error("無料デモの上限は、0以上の数字か空欄にしてください。")
                    else:
                        try:
                            demo_quota.admin_update(
                                s["code"],
                                is_internal or s["internal_by_code"],
                                int(limit_value) if limit_value else None,
                                int(used),
                                memo.strip(),
                            )
                        except demo_quota.QuotaError as exc:
                            st.error(f"{exc} 時間をおいてもう一度お試しください。")
                        else:
                            st.session_state["admin_open"] = s["code"]
                            st.session_state["admin_saved"] = s["code"]
                            st.rerun()
            if st.session_state.get("admin_saved") == s["code"]:
                st.success("保存しました。")
                st.session_state.pop("admin_saved", None)
