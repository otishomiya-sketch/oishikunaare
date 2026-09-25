import base64
import io
import zipfile
from pathlib import Path

import requests
import streamlit as st

st.set_page_config(
    page_title="Menu Photo Pro",
    page_icon="🍽️",
    layout="wide",
)

PROMPT = """Transform the supplied food photo into a polished professional restaurant/menu photograph.

SOURCE-OF-TRUTH RULES:
- Preserve exactly the same dishes, ingredients, plates, bowls, trays, portion sizes, piece counts, and visible food components.
- Do NOT add, remove, replace, invent, or rearrange food.
- Do NOT add garnish, sauces, drinks, bread, soup, toppings, or side dishes that are not already present.
- Keep the identity of the food unchanged.

EDIT ONLY THE PRESENTATION:
- professional composition
- clean restaurant/menu background
- natural soft lighting
- accurate white balance
- appetizing but realistic color
- subtle depth of field
- clean table surface
- tasteful non-food props only when helpful
- realistic photographic texture
- no artificial steam unless the source clearly contains steam

The supplied image is the source of truth; do not recreate the meal from text.
"""

def get_api_key():
    try:
        return st.secrets["OPENAI_API_KEY"]
    except Exception:
        return None

def edit_image(api_key, image_bytes, filename, style, model="gpt-image-2"):
    ext = Path(filename).suffix.lower()
    mime = "image/png"
    if ext in [".jpg", ".jpeg"]:
        mime = "image/jpeg"
    elif ext == ".webp":
        mime = "image/webp"

    response = requests.post(
        "https://api.openai.com/v1/images/edits",
        headers={"Authorization": f"Bearer {api_key}"},
        data={
            "model": model,
            "prompt": PROMPT + "\n\nSTYLE DIRECTION:\n" + style,
            "output_format": "png",
        },
        files={"image[]": (filename, image_bytes, mime)},
        timeout=300,
    )
    if not response.ok:
        raise RuntimeError(f"Image API error {response.status_code}: {response.text[:800]}")
    data = response.json()["data"][0]
    if data.get("b64_json"):
        return base64.b64decode(data["b64_json"])
    if data.get("url"):
        r = requests.get(data["url"], timeout=120)
        r.raise_for_status()
        return r.content
    raise RuntimeError("画像データを取得できませんでした。")

st.title("🍽️ Menu Photo Pro")
st.markdown("### 料理写真を、そのまま活かしてプロ品質のメニュー写真へ")
st.caption("料理・食材・皿・量を変えず、写真の見栄えだけを整えます。")

api_key = get_api_key()
if not api_key:
    st.error("管理者設定が未完了です。OPENAI_API_KEY を Streamlit Secrets に設定してください。")
    st.stop()

with st.sidebar:
    st.header("仕上がり設定")
    style = st.text_area(
        "写真の雰囲気",
        "明るく親しみやすい施設メニュー風。清潔感のある自然光、落ち着いた背景。",
        height=110,
    )
    model = st.selectbox("画像モデル", ["gpt-image-2", "gpt-image-1.5"], index=0)
    st.divider()
    st.caption("このサービスのAPIキーは利用者には表示されません。")

uploads = st.file_uploader(
    "ここに料理写真をドロップ",
    type=["png", "jpg", "jpeg", "webp"],
    accept_multiple_files=True,
)

if uploads:
    st.write(f"**{len(uploads)}枚**の写真を選択中")
    cols = st.columns(min(4, len(uploads)))
    for i, f in enumerate(uploads):
        with cols[i % len(cols)]:
            st.image(f, caption=f.name, use_container_width=True)

    if st.button("✨ プロ品質に仕上げる", type="primary", use_container_width=True):
        results = []
        progress = st.progress(0)
        status = st.empty()

        for i, uploaded in enumerate(uploads):
            status.write(f"{i+1}/{len(uploads)} を処理中…")
            try:
                out = edit_image(api_key, uploaded.getvalue(), uploaded.name, style, model)
                name = f"{i+1:02d}_{Path(uploaded.name).stem}_menu.png"
                results.append((name, out))
            except Exception as e:
                st.error(f"{uploaded.name}: {e}")
            progress.progress((i + 1) / len(uploads))

        status.empty()

        if results:
            st.success(f"{len(results)}枚の処理が完了しました。")
            cols = st.columns(min(3, len(results)))
            for i, (name, data) in enumerate(results):
                with cols[i % len(cols)]:
                    st.image(data, caption=name, use_container_width=True)
                    st.download_button(
                        "画像を保存",
                        data=data,
                        file_name=name,
                        mime="image/png",
                        key=f"download_{i}",
                        use_container_width=True,
                    )

            if len(results) > 1:
                buf = io.BytesIO()
                with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
                    for name, data in results:
                        z.writestr(name, data)
                st.download_button(
                    "📦 全画像をZIPで保存",
                    data=buf.getvalue(),
                    file_name="menu-photo-pro.zip",
                    mime="application/zip",
                    use_container_width=True,
                )
