# Receipt Bot — hosted, multi-tenant. OCR (Tesseract) is baked in so NOBODY
# installs anything. Build once, deploy to Railway / Render / Fly.io / Cloud Run.
FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

# tesseract-ocr = the OCR engine; libglib2.0-0 + libgomp1 = opencv-headless runtime deps.
RUN apt-get update && apt-get install -y --no-install-recommends \
        tesseract-ocr \
        libglib2.0-0 \
        libgomp1 \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.txt .
RUN pip install -r requirements.txt

COPY . .

# Encrypted SQLite datastore lives here — mount a PERSISTENT volume at /app/data
# (Railway/Render/Fly volume) so users don't have to reconnect after a redeploy.
ENV DB_PATH=/app/data/receiptbot.db

# The web server (OAuth callback + health check). Most hosts inject $PORT.
EXPOSE 8080

CMD ["python", "app.py"]
