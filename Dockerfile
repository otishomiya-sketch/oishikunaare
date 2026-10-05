# Railway runs the app from this image (Streamlit Cloud used packages.txt instead).
FROM python:3.12-slim

# Japanese font for the video captions.
RUN apt-get update \
    && apt-get install -y --no-install-recommends fonts-noto-cjk \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY . .

# Railway keeps the whole secrets.toml in the STREAMLIT_SECRETS variable;
# write it where st.secrets looks before starting.
CMD printf '%s' "$STREAMLIT_SECRETS" > .streamlit/secrets.toml \
    && exec streamlit run app.py \
       --server.port "${PORT:-8501}" --server.address 0.0.0.0 --server.headless true
