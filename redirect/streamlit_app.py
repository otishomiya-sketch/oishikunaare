"""Forwarder for the old address (https://7ayyryczawpyuggappqsqqd.streamlit.app).

Sales messages, flyers and LINE links sent before the move point at the old
Streamlit Community Cloud address. Deploy this file there (main file path
redirect/streamlit_app.py, custom subdomain 7ayyryczawpyuggappqsqqd) and it
sends visitors to https://menu.otis.company with the same query string, so the
demo code (?code=), outreach tracking (?ref=) and flyer tag (?src=) still work.
"""

import json
from urllib.parse import urlencode

import streamlit as st
import streamlit.components.v1 as components

NEW_URL = "https://menu.otis.company"

st.set_page_config(page_title="Menu Photo Pro", page_icon="🍽️", layout="centered")

params = {k: v for k, v in st.query_params.items()}
target = f"{NEW_URL}/?{urlencode(params)}" if params else f"{NEW_URL}/"

st.markdown("### Menu Photo Pro は新しいアドレスに移りました")
st.write("下のボタンを押すと、新しいページが開きます。")
st.link_button("👉 新しいページを開く", target, type="primary", width="stretch")
st.caption(f"新しいアドレス：{NEW_URL}")

# Streamlit Community Cloud shows apps inside a sandboxed frame that may not move
# the whole tab, so the button (which opens a new tab outside the frame) is the
# main path. Where the page is not framed (e.g. run locally), move the tab
# automatically. Never load the app inside the frame: payments and the saved
# demo code do not work reliably there.
target_js = json.dumps(target)
components.html(
    "<script>"
    "try {"
    "  var d = window.parent.document, s = d.createElement('script');"
    f"  s.textContent = 'try {{ if (window.top === window) window.location.replace(' + {json.dumps(target_js)} + ');"
    f" else window.top.location.replace(' + {json.dumps(target_js)} + '); }} catch (e) {{}}';"
    "  d.body.appendChild(s);"
    "} catch (e) {}"
    "</script>",
    height=0,
)
