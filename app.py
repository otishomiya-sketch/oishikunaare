import base64
import io
import time
import zipfile
from pathlib import Path

import requests
import streamlit as st
from PIL import Image, ImageOps, UnidentifiedImageError

import billing
import db
from auth import MIN_PASSWORD_LENGTH, USER_ID_PATTERN, make_hash, verify_password

st.set_page_config(
    page_title="Menu Photo Pro",
    page_icon="🍽️",
    layout="wide",
)

PROMPT = """Edit the supplied food photo into a polished professional restaurant/menu photograph.

SOURCE-OF-TRUTH RULES:
- The supplied image is the source of truth.
- Preserve exactly the same dishes, ingredients, plates, bowls, trays, portion sizes, piece counts, and visible food components.
- Do NOT add, remove, replace, invent, or rearrange food.
- Do NOT add garnish, sauces, drinks, bread, soup, toppings, or side dishes that are not already present.
- Keep the identity of the food unchanged.
- Do not change the amount of food.

EDIT ONLY THE PRESENTATION:
- professional menu-photo composition
- clean restaurant/menu background
- natural soft lighting
- accurate white balance
- appetizing but realistic color
- subtle depth of field
- clean table surface
- tasteful non-food props only when helpful
- realistic photographic texture
- no artificial steam unless the source clearly contains steam

IMPORTANT:
- Preserve the food's shape, texture, color, and arrangement as closely as possible.
- Do not turn the dish into a different recipe.
- Make the result look like a professionally photographed version of the same original dish.
"""


def get_api_key():
    try:
        key = st.secrets["OPENAI_API_KEY"]
        return str(key).strip() if key else None
    except Exception:
        return None



def normalize_image(image_bytes, max_edge=3840):
    """Convert any accepted upload into a clean RGB PNG.

    This prevents CMYK, palette, grayscale, EXIF orientation, and other
    camera/phone-specific modes from causing image-edit upload errors.
    """
    try:
        with Image.open(io.BytesIO(image_bytes)) as original:
            image = ImageOps.exif_transpose(original)

            # Food photos do not need alpha for this workflow.
            if image.mode != "RGB":
                image = image.convert("RGB")
            else:
                image = image.copy()

            # Avoid unnecessarily huge uploads while preserving aspect ratio.
            if max(image.size) > max_edge:
                scale = max_edge / max(image.size)
                new_size = (
                    max(1, round(image.width * scale)),
                    max(1, round(image.height * scale)),
                )
                image = image.resize(new_size, Image.Resampling.LANCZOS)

            output = io.BytesIO()
            image.save(output, format="PNG", optimize=True)
            return output.getvalue()

    except (UnidentifiedImageError, OSError, ValueError) as exc:
        raise RuntimeError(
            "画像を読み込めませんでした。JPG / JPEG / PNG / WebP の画像を選択してください。"
        ) from exc


def edit_image(api_key, image_bytes, filename, style, quality="high"):
    normalized_bytes = normalize_image(image_bytes)

    response = requests.post(
        "https://api.openai.com/v1/images/edits",
        headers={
            "Authorization": f"Bearer {api_key}",
        },
        data={
            "model": "gpt-image-2",
            "prompt": PROMPT + "\n\nSTYLE DIRECTION:\n" + style,
            "quality": quality,
            "output_format": "png",
        },
        files={
            "image[]": ("input.png", normalized_bytes, "image/png"),
        },
        timeout=300,
    )

    if not response.ok:
        try:
            error_json = response.json()
            error_message = (
                error_json.get("error", {}).get("message")
                or response.text[:1000]
            )
        except Exception:
            error_message = response.text[:1000]

        raise RuntimeError(
            f"Image API error {response.status_code}: {error_message}"
        )

    try:
        data = response.json()["data"][0]
    except (KeyError, IndexError, TypeError, ValueError) as exc:
        raise RuntimeError("OpenAIから画像データを取得できませんでした。") from exc

    if data.get("b64_json"):
        return base64.b64decode(data["b64_json"])

    if data.get("url"):
        download = requests.get(data["url"], timeout=120)
        download.raise_for_status()
        return download.content

    raise RuntimeError("生成された画像データを取得できませんでした。")




# ---- Accounts and tickets ----

MAX_LOGIN_ATTEMPTS = 5
LOCKOUT_SECONDS = 300
REQUIRED_SECRETS = [
    "OPENAI_API_KEY",
    "SUPABASE_URL",
    "SUPABASE_SERVICE_KEY",
    "STRIPE_SECRET_KEY",
    "APP_URL",
]


def get_admins():
    """Return {admin_id: password_hash} from the [admins] table in Secrets."""
    try:
        return {str(k): str(v) for k, v in st.secrets["admins"].items()}
    except Exception:
        return {}


def missing_settings():
    missing = []
    for name in REQUIRED_SECRETS:
        try:
            if not str(st.secrets[name]).strip():
                missing.append(name)
        except Exception:
            missing.append(name)
    if not get_admins():
        missing.append("[admins]")
    if not billing.get_plans():
        missing.append("[[plans]]")
    return missing


def authenticate(user_id, password):
    """Return 'admin', 'member', or None."""
    admins = get_admins()
    if user_id in admins:
        return "admin" if verify_password(password, admins[user_id]) else None
    user = db.get_user(user_id)
    if user and verify_password(password, user["password_hash"]):
        return "member"
    return None


def start_session(user_id, role):
    st.session_state["user"] = user_id
    st.session_state["role"] = role
    st.session_state["failed_logins"] = 0


def sync_pending_purchases(user_id):
    """Add tickets for Stripe payments that finished but were not yet counted."""
    added = 0
    for session_id in db.pending_purchases(user_id):
        status = billing.checkout_status(session_id)
        if status == "paid" and db.complete_purchase(session_id):
            added += 1
        elif status == "expired":
            db.expire_purchase(session_id)
    return added


def handle_checkout_return():
    """Stripe sends the buyer back with ?session_id=... after paying."""
    session_id = st.query_params.get("session_id")
    if not session_id:
        return
    st.query_params.clear()
    try:
        if billing.checkout_status(session_id) == "paid":
            if db.complete_purchase(session_id):
                st.session_state["flash"] = "お支払いを確認し、チケットを追加しました。"
            else:
                st.session_state["flash"] = "このお支払いはすでにチケットに反映済みです。"
    except (billing.BillingError, db.DatabaseError) as exc:
        st.session_state["flash_error"] = f"お支払いの確認に失敗しました: {exc}"


def show_flash():
    if "flash" in st.session_state:
        st.success(st.session_state.pop("flash"))
    if "flash_error" in st.session_state:
        st.error(st.session_state.pop("flash_error"))


def login_form():
    locked_until = st.session_state.get("locked_until", 0)
    if time.time() < locked_until:
        remaining = int(locked_until - time.time()) + 1
        st.error(f"ログインに続けて失敗したため、{remaining}秒後に再度お試しください。")
        return

    with st.form("login"):
        user_id = st.text_input("ID")
        password = st.text_input("パスワード", type="password")
        submitted = st.form_submit_button(
            "ログイン", type="primary", width="stretch"
        )

    if not submitted:
        return

    user_id = user_id.strip()
    try:
        role = authenticate(user_id, password)
    except db.DatabaseError as exc:
        st.error(f"ログインできませんでした: {exc}")
        return

    if role:
        start_session(user_id, role)
        if role == "member":
            try:
                if sync_pending_purchases(user_id):
                    st.session_state["flash"] = "お支払い済みのチケットを追加しました。"
            except (billing.BillingError, db.DatabaseError):
                pass
        st.rerun()

    failed = st.session_state.get("failed_logins", 0) + 1
    st.session_state["failed_logins"] = failed
    if failed >= MAX_LOGIN_ATTEMPTS:
        st.session_state["locked_until"] = time.time() + LOCKOUT_SECONDS
        st.session_state["failed_logins"] = 0
    st.error("IDまたはパスワードが正しくありません。")


def signup_form():
    terms_url = str(st.secrets.get("TERMS_URL", "")).strip()

    with st.form("signup"):
        user_id = st.text_input(
            "ID", help="半角英数字・ハイフン・アンダースコアで3〜32文字"
        )
        password = st.text_input(
            "パスワード", type="password", help=f"{MIN_PASSWORD_LENGTH}文字以上"
        )
        password_confirm = st.text_input("パスワード（確認）", type="password")
        agreed = True
        if terms_url:
            st.markdown(f"[利用規約・特定商取引法に基づく表記]({terms_url})")
            agreed = st.checkbox("利用規約に同意します")
        submitted = st.form_submit_button(
            "登録する", type="primary", width="stretch"
        )

    if not submitted:
        return

    user_id = user_id.strip()
    if not USER_ID_PATTERN.match(user_id):
        st.error("IDは半角英数字・ハイフン・アンダースコアで3〜32文字にしてください。")
    elif len(password) < MIN_PASSWORD_LENGTH:
        st.error(f"パスワードは{MIN_PASSWORD_LENGTH}文字以上にしてください。")
    elif password != password_confirm:
        st.error("パスワードが一致しません。")
    elif not agreed:
        st.error("利用規約への同意が必要です。")
    elif user_id in get_admins():
        st.error("このIDはすでに使われています。")
    else:
        try:
            created = db.create_user(user_id, make_hash(password))
        except db.DatabaseError as exc:
            st.error(f"登録できませんでした: {exc}")
            return
        if not created:
            st.error("このIDはすでに使われています。")
            return
        start_session(user_id, "member")
        st.session_state["flash"] = "登録が完了しました。チケットを購入すると写真を加工できます。"
        st.rerun()


def auth_screen():
    st.title("🍽️ Menu Photo Pro")
    st.markdown("### 料理写真を、そのまま活かしてプロ品質のメニュー写真へ")
    show_flash()

    login_tab, signup_tab = st.tabs(["ログイン", "新規登録"])
    with login_tab:
        login_form()
    with signup_tab:
        signup_form()
    st.stop()


def purchase_panel(user_id):
    st.subheader("チケット購入")
    st.caption("写真1枚の加工につきチケット1枚を使います。")

    for i, plan in enumerate(billing.get_plans()):
        try:
            label = f"{plan['name']}（{plan['credits']}枚・{billing.price_label(plan['price_id'])}）"
        except billing.BillingError:
            label = f"{plan['name']}（{plan['credits']}枚）"

        if st.button(label, key=f"plan_{i}", width="stretch"):
            try:
                session_id, url = billing.create_checkout(user_id, plan)
                db.add_pending_purchase(session_id, user_id, plan["credits"])
                st.session_state["checkout_url"] = url
            except (billing.BillingError, db.DatabaseError) as exc:
                st.error(f"購入手続きを開始できませんでした: {exc}")

    if st.session_state.get("checkout_url"):
        st.link_button(
            "💳 決済ページを開く",
            st.session_state["checkout_url"],
            type="primary",
            width="stretch",
        )
        st.caption("お支払い後、下のボタンでチケットを反映できます。")

    if st.button("お支払い済みのチケットを反映", width="stretch"):
        try:
            added = sync_pending_purchases(user_id)
        except (billing.BillingError, db.DatabaseError) as exc:
            st.error(f"確認できませんでした: {exc}")
        else:
            st.session_state.pop("checkout_url", None)
            st.session_state["flash"] = (
                "チケットを追加しました。" if added else "新しいお支払いは見つかりませんでした。"
            )
            st.rerun()


def admin_panel():
    st.subheader("会員一覧")
    try:
        members = db.list_users()
    except db.DatabaseError as exc:
        st.error(f"会員一覧を取得できませんでした: {exc}")
        return

    if not members:
        st.info("まだ会員はいません。")
        return

    st.dataframe(
        [
            {
                "ID": m["user_id"],
                "残りチケット": m["credits"],
                "登録日時": m["created_at"][:16].replace("T", " "),
            }
            for m in members
        ],
        width="stretch",
        hide_index=True,
    )

    st.subheader("チケットを付与")
    with st.form("grant"):
        target = st.selectbox("会員", [m["user_id"] for m in members])
        amount = st.number_input("枚数", min_value=1, max_value=1000, value=10)
        if st.form_submit_button("付与する", type="primary"):
            try:
                total = db.add_credits(target, int(amount))
            except db.DatabaseError as exc:
                st.error(f"付与できませんでした: {exc}")
            else:
                st.session_state["flash"] = f"{target} に{int(amount)}枚付与しました（残り{total}枚）。"
                st.rerun()


# ---- UI ----

missing = missing_settings()
if missing:
    st.error(
        "管理者設定が未完了です。Streamlit Secrets に次の項目を設定してください: "
        + ", ".join(missing)
    )
    st.stop()

handle_checkout_return()

if "user" not in st.session_state:
    auth_screen()

user = st.session_state["user"]
is_admin = st.session_state.get("role") == "admin"

if is_admin and user not in get_admins():
    st.session_state.clear()
    st.rerun()

credits = None
if not is_admin:
    try:
        member = db.get_user(user)
    except db.DatabaseError as exc:
        st.error(f"会員情報を取得できませんでした: {exc}")
        st.stop()
    if not member:
        st.session_state.clear()
        st.rerun()
    credits = member["credits"]

api_key = get_api_key()

with st.sidebar:
    if is_admin:
        st.write(f"👤 {user}（管理者）でログイン中")
    else:
        st.write(f"👤 {user} でログイン中")
        credit_slot = st.empty()
        credit_slot.metric("残りチケット", f"{credits}枚")
    if st.button("ログアウト", width="stretch"):
        st.session_state.clear()
        st.rerun()

    if not is_admin:
        st.divider()
        purchase_panel(user)

    st.divider()
    st.header("仕上がり設定")

    style = st.text_area(
        "写真の雰囲気",
        "明るく親しみやすい施設メニュー風。清潔感のある自然光、落ち着いた背景。",
        height=110,
    )

    quality = st.selectbox(
        "仕上がり品質",
        ["medium", "high"],
        index=1,
        help="high はより高品質ですが、medium よりAPI利用量が増える場合があります。",
    )

st.title("🍽️ Menu Photo Pro")
st.markdown("### 料理写真を、そのまま活かしてプロ品質のメニュー写真へ")
st.caption("料理・食材・皿・量を変えず、写真の見栄えだけを整えます。")
show_flash()

if is_admin:
    photo_tab, admin_tab = st.tabs(["写真加工", "会員管理"])
    with admin_tab:
        admin_panel()
else:
    photo_tab = st.container()

with photo_tab:
    uploads = st.file_uploader(
        "ここに料理写真をドロップ",
        type=["png", "jpg", "jpeg", "webp"],
        accept_multiple_files=True,
    )

    if not is_admin and credits == 0:
        st.info("チケットがありません。左のメニューからチケットを購入してください。")

    if uploads:
        st.write(f"**{len(uploads)}枚**の写真を選択中")
        if not is_admin and 0 < credits < len(uploads):
            st.warning(
                f"チケットが足りません（残り{credits}枚）。先頭の{credits}枚だけ加工します。"
            )

        preview_cols = st.columns(min(4, len(uploads)))
        for i, uploaded in enumerate(uploads):
            with preview_cols[i % len(preview_cols)]:
                st.image(
                    uploaded,
                    caption=uploaded.name,
                    width="stretch",
                )

        if st.button(
            "✨ プロ品質に仕上げる",
            type="primary",
            width="stretch",
            disabled=not is_admin and credits == 0,
        ):
            results = []
            progress = st.progress(0)
            status = st.empty()

            for i, uploaded in enumerate(uploads):
                if not is_admin:
                    try:
                        remaining = db.use_credit(user)
                    except db.DatabaseError as exc:
                        st.error(f"チケットを確認できませんでした: {exc}")
                        break
                    if remaining is None:
                        st.error("チケットが足りないため、残りの写真は加工しませんでした。")
                        break
                    credit_slot.metric("残りチケット", f"{remaining}枚")

                status.write(f"{i + 1}/{len(uploads)} を処理中…")

                try:
                    output = edit_image(
                        api_key=api_key,
                        image_bytes=uploaded.getvalue(),
                        filename=uploaded.name,
                        style=style,
                        quality=quality,
                    )

                    output_name = (
                        f"{i + 1:02d}_{Path(uploaded.name).stem}_menu.png"
                    )
                    results.append((output_name, output))

                except Exception as exc:
                    st.error(f"{uploaded.name}: {exc}")
                    if not is_admin:
                        try:
                            remaining = db.add_credits(user, 1)
                            credit_slot.metric("残りチケット", f"{remaining}枚")
                            st.caption("この写真のチケットは返却しました。")
                        except db.DatabaseError:
                            st.caption("チケットの返却に失敗しました。管理者にお問い合わせください。")

                progress.progress((i + 1) / len(uploads))

            status.empty()

            if results:
                st.success(f"{len(results)}枚の処理が完了しました。")

                result_cols = st.columns(min(3, len(results)))

                for i, (name, data) in enumerate(results):
                    with result_cols[i % len(result_cols)]:
                        st.image(
                            data,
                            caption=name,
                            width="stretch",
                        )

                        st.download_button(
                            "画像を保存",
                            data=data,
                            file_name=name,
                            mime="image/png",
                            key=f"download_{i}",
                            width="stretch",
                            on_click="ignore",
                        )

                if len(results) > 1:
                    zip_buffer = io.BytesIO()

                    with zipfile.ZipFile(
                        zip_buffer,
                        "w",
                        zipfile.ZIP_DEFLATED,
                    ) as archive:
                        for name, data in results:
                            archive.writestr(name, data)

                    st.download_button(
                        "📦 全画像をZIPで保存",
                        data=zip_buffer.getvalue(),
                        file_name="menu-photo-pro.zip",
                        mime="application/zip",
                        width="stretch",
                        on_click="ignore",
                    )
