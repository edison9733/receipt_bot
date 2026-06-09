#!/usr/bin/env bash
set -euo pipefail

IMAGE="ghcr.io/edison9733/receipt-bot:latest"
NAME="receiptbot"

if ! command -v docker >/dev/null 2>&1; then
  echo "Docker isn't installed. Install Docker Desktop, open it once, then re-run this:"
  echo "  https://www.docker.com/products/docker-desktop/"
  exit 1
fi

if ! docker info >/dev/null 2>&1; then
  echo "Docker is installed but not running. Open Docker Desktop, wait for the whale icon, then re-run this."
  exit 1
fi

read -r -p "Paste your Telegram bot token (from @BotFather): " TOKEN
TOKEN="$(printf '%s' "${TOKEN:-}" | tr -d '[:space:]')"
if [ -z "$TOKEN" ]; then
  echo "No token entered. Aborting."
  exit 1
fi

echo "Pulling the latest bot image..."
docker pull "$IMAGE"

echo "Starting the bot..."
docker rm -f "$NAME" >/dev/null 2>&1 || true
docker run -d \
  --name "$NAME" \
  --restart unless-stopped \
  -p 8080:8080 \
  -v receiptbot:/app/data \
  -e TELEGRAM_TOKEN="$TOKEN" \
  "$IMAGE" >/dev/null

echo
echo "Bot is running."
echo "In Telegram, message your bot and send:  /start  then  /connect"
echo "After approving Google, send:  /setkey sk-...   then send a receipt photo."
