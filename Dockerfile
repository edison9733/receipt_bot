# Receipt Bot — prebuilt, single-user self-host image.
#
# Tesseract (OCR) is baked in AND the operator's Google OAuth client is baked in
# at build time, so the END USER installs nothing and configures no Google project.
# Build once via CI (.github/workflows/docker.yml) and publish to GHCR.

FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

# tesseract-ocr = OCR engine; libglib2.0-0 + libgomp1 = opencv-headless runtime deps.
RUN apt-get update && apt-get install -y --no-install-recommends \
        tesseract-ocr \
        libglib2.0-0 \
        libgomp1 \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.txt .
RUN pip install -r requirements.txt

COPY . .

# ── Operator's Google OAuth client, injected at BUILD time from CI secrets ──
# drive.file scope only; consent screen published to production. Passed as build
# args so the published image "just works" — the end user sets none of this.
ARG GOOGLE_CLIENT_ID=""
ARG GOOGLE_CLIENT_SECRET=""
ENV GOOGLE_CLIENT_ID=${GOOGLE_CLIENT_ID} \
    GOOGLE_CLIENT_SECRET=${GOOGLE_CLIENT_SECRET}

# Single-user self-host defaults. The loopback redirect works for every
# self-hoster because the container's port 8080 is published to their machine.
ENV BASE_URL=http://localhost:8080 \
    DB_PATH=/app/data/receiptbot.db

# Encrypted datastore + the auto-generated encryption key live here.
# Keep this volume (the run command mounts a named volume `receiptbot`).
VOLUME ["/app/data"]
EXPOSE 8080

CMD ["python", "app.py"]
