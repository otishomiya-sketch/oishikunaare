import base64
import html
import io
import re
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from urllib.parse import urlencode

import requests
import streamlit as st
import streamlit.components.v1 as components
from PIL import Image, ImageOps, UnidentifiedImageError

try:
    # iPhone photos may arrive as HEIC.
    from pillow_heif import register_heif_opener

    register_heif_opener()
except ImportError:
    pass

import billing
import demo_quota
from before_after_video import make_image_video, make_video

st.set_page_config(
    page_title="Menu Photo Pro",
    page_icon="🍽️",
    layout="wide",
)

# How many photos are sent to OpenAI at the same time.
MAX_PARALLEL = 4
MAX_RETRIES = 3

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


def normalize_image(image_bytes, max_edge=2048):
    """Convert any accepted upload into a clean RGB JPEG.

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

            # The model does not need more detail than this, and smaller
            # uploads make each request noticeably faster.
            if max(image.size) > max_edge:
                scale = max_edge / max(image.size)
                new_size = (
                    max(1, round(image.width * scale)),
                    max(1, round(image.height * scale)),
                )
                image = image.resize(new_size, Image.Resampling.LANCZOS)

            output = io.BytesIO()
            # High-quality JPEG is far quicker to encode and upload than PNG.
            image.save(output, format="JPEG", quality=95)
            return output.getvalue()

    except (UnidentifiedImageError, OSError, ValueError) as exc:
        raise RuntimeError(
            "画像を読み込めませんでした。JPG・PNG・WebP・HEIC の写真を選んでください。"
        ) from exc


def edit_image(api_key, image_bytes, filename, style, quality="high"):
    normalized_bytes = normalize_image(image_bytes)

    for attempt in range(MAX_RETRIES):
        response = requests.post(
            "https://api.openai.com/v1/images/edits",
            headers={
                "Authorization": f"Bearer {api_key}",
            },
            data={
                # Flare is the speed-focused GPT Image 2.5 model.
                "model": "gpt-image-2.5-flare",
                "prompt": PROMPT + "\n\nSTYLE DIRECTION:\n" + style,
                "quality": quality,
                # JPEG output is faster than PNG according to OpenAI.
                "output_format": "jpeg",
                "output_compression": 95,
            },
            files={
                "image[]": ("input.jpg", normalized_bytes, "image/jpeg"),
            },
            timeout=300,
        )

        # Rate limits are more likely when photos are sent in parallel.
        retryable = response.status_code == 429 or response.status_code >= 500
        if not retryable or attempt == MAX_RETRIES - 1:
            break
        time.sleep(5 * (attempt + 1))

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


# ---- UI ----

CSS = """
<style>
@import url('https://fonts.googleapis.com/css2?family=Dela+Gothic+One&family=Zen+Kaku+Gothic+New:wght@400;500;700;900&display=swap');

/* Set the font on the app root only, so Streamlit's icon font is left alone. */
.stApp, .stApp button, .stApp input, .stApp textarea {
    font-family: "Zen Kaku Gothic New", "Hiragino Sans", "Yu Gothic", sans-serif;
}
header[data-testid="stHeader"] { background: transparent; }
.block-container { max-width: 760px; padding-top: 2.5rem; padding-bottom: 7rem; }
@media (max-width: 640px) {
    .block-container { padding-top: 1.25rem; padding-left: 16px; padding-right: 16px; }
}

.mpp-hero { display: flex; flex-direction: column; gap: 10px; padding-bottom: 18px; border-bottom: 2px solid #2A211C; margin-bottom: 8px; }
.mpp-eyebrow { font-size: 13px; font-weight: 900; letter-spacing: 0.16em; color: #6A5D53; }
.stMarkdown .mpp-title { font-family: "Dela Gothic One", sans-serif; font-weight: 400; font-size: 44px; line-height: 1.2; margin: 0; padding: 0; color: #2A211C; }
.mpp-title em { font-style: normal; color: #B7412A; }
.mpp-lead { font-size: 16px; color: #4A3F37; margin: 0; }
@media (max-width: 640px) {
    .mpp-hero { gap: 6px; padding-bottom: 12px; }
    .stMarkdown .mpp-title { font-size: 28px; }
    .mpp-lead { font-size: 15px; }
}

/* Selected photos as a compact 3-up grid instead of one full-width image per row. */
.mpp-thumbs { display: grid; grid-template-columns: repeat(auto-fill, minmax(96px, 1fr)); gap: 8px; margin: 4px 0 8px; }
.mpp-thumbs img { width: 100%; aspect-ratio: 1; object-fit: cover; border-radius: 10px; display: block; }
@media (max-width: 640px) { .mpp-thumbs { grid-template-columns: repeat(3, minmax(0, 1fr)); } }

/* Uploader: one big tap target with Japanese copy. */
div[data-testid="stFileUploaderDropzoneInstructions"] span,
div[data-testid="stFileUploaderDropzoneInstructions"] small { display: none; }
div[data-testid="stFileUploaderDropzoneInstructions"] > div::before {
    content: "タップして写真を選ぶ"; display: block; font-weight: 900; font-size: 17px; color: #2A211C;
}
div[data-testid="stFileUploaderDropzoneInstructions"] > div::after {
    content: "複数枚まとめて選べます（JPG・PNG・WebP・HEIC）"; display: block; font-size: 13px; color: #6A5D53;
}
/* Replace the button's own icon and "Upload"/"Browse files" text (which keeps its
   width even when hidden) with a centred photo icon and Japanese label. */
[data-testid="stFileUploaderDropzone"] button {
    display: inline-flex; align-items: center; justify-content: center; gap: 8px;
    min-height: 48px; border-radius: 999px; padding: 0 24px;
    background: #2A211C; border-color: #2A211C; color: #FFFFFF;
    font-size: 0 !important;  /* older Streamlit puts "Browse files" as bare text */
}
[data-testid="stFileUploaderDropzone"] button > * { display: none !important; }
[data-testid="stFileUploaderDropzone"] button::before {
    content: ""; width: 20px; height: 20px; flex-shrink: 0; background: currentColor;
    -webkit-mask: url("data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 24 24' fill='none' stroke='black' stroke-width='2' stroke-linecap='round' stroke-linejoin='round'%3E%3Crect x='3' y='5' width='18' height='14' rx='2'/%3E%3Ccircle cx='9' cy='10' r='1.6'/%3E%3Cpath d='M21 16l-5-5-8 8'/%3E%3C/svg%3E") center / contain no-repeat;
            mask: url("data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 24 24' fill='none' stroke='black' stroke-width='2' stroke-linecap='round' stroke-linejoin='round'%3E%3Crect x='3' y='5' width='18' height='14' rx='2'/%3E%3Ccircle cx='9' cy='10' r='1.6'/%3E%3Cpath d='M21 16l-5-5-8 8'/%3E%3C/svg%3E") center / contain no-repeat;
}
[data-testid="stFileUploaderDropzone"] button::after { content: "写真を選ぶ"; font-size: 16px; font-weight: 700; line-height: 1; color: #FFFFFF; }
@media (max-width: 640px) { [data-testid="stFileUploaderDropzone"] button { width: 100%; } }

/* Keep the main action within thumb reach while scrolling. */
/* The device-memory helper renders nothing; keep it out of the layout. */
.st-key-device_memory { position: absolute; width: 0; height: 0; overflow: hidden; }

.st-key-run, .st-key-restart {
    position: sticky; bottom: 0; z-index: 10;
    padding: 10px 0 calc(10px + env(safe-area-inset-bottom, 0px));
    background: linear-gradient(rgba(251, 246, 236, 0), #FBF6EC 30%);
}
.mpp-note { font-size: 13px; color: #6A5D53; line-height: 1.6; }
.mpp-plan { display: flex; justify-content: space-between; align-items: center; gap: 12px; flex-wrap: wrap; }
.mpp-plan b { font-family: "Dela Gothic One", sans-serif; font-weight: 400; font-size: 20px; margin-right: 10px; }
.mpp-plan span { font-size: 15px; font-weight: 700; color: #4A3F37; }
.mpp-price { font-size: 18px; font-weight: 900; color: #B7412A; }
.mpp-price small { font-size: 12px; font-weight: 500; color: #6A5D53; margin-left: 4px; }
.mpp-quota { display: flex; flex-wrap: wrap; justify-content: space-between; align-items: center; gap: 4px 12px; background: #FFFFFF; border: 1.5px solid #2A211C; border-radius: 12px; padding: 10px 14px; margin: 4px 0; font-size: 14px; }
.mpp-quota > div { flex: 1 1 8em; min-width: 0; }
.mpp-quota b { font-size: 15px; text-align: right; margin-left: auto; }
.mpp-quota b small { display: block; font-size: 12px; font-weight: 500; color: #6A5D53; }
.mpp-quota b span { font-family: "Dela Gothic One", sans-serif; font-weight: 400; font-size: 20px; color: #B7412A; }
.mpp-done { background: #2A211C; color: #FBF6EC; border-radius: 14px; padding: 20px; display: flex; flex-direction: column; gap: 8px; }
.mpp-done strong { font-family: "Dela Gothic One", sans-serif; font-weight: 400; font-size: 20px; }
.mpp-done p { margin: 0; font-size: 15px; line-height: 1.7; color: #E9DFCF; }

@media (max-width: 640px) {
    .mpp-steps { gap: 6px; }
    .mpp-step { flex: 1 1 0; min-width: 0; justify-content: center; font-size: 12px; padding: 4px 8px 4px 4px; gap: 6px; }
    .mpp-step b { width: 22px; height: 22px; font-size: 11px; flex-shrink: 0; }
}

.mpp-steps { display: flex; gap: 8px; flex-wrap: wrap; margin: 6px 0 4px; }
.mpp-steps { flex-wrap: nowrap; }
.mpp-step { white-space: nowrap; display: flex; align-items: center; gap: 8px; padding: 6px 14px 6px 6px; border-radius: 999px; border: 1.5px solid #D9CCB6; color: #6A5D53; font-size: 14px; font-weight: 700; background: #FFFFFF; }
.mpp-step b { width: 26px; height: 26px; border-radius: 50%; display: flex; align-items: center; justify-content: center; background: #F3E7CF; color: #6A5D53; font-family: "Dela Gothic One", sans-serif; font-weight: 400; font-size: 13px; }
.mpp-step.on { border-color: #2A211C; color: #2A211C; }
.mpp-step.on b { background: #B7412A; color: #FFFFFF; }
.mpp-step.done b { background: #2A211C; color: #FFFFFF; }

.mpp-section { font-family: "Dela Gothic One", sans-serif; font-weight: 400; font-size: 24px; margin: 18px 0 2px; color: #2A211C; }
.mpp-label { font-size: 12px; font-weight: 900; letter-spacing: 0.14em; color: #6A5D53; margin-bottom: 4px; }
.mpp-label.after { color: #B7412A; }
.mpp-name { font-weight: 700; font-size: 15px; }

[data-testid="stFileUploaderDropzone"] { background: #FFFFFF; border: 2px dashed #CDBBA0; border-radius: 14px; padding: 22px 18px; display: flex; flex-direction: column; align-items: stretch; gap: 14px; }
/* Explanation first, then the button, whichever order Streamlit renders them in. */
[data-testid="stFileUploaderDropzoneInstructions"] { order: -1; margin: 0; }
[data-testid="stFileUploaderDropzone"] > span { display: flex; justify-content: center; }
.stButton > button, .stDownloadButton > button { border-radius: 999px; font-weight: 700; min-height: 44px; }
.stButton > button[kind="primary"] { font-size: 17px; min-height: 52px; letter-spacing: 0.04em; }
</style>
"""

VIEW_SLIDER = "スライダーで比較"
# label -> (style, description)
VIDEO_STYLES = {
    "仕上がりだけ（画面いっぱい）": ("full", "縦の画面いっぱいに、料理の上をゆっくり流れます"),
    "仕上がりだけ（全体を見せる）": ("panel", "お皿全体を見せたまま、ゆっくり寄っていきます"),
    "ビフォーアフター": ("before_after", "元の写真から仕上がりに切り替わります"),
}
VIEW_SIDE = "左右に並べる"


def thumbnail(image_bytes, edge=240):
    """Square-ish small JPEG for the selected-photos grid."""
    with Image.open(io.BytesIO(image_bytes)) as original:
        image = ImageOps.exif_transpose(original).convert("RGB")
        image.thumbnail((edge, edge), Image.Resampling.LANCZOS)
        output = io.BytesIO()
        image.save(output, format="JPEG", quality=80)
        return output.getvalue()


def preview_jpeg(image_bytes, max_edge=1400):
    """Small JPEG for on-screen comparison (downloads keep full size)."""
    with Image.open(io.BytesIO(image_bytes)) as original:
        image = ImageOps.exif_transpose(original).convert("RGB")
        image.thumbnail((max_edge, max_edge), Image.Resampling.LANCZOS)
        output = io.BytesIO()
        image.save(output, format="JPEG", quality=85)
        return output.getvalue(), image.width, image.height


# Drag-to-compare view, served from compare_component/ (plain HTML, no build step).
_before_after = components.declare_component(
    "before_after",
    path=str(Path(__file__).parent / "compare_component"),
)


# Invisible helper that remembers the store's demo code in the browser.
_device_memory = components.declare_component(
    "device_memory",
    path=str(Path(__file__).parent / "device_memory"),
)


# Save button that puts photos in the phone's photo library (share sheet on
# iPhone, download on Android).
_save_photos = components.declare_component(
    "save_photos",
    path=str(Path(__file__).parent / "save_photos"),
)


def save_button(photos, label, key, secondary=False, mime="image/jpeg"):
    _save_photos(
        files=[{"name": name, "data": base64.b64encode(data).decode(), "type": mime} for name, data in photos],
        label=label,
        secondary=secondary,
        key=key,
        default=None,
    )


def compare_slider(before, after, width, height, key):
    _before_after(
        before="data:image/jpeg;base64," + base64.b64encode(before).decode(),
        after="data:image/jpeg;base64," + base64.b64encode(after).decode(),
        width=width,
        height=height,
        key=key,
        default=None,
    )


def start_over():
    """Clear the finished photos and empty the uploader."""
    st.session_state.pop("flash", None)
    st.session_state.pop("results", None)
    st.session_state.pop("errors", None)
    st.session_state["batch"] = st.session_state.get("batch", 0) + 1


def step_bar(current):
    steps = ["写真を選ぶ", "仕上げる", "保存する"]
    items = []
    for n, label in enumerate(steps, start=1):
        state = "on" if n == current else ("done" if n < current else "")
        items.append(f'<div class="mpp-step {state}"><b>{n}</b>{label}</div>')
    st.markdown(f'<div class="mpp-steps">{"".join(items)}</div>', unsafe_allow_html=True)


st.markdown(CSS, unsafe_allow_html=True)

api_key = get_api_key()

if not api_key:
    st.error(
        "管理者設定が未完了です。OPENAI_API_KEY を Streamlit Secrets に設定してください。"
    )
    st.stop()

st.markdown(
    """
<div class="mpp-hero">
  <div class="mpp-eyebrow">MENU PHOTO PRO</div>
  <h1 class="mpp-title">スマホの料理写真を、<em>メニュー写真</em>に。</h1>
  <p class="mpp-lead">料理・食材・皿・量は変えずに、光・色・背景だけを整えます。</p>
</div>
""",
    unsafe_allow_html=True,
)

# ---- Demo access ----
# Stores open the shared LINE link, enter their name once, and get their own
# demo allowance. Their code is kept in the URL and in this browser, so
# reopening the LINE link continues where they left off.

APP_URL = "https://7ayyryczawpyuggappqsqqd.streamlit.app"
CONTACT = "お問い合わせ：オーティス"


def opened_in_line():
    """LINE's in-app browser (User-Agent contains "Line/<version>")."""
    try:
        user_agent = st.context.headers.get("User-Agent", "")
    except Exception:
        return False
    return bool(re.search(r"\bLine/\d", user_agent))


# LINE's in-app browser often cannot pick photos or save files (especially on
# Android). `openExternalBrowser=1` is LINE's own switch to open a link in the
# phone's regular browser instead.
if opened_in_line():
    params = {k: v for k, v in st.query_params.items() if k != "openExternalBrowser"}
    params["openExternalBrowser"] = "1"
    st.warning(
        "LINEの中で開いています。LINEの中では、写真の選択や保存がうまくいかないことがあります。"
        "下のボタンから、Chromeなどのブラウザで開き直してください。"
    )
    st.link_button(
        "ブラウザで開き直す",
        f"{APP_URL}/?{urlencode(params)}",
        type="primary",
        width="stretch",
    )

remembered = _device_memory(save=st.session_state.get("save_code"), key="device_memory", default=None)
code = (st.query_params.get("code") or "").strip()

if not code:
    if remembered is None:
        # The browser has not answered yet; this lasts a moment on first load.
        st.caption("読み込み中です。表示されない場合は、ページを再読み込みしてください。")
        st.stop()
    code = remembered


def show_flash():
    # Kept until the next photo run or restart: helper components rerun the
    # page right after load, which would otherwise wipe the message at once.
    if "flash" in st.session_state:
        st.success(st.session_state["flash"])


def finished_screen(title, body):
    st.markdown(
        f'<div class="mpp-done"><strong>{title}</strong><p>{body}</p></div>',
        unsafe_allow_html=True,
    )
    st.stop()


def start_screen(message=None):
    try:
        demo_closed = demo_quota.total_remaining() == 0
    except demo_quota.QuotaError as exc:
        st.error(f"{exc} 時間をおいて開き直してください。")
        st.stop()
    if demo_closed and not billing.enabled():
        finished_screen(
            "デモの受付を終了しました",
            "たくさんのご利用ありがとうございました。本導入のご相談は、オーティスまでお気軽にご連絡ください。",
        )
    if demo_closed:
        st.info("無料デモの受付は終了しました。お店の名前を登録すると、有料プランでご利用いただけます。")

    if message:
        st.info(message)

    store_limit = demo_quota.settings()["store_limit"]
    with st.form("register"):
        st.markdown(
            f'<div class="mpp-section">無料デモを始める</div>'
            f'<div class="mpp-note">お店の名前を入れるだけで、すぐに使えます。1店あたり{store_limit}枚まで無料でお試しいただけます。</div>',
            unsafe_allow_html=True,
        )
        name = st.text_input("お店の名前", max_chars=40, placeholder="例：カレーの店 たなか")
        if st.form_submit_button("デモを始める", type="primary", width="stretch"):
            if not name.strip():
                st.error("お店の名前を入れてください。")
            else:
                try:
                    new_code = demo_quota.register(name.strip(), APP_URL)
                except demo_quota.QuotaError as exc:
                    st.error(f"{exc} 時間をおいてもう一度お試しください。")
                    st.stop()
                st.session_state["save_code"] = new_code
                st.query_params["code"] = new_code
                st.rerun()

    with st.expander("デモコードをお持ちの方"):
        with st.form("code_form"):
            entered = st.text_input("デモコード", placeholder="例：demo-abc123")
            if st.form_submit_button("このコードで始める", width="stretch") and entered.strip():
                st.session_state["save_code"] = entered.strip()
                st.query_params["code"] = entered.strip()
                st.rerun()

    st.caption(CONTACT)
    st.stop()


if not code:
    start_screen()

try:
    account = demo_quota.get_account(code)
except demo_quota.QuotaError as exc:
    st.error(f"{exc} 時間をおいて開き直してください。")
    st.stop()

if not account:
    start_screen("このデモコードは見つかりませんでした。お店の名前を入れて、新しく始めてください。")

# Keep this store's code in the URL and the browser from now on.
if remembered != code:
    st.session_state["save_code"] = code
if st.query_params.get("code") != code:
    st.query_params["code"] = code

# ---- Paid plans (Stripe) ----


def plan_panel(current=None):
    """The three monthly plans with a sign-up button each (or a manage button if subscribed)."""
    st.markdown('<div class="mpp-section">料金プラン</div>', unsafe_allow_html=True)
    st.markdown(
        '<div class="mpp-note">毎月1日にプランの枚数が追加され、使い切れなかった分は翌月に繰り越されます。'
        "いつでもプランの変更・解約ができます（解約すると繰越分はなくなります）。</div>",
        unsafe_allow_html=True,
    )
    for p in billing.PLANS:
        with st.container(border=True):
            st.markdown(
                f'<div class="mpp-plan"><div><b>{p["name"]}</b><span>月{p["quota"]}枚まで</span></div>'
                f'<div class="mpp-price">月額{p["price"]:,}円<small>（税込{billing.price_with_tax(p):,}円）</small></div></div>',
                unsafe_allow_html=True,
            )
            if current:
                if current["key"] == p["key"]:
                    st.markdown('<div class="mpp-note">ご利用中のプランです</div>', unsafe_allow_html=True)
            elif st.button("このプランで申し込む", key=f"plan_{p['key']}", width="stretch", type="primary"):
                try:
                    _, url = billing.create_checkout(code, p, APP_URL)
                    st.session_state["checkout"] = (p["name"], url)
                except billing.BillingError as exc:
                    st.error(f"{exc} 時間をおいてもう一度お試しください。")

    if st.session_state.get("checkout") and not current:
        name, url = st.session_state["checkout"]
        st.link_button(f"{name}プランのお支払い画面へ進む（Stripe）", url, type="primary", width="stretch")
        st.caption("カード情報はStripeの安全な画面で入力します。お支払いが終わると、自動でこの画面に戻ります。")

    if current:
        manage_button()
    else:
        with st.expander("お支払い済みなのに反映されない方"):
            if st.button("契約を確認する", key="find_subscription", width="stretch"):
                try:
                    found = billing.find_subscription(code)
                except billing.BillingError as exc:
                    found = None
                    st.error(str(exc))
                if found:
                    sub_id, customer_id = found
                    info = billing.subscription_plan(sub_id)
                    demo_quota.link_subscription(code, sub_id, customer_id, info["plan"]["name"] if info["plan"] else "")
                    st.session_state["flash"] = "ご契約を確認しました。有料プランをご利用いただけます。"
                    st.rerun()
                else:
                    st.info("このお店のご契約が見つかりませんでした。オーティスまでお問い合わせください。")

    legal_url = str(st.secrets.get("TERMS_URL", "")).strip()
    if legal_url:
        st.markdown(f'<div class="mpp-note"><a href="{html.escape(legal_url)}" target="_blank">利用規約・特定商取引法に基づく表記</a></div>', unsafe_allow_html=True)


def manage_button():
    if st.button("プランの変更・解約・カードの変更", key="portal", width="stretch"):
        try:
            st.session_state["portal_url"] = billing.portal_url(account["customer_id"], code, APP_URL)
        except billing.BillingError as exc:
            st.error(f"{exc} 時間をおいてもう一度お試しください。")
    if st.session_state.get("portal_url"):
        st.link_button("手続きの画面へ進む（Stripe）", st.session_state["portal_url"], width="stretch")


plan = None
if billing.enabled():
    # Coming back from Stripe Checkout with ?session_id=...
    session_id = st.query_params.get("session_id")
    if session_id:
        try:
            done = billing.completed_checkout(session_id, code)
            if done:
                sub_id, customer_id = done
                info = billing.subscription_plan(sub_id)
                demo_quota.link_subscription(code, sub_id, customer_id, info["plan"]["name"] if info["plan"] else "")
                st.session_state["flash"] = "お申し込みありがとうございます。有料プランが始まりました。"
                st.session_state.pop("checkout", None)
                account = demo_quota.get_account(code)
        except (billing.BillingError, demo_quota.QuotaError) as exc:
            st.error(f"お申し込みの確認に失敗しました。{exc}")
        del st.query_params["session_id"]

    # Coming back from the Customer Portal: plan may have changed.
    if st.query_params.get("portal"):
        billing.subscription_plan.clear()
        st.session_state.pop("portal_url", None)
        del st.query_params["portal"]

    if account["subscription_id"]:
        try:
            info = billing.subscription_plan(account["subscription_id"])
            plan = info["plan"]
            label = plan["name"] if plan else f"停止中（{info['status']}）"
            if label != account["plan_label"]:
                demo_quota.set_plan_label(code, label)
        except billing.BillingError:
            # Stripe unreachable: trust the last known plan rather than locking a paying store out.
            plan = next((p for p in billing.PLANS if p["name"] == account["plan_label"]), None)

if plan:
    balance = demo_quota.paid_balance(account, plan["quota"])
    remaining = balance["remaining"]
    detail = f'今月分{plan["quota"]}＋繰越{balance["carry"]}' if balance["carry"] else f'今月分{plan["quota"]}'
    quota_text = f'{plan["name"]}プラン　今月の残り <span>{remaining}</span>枚<small>（{detail}）</small>'
else:
    remaining = account["remaining"]
    quota_text = f'デモ残り <span>{remaining}</span> / {account["limit"]}枚'

store_name = html.escape(account["store"] or "デモ")
st.markdown(
    f'<div class="mpp-quota"><div>{store_name} さま</div><b>{quota_text}</b></div>',
    unsafe_allow_html=True,
)
show_flash()

if billing.enabled() and remaining > 0:
    with st.expander("プランの変更・解約" if plan else f"有料プランを見る（月額{billing.PLANS[0]['price']:,}円〜）"):
        plan_panel(current=plan)

results = st.session_state.get("results", [])

for message in st.session_state.get("errors", []):
    st.error(message)

if remaining == 0 and not results:
    if plan:
        st.markdown(
            '<div class="mpp-done"><strong>今月の枚数を使い切りました</strong>'
            f'<p>{plan["name"]}プラン（月{plan["quota"]}枚）の今月分と繰越分をご利用いただきました。'
            f'来月1日に{plan["quota"]}枚が追加されます。上のプランに変更すると、今月もすぐにご利用いただけます。</p></div>',
            unsafe_allow_html=True,
        )
        plan_panel(current=plan)
    elif billing.enabled():
        title = "無料デモの受付を終了しました" if account["total_exhausted"] else "デモ枠を使い切りました"
        st.markdown(
            f'<div class="mpp-done"><strong>{title}</strong>'
            "<p>ご利用ありがとうございました。有料プランにお申し込みいただくと、続けてお使いいただけます。</p></div>",
            unsafe_allow_html=True,
        )
        plan_panel()
    else:
        st.markdown(
            '<div class="mpp-done"><strong>デモ枠を使い切りました</strong>'
            "<p>ご利用ありがとうございました。本導入のご相談は、オーティスまでお気軽にご連絡ください。</p></div>",
            unsafe_allow_html=True,
        )
    st.caption(CONTACT)
    st.stop()

# A new key per batch empties the uploader when starting over.
upload_key = f"uploads_{st.session_state.get('batch', 0)}"

step_bar(3 if results else (2 if st.session_state.get(upload_key) else 1))

# Once photos are finished, show only the results so nothing is re-run by accident.
# No `type` filter: an extension list stops Android from opening the photo
# gallery (device_memory/index.html sets accept="image/*" instead), and gallery
# files do not always have an extension. Files are checked by opening them.
uploads = None if results else st.file_uploader(
    "料理写真",
    type=None,
    accept_multiple_files=True,
    label_visibility="collapsed",
    key=upload_key,
)

if uploads:
    previews = []
    unreadable = []
    for u in uploads:
        try:
            previews.append((u, thumbnail(u.getvalue())))
        except Exception:
            unreadable.append(u.name)
    if unreadable:
        st.warning(
            "写真として読み込めないファイルがありました（" + "、".join(unreadable) + "）。"
            "JPG・PNG・WebP・HEICの写真を選んでください。"
        )
    uploads = [u for u, _ in previews]

if uploads:
    st.markdown(
        f'<div class="mpp-section">選んだ写真　{len(uploads)}枚</div>',
        unsafe_allow_html=True,
    )

    thumbs = "".join(
        f'<img src="data:image/jpeg;base64,{base64.b64encode(thumb).decode()}" alt="{html.escape(u.name)}">'
        for u, thumb in previews
    )
    st.markdown(f'<div class="mpp-thumbs">{thumbs}</div>', unsafe_allow_html=True)

    count = min(len(uploads), remaining)
    if len(uploads) > remaining:
        st.warning(f"デモの残りは{remaining}枚です。選んだ写真のうち、先頭の{remaining}枚を仕上げます。")

    with st.expander("仕上がりの設定（そのままでもOK）"):
        style = st.text_area(
            "写真の雰囲気",
            "明るく親しみやすい施設メニュー風。清潔感のある自然光、落ち着いた背景。",
            height=100,
        )
        quality = st.segmented_control(
            "仕上がり品質",
            ["medium", "high", "xhigh", "max"],
            default="high",
            help="medium → max の順に高品質になりますが、時間とAPI利用料金も増えます。",
        ) or "high"

    if st.button(
        f"プロ品質に仕上げる（{count}枚）",
        type="primary",
        width="stretch",
        key="run",
    ):
        # Count the photos against the store's limit before spending anything.
        try:
            granted = demo_quota.reserve(code, count, monthly_quota=plan["quota"] if plan else None)
        except demo_quota.QuotaError as exc:
            st.error(f"{exc} 時間をおいてもう一度お試しください。")
            st.stop()
        if not granted:
            st.rerun()
        uploads = uploads[:granted]

        st.session_state.pop("flash", None)
        st.session_state["results"] = []
        errors = []
        processed = [None] * len(uploads)
        progress = st.progress(0)
        status = st.empty()
        status.info(
            f"0/{len(uploads)} 枚完了　仕上がるまで、この画面を開いたままお待ちください。"
            "途中でほかのアプリに切り替えたり画面を消したりすると、やり直しになることがあります。"
        )

        with ThreadPoolExecutor(
            max_workers=min(MAX_PARALLEL, len(uploads))
        ) as pool:
            futures = {
                pool.submit(
                    edit_image,
                    api_key=api_key,
                    image_bytes=uploaded.getvalue(),
                    filename=uploaded.name,
                    style=style,
                    quality=quality,
                ): i
                for i, uploaded in enumerate(uploads)
            }

            for done, future in enumerate(as_completed(futures), start=1):
                i = futures[future]
                uploaded = uploads[i]

                try:
                    output = future.result()
                    before, width, height = preview_jpeg(uploaded.getvalue())
                    after, _, _ = preview_jpeg(output)
                    processed[i] = {
                        "name": f"{i + 1:02d}_{Path(uploaded.name).stem}_menu.jpg",
                        "source": uploaded.name,
                        "before": before,
                        "before_src": preview_jpeg(uploaded.getvalue(), max_edge=2000)[0],
                        "after": after,
                        "width": width,
                        "height": height,
                        "full": output,
                    }

                except Exception as exc:
                    errors.append(
                        f"{uploaded.name}：仕上げに失敗しました。この写真はデモの枚数に数えていません。"
                        f"（詳細：{exc}）"
                    )

                progress.progress(done / len(uploads))
                status.info(
                    f"{done}/{len(uploads)} 枚完了　この画面を開いたままお待ちください。"
                )

        progress.empty()
        status.empty()
        st.session_state["results"] = [r for r in processed if r]
        st.session_state["errors"] = errors

        # Failed photos do not count toward the demo limit.
        try:
            demo_quota.release(
                code,
                len(uploads) - len(st.session_state["results"]),
                monthly_quota=plan["quota"] if plan else None,
            )
        except demo_quota.QuotaError:
            pass
        st.rerun()

if results:
    st.button("← 最初に戻る", key="restart_top", on_click=start_over)

    head_col, view_col = st.columns([3, 2], vertical_alignment="bottom")
    with head_col:
        st.markdown(
            f'<div class="mpp-section">仕上がり　{len(results)}枚</div>',
            unsafe_allow_html=True,
        )
    with view_col:
        view = st.segmented_control(
            "表示",
            [VIEW_SLIDER, VIEW_SIDE],
            default=VIEW_SLIDER,
            label_visibility="collapsed",
            key="view",
        ) or VIEW_SLIDER

    if len(results) > 1:
        save_button(
            [(r["name"], r["full"]) for r in results],
            f"全{len(results)}枚を写真に保存",
            key="save_all",
            secondary=True,
        )

    for i, r in enumerate(results):
        with st.container(border=True):
            st.markdown(f'<div class="mpp-name">{r["source"]}</div>', unsafe_allow_html=True)

            if view == VIEW_SLIDER:
                compare_slider(r["before"], r["after"], r["width"], r["height"], key=f"compare_{i}")
            else:
                left, right = st.columns(2)
                with left:
                    st.markdown('<div class="mpp-label">BEFORE　元の写真</div>', unsafe_allow_html=True)
                    st.image(r["before"], width="stretch")
                with right:
                    st.markdown('<div class="mpp-label after">AFTER　仕上がり</div>', unsafe_allow_html=True)
                    st.image(r["after"], width="stretch")

            save_button([(r["name"], r["full"])], "この写真を保存", key=f"save_{i}")

            with st.expander("SNS用の動画を作る（無料）"):
                st.markdown(
                    '<div class="mpp-note">縦長・約8秒の動画です。Instagramのリールやストーリーにそのまま使えます。'
                    "写真を動かして作るので料理は変わらず、デモの枚数にも数えません。</div>",
                    unsafe_allow_html=True,
                )
                video_style = st.radio(
                    "動画の種類",
                    list(VIDEO_STYLES),
                    key=f"video_style_{i}",
                    captions=[VIDEO_STYLES[k][1] for k in VIDEO_STYLES],
                )
                caption = st.text_input(
                    "動画に入れる文字（任意）",
                    max_chars=30,
                    placeholder="例：季節限定 きのこカレー",
                    key=f"caption_{i}",
                )
                credit = st.checkbox("「Menu Photo Pro で仕上げました」を入れる", value=True, key=f"credit_{i}")
                if st.button("動画を作る", key=f"make_video_{i}", width="stretch"):
                    with st.spinner("動画を作っています（10秒ほど）…"):
                        try:
                            if VIDEO_STYLES[video_style][0] == "before_after":
                                r["video"] = make_video(r["before_src"], r["full"], caption, credit)
                            else:
                                r["video"] = make_image_video(
                                    r["full"], caption, credit, style=VIDEO_STYLES[video_style][0]
                                )
                        except Exception as exc:
                            st.error(f"動画を作れませんでした。もう一度お試しください。（詳細：{exc}）")
                if r.get("video"):
                    st.video(r["video"], format="video/mp4")
                    save_button(
                        [(Path(r["name"]).stem + "_movie.mp4", r["video"])],
                        "動画を保存",
                        key=f"save_video_{i}",
                        mime="video/mp4",
                    )

            with st.expander("うまく保存できないときは"):
                st.markdown(
                    '<div class="mpp-note">下の画像を長押しして、'
                    "iPhoneは「\"写真\"に保存」、Androidは「画像をダウンロード」を選んでください。</div>",
                    unsafe_allow_html=True,
                )
                st.image(r["full"], width="stretch")

    st.button("最初に戻る（別の写真を仕上げる）", width="stretch", key="restart", on_click=start_over)
