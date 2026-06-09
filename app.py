#!/usr/bin/env python3
"""
Hosted entry point — ONE process that runs both:

  • the Telegram bot (long-polling for the first cut; webhooks are a Phase-2 swap), and
  • a tiny aiohttp web server that handles the Google OAuth redirect at
    GET {BASE_URL}/oauth2callback  (+ a `/healthz` health check).

Flow: user taps /connect → approves on Google → Google redirects here with
`code` + signed `state` → we verify the state (→ Telegram id), exchange the code
for a refresh token, store it (encrypted), auto-provision the user's sheet +
folder, and DM them to come back and /setkey.

Run locally or in the container with:  python app.py
"""

import _bootstrap  # noqa: F401,E402 — MUST be first: sets FERNET_KEY + BASE_URL before gauth/db import

import os
import signal
import asyncio
import logging

from aiohttp import web
from telegram.ext import ApplicationBuilder

import db
import gauth
import provision
import bot

logging.basicConfig(format="%(asctime)s [%(levelname)s] %(message)s", level=logging.INFO)
log = logging.getLogger("receiptbot.app")

TELEGRAM_TOKEN = os.environ["TELEGRAM_TOKEN"]
PORT = int(os.environ.get("PORT", "8080"))

_SUCCESS_HTML = """<!doctype html>
<html><head><meta charset="utf-8"><title>Connected</title>
<style>
 body{font-family:system-ui,-apple-system,Segoe UI,Roboto,sans-serif;background:#0F172A;
      color:#F1F5F9;display:flex;min-height:100vh;align-items:center;justify-content:center;margin:0}
 .card{background:#1E293B;padding:40px 48px;border-radius:16px;text-align:center;max-width:420px}
 h1{margin:0 0 8px;font-size:26px} p{color:#94A3B8;line-height:1.5}
</style></head>
<body><div class="card">
 <h1>✅ Connected!</h1>
 <p>Your Receipt Tracker has been created. You can close this tab and return to
 Telegram — paste your DeepSeek key with <b>/setkey</b>, then start sending receipts.</p>
</div></body></html>"""


async def health(request: web.Request) -> web.Response:
    return web.Response(text="ok")


def _do_connect(tid: int, code: str) -> str:
    """Blocking work: exchange code, store token, provision sheet+folder. Returns sheet link."""
    creds = gauth.exchange_code(code)
    refresh = creds.refresh_token
    if not refresh:
        raise RuntimeError(
            "Google did not return a refresh token. Use /disconnect, then /connect again."
        )
    db.set_google_token(tid, refresh)
    sheet_id, folder_id = provision.provision_user(creds)
    db.set_provision(tid, sheet_id, folder_id)
    return f"https://docs.google.com/spreadsheets/d/{sheet_id}"


async def oauth2callback(request: web.Request) -> web.Response:
    application = request.app["tg_app"]
    err = request.query.get("error")
    if err:
        return web.Response(text=f"Authorization cancelled: {err}", status=400)

    state = request.query.get("state", "")
    code = request.query.get("code", "")
    if not state or not code:
        return web.Response(text="Missing code/state.", status=400)

    try:
        tid = gauth.verify_state(state)
    except Exception:
        return web.Response(text="Invalid or expired link. Tap /connect in Telegram again.",
                            status=400)

    try:
        # Offload the blocking Google calls so the event loop (and the bot) stays responsive.
        link = await asyncio.get_running_loop().run_in_executor(None, _do_connect, tid, code)
    except Exception as e:
        log.exception("OAuth callback failed for %s", tid)
        try:
            await application.bot.send_message(
                tid, f"⚠️ Connecting failed: {e}\nTap /connect to try again.")
        except Exception:
            pass
        return web.Response(text=f"Something went wrong: {e}", status=500)

    try:
        await application.bot.send_message(
            tid,
            "✅ *Google connected* and your Receipt Tracker is ready!\n"
            f"{link}\n\n"
            "Now paste your DeepSeek key:\n`/setkey sk-...`\n\n"
            "Then just send a receipt photo. 📸",
            parse_mode="Markdown", disable_web_page_preview=True,
        )
    except Exception:
        log.warning("Could not DM user %s after connect", tid)

    return web.Response(text=_SUCCESS_HTML, content_type="text/html")


async def main() -> None:
    db.init_db()
    if not gauth.is_configured():
        log.warning("OAuth not configured (GOOGLE_CLIENT_ID/SECRET/BASE_URL) — "
                    "/connect will tell users the bot isn't set up yet.")

    application = ApplicationBuilder().token(TELEGRAM_TOKEN).build()
    bot.register_handlers(application)

    web_app = web.Application()
    web_app["tg_app"] = application
    web_app.add_routes([
        web.get("/", health),
        web.get("/healthz", health),
        web.get("/oauth2callback", oauth2callback),
    ])
    runner = web.AppRunner(web_app)
    await runner.setup()
    site = web.TCPSite(runner, "0.0.0.0", PORT)

    stop = asyncio.Event()
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            loop.add_signal_handler(sig, stop.set)
        except NotImplementedError:  # e.g. Windows
            pass

    async with application:
        await application.start()
        await application.updater.start_polling(drop_pending_updates=True)
        await site.start()
        log.info("Bot polling + web server on :%d. Authorized users: %s",
                 PORT, bot.AUTHORIZED or "ALL")
        await stop.wait()
        log.info("Shutting down…")
        await application.updater.stop()
        await application.stop()
        await runner.cleanup()


if __name__ == "__main__":
    asyncio.run(main())
