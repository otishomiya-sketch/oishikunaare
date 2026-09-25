import base64
import io
import time
import zipfile
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

import requests
import streamlit as st
from PIL import Image, ImageOps, UnidentifiedImageError

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
            "画像を読み込めませんでした。JPG / JPEG / PNG / WebP の画像を選択してください。"
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

st.title("🍽️ Menu Photo Pro")
st.markdown("### 料理写真を、そのまま活かしてプロ品質のメニュー写真へ")
st.caption("料理・食材・皿・量を変えず、写真の見栄えだけを整えます。")

api_key = get_api_key()

if not api_key:
    st.error(
        "管理者設定が未完了です。OPENAI_API_KEY を Streamlit Secrets に設定してください。"
    )
    st.stop()

with st.sidebar:
    st.header("仕上がり設定")

    style = st.text_area(
        "写真の雰囲気",
        "明るく親しみやすい施設メニュー風。清潔感のある自然光、落ち着いた背景。",
        height=110,
    )

    quality = st.selectbox(
        "仕上がり品質",
        ["medium", "high", "xhigh", "max"],
        index=1,
        help="medium → max の順に高品質になりますが、時間とAPI利用料金も増えます。",
    )

    st.divider()
    st.caption("このサービスのAPIキーは利用者には表示されません。")

uploads = st.file_uploader(
    "ここに料理写真をドロップ",
    type=["png", "jpg", "jpeg", "webp"],
    accept_multiple_files=True,
)

if uploads:
    st.write(f"**{len(uploads)}枚**の写真を選択中")

    preview_cols = st.columns(min(4, len(uploads)))
    for i, uploaded in enumerate(uploads):
        with preview_cols[i % len(preview_cols)]:
            st.image(
                uploaded,
                caption=uploaded.name,
                use_container_width=True,
            )

    if st.button(
        "✨ プロ品質に仕上げる",
        type="primary",
        use_container_width=True,
    ):
        results = [None] * len(uploads)
        progress = st.progress(0)
        status = st.empty()
        status.write(f"0/{len(uploads)} 枚完了（最大{MAX_PARALLEL}枚ずつ同時に処理中…）")

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
                    output_name = (
                        f"{i + 1:02d}_{Path(uploaded.name).stem}_menu.jpg"
                    )
                    results[i] = (output_name, future.result())

                except Exception as exc:
                    st.error(f"{uploaded.name}: {exc}")

                progress.progress(done / len(uploads))
                status.write(f"{done}/{len(uploads)} 枚完了…")

        status.empty()
        results = [result for result in results if result]

        if results:
            st.success(f"{len(results)}枚の処理が完了しました。")

            result_cols = st.columns(min(3, len(results)))

            for i, (name, data) in enumerate(results):
                with result_cols[i % len(result_cols)]:
                    st.image(
                        data,
                        caption=name,
                        use_container_width=True,
                    )

                    st.download_button(
                        "画像を保存",
                        data=data,
                        file_name=name,
                        mime="image/jpeg",
                        key=f"download_{i}",
                        use_container_width=True,
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
                    use_container_width=True,
                    on_click="ignore",
                )
