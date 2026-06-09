#!/usr/bin/env python3
"""
Telegram Receipt Bot — Malaysian Tax Edition (hosted, multi-tenant)

One hosted bot serves MANY users. Each user connects their OWN Google account
(/connect) and pastes their OWN DeepSeek key (/setkey); the bot stores both
(encrypted) and auto-provisions a personal Receipt Tracker sheet + Receipts
Drive folder. Every receipt is OCR'd, classified (Expense vs tax Relief),
filed into that user's Drive and logged to that user's Sheet.

This module holds the Telegram handlers + per-receipt processing. The combined
web + polling entry point lives in app.py, which calls register_handlers().
"""

import os, io, re, json, logging, datetime, textwrap, subprocess, tempfile
from pathlib import Path
from types import SimpleNamespace

import cv2
import numpy as np
import httpx

from googleapiclient.discovery import build
from googleapiclient.http import MediaIoBaseUpload

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application, CommandHandler, MessageHandler, filters, ContextTypes
)

import categories as cat
import db
import gauth
import provision

# ── Config ──────────────────────────────────────────────────────────────
DEEPSEEK_URL       = os.environ.get("DEEPSEEK_URL", "https://api.deepseek.com/v1/chat/completions")
DEEPSEEK_MODEL     = os.environ.get("DEEPSEEK_MODEL", "deepseek-chat")
SHARED_DEEPSEEK_KEY = os.environ.get("SHARED_DEEPSEEK_KEY", "")  # optional fallback you fund
AUTHORIZED          = {int(x) for x in os.environ.get("AUTHORIZED_USERS", "").split(",") if x.strip()}

logging.basicConfig(
    format="%(asctime)s [%(levelname)s] %(message)s", level=logging.INFO
)
logging.getLogger("httpx").setLevel(logging.WARNING)
log = logging.getLogger("receiptbot")


# ── Per-user Google services (built from the stored refresh token, cached) ─
# Cache maps telegram_id → (refresh_token, SimpleNamespace(drive, sheets, ...)).
# Keyed by the token so a /disconnect+reconnect transparently rebuilds.
_svc_cache: dict[int, tuple[str, SimpleNamespace]] = {}


def get_user_ctx(tid: int) -> SimpleNamespace | None:
    """Return per-user services + ids, or None if the user hasn't connected."""
    refresh = db.get_google_refresh_token(tid)
    user = db.get_user(tid)
    if not refresh or not user or not user.get("sheet_id"):
        return None

    cached = _svc_cache.get(tid)
    if cached and cached[0] == refresh:
        return cached[1]

    creds = gauth.creds_from_refresh(refresh)
    ctx = SimpleNamespace(
        drive=build("drive", "v3", credentials=creds, cache_discovery=False),
        sheets=build("sheets", "v4", credentials=creds, cache_discovery=False),
        sheet_id=user["sheet_id"],
        folder_id=user.get("drive_folder_id") or "",
    )
    _svc_cache[tid] = (refresh, ctx)
    return ctx


def effective_deepseek_key(tid: int) -> str:
    """The user's own key if set, else the optional shared key you fund."""
    return db.get_deepseek_key(tid) or SHARED_DEEPSEEK_KEY


# ── Drive: two-level folder routing (Type → Category) ──────────────────
_folder_cache: dict[tuple, str] = {}  # (parent_id, name) → folder_id; parent ids are per-user


def _drive_escape(name: str) -> str:
    return name.replace("\\", "\\\\").replace("'", "\\'")


def _get_or_create_folder(drive, parent_id: str, name: str) -> str:
    key = (parent_id, name)
    if key in _folder_cache:
        return _folder_cache[key]

    q = (
        f"'{parent_id}' in parents and name='{_drive_escape(name)}' "
        f"and mimeType='application/vnd.google-apps.folder' and trashed=false"
    )
    resp = drive.files().list(q=q, fields="files(id,name)", spaces="drive").execute()
    files = resp.get("files", [])
    if files:
        fid = files[0]["id"]
    else:
        meta = {
            "name": name,
            "mimeType": "application/vnd.google-apps.folder",
            "parents": [parent_id],
        }
        fid = drive.files().create(body=meta, fields="id").execute()["id"]
        log.info("Created Drive folder: %s", name)
    _folder_cache[key] = fid
    return fid


def _target_folder(drive, root_id: str, receipt_type: str, category: str) -> str:
    """root → 'Expenses'/'Relief' → category subfolder. Returns leaf folder id."""
    type_name = cat.RELIEF_FOLDER if receipt_type == cat.TYPE_RELIEF else cat.EXPENSE_FOLDER
    type_id = _get_or_create_folder(drive, root_id, type_name)
    return _get_or_create_folder(drive, type_id, cat.folder_name(category))


def upload_to_drive(drive, root_id: str, image_bytes: bytes, filename: str,
                    receipt_type: str, category: str) -> str:
    if not root_id:
        return ""
    folder_id = _target_folder(drive, root_id, receipt_type, category)
    media = MediaIoBaseUpload(io.BytesIO(image_bytes), mimetype="image/jpeg", resumable=True)
    meta = {"name": filename, "parents": [folder_id]}
    f = drive.files().create(body=meta, media_body=media, fields="id,webViewLink").execute()
    log.info("Uploaded %s → %s/%s", filename,
             cat.RELIEF_FOLDER if receipt_type == cat.TYPE_RELIEF else cat.EXPENSE_FOLDER,
             cat.folder_name(category))
    return f.get("webViewLink", "")


# ── Sheets: route to Expenses or Relief tab ────────────────────────────
def append_to_sheet(sheets, sheet_id: str, receipt_type: str, fields: dict,
                    link: str, ocr_text: str):
    ts = datetime.datetime.now().isoformat(timespec="seconds")
    merchant = fields.get("merchant") or "Unknown"
    date     = fields.get("date") or ""
    amount   = fields.get("total")
    tax      = fields.get("tax")
    payment  = fields.get("payment_method") or ""
    category = fields.get("category")
    items    = fields.get("items") or ""
    notes    = fields.get("notes") or ""
    raw      = ocr_text[:500]

    if receipt_type == cat.TYPE_RELIEF:
        # Timestamp, Merchant, Date, Amount, Relief Type, Payment, Description, Receipt, Raw OCR, Notes
        row = [ts, merchant, date, amount, category, payment, items, link, raw, notes]
        rng = "Relief!A:J"
    else:
        # Timestamp, Merchant, Date, Amount, Tax, Category, Payment, Description, Receipt, Raw OCR, Notes
        row = [ts, merchant, date, amount, tax, category, payment, items, link, raw, notes]
        rng = "Expenses!A:K"

    sheets.spreadsheets().values().append(
        spreadsheetId=sheet_id, range=rng,
        valueInputOption="USER_ENTERED", insertDataOption="INSERT_ROWS",
        body={"values": [row]},
    ).execute()
    log.info("Appended row to '%s' tab.", rng.split("!")[0])


# ── Image preprocessing ────────────────────────────────────────────────
def preprocess(img_bytes: bytes):
    arr = np.frombuffer(img_bytes, np.uint8)
    img = cv2.imdecode(arr, cv2.IMREAD_COLOR)
    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    h, w = gray.shape
    if w < 1200:
        scale = 1200 / w
        gray = cv2.resize(gray, None, fx=scale, fy=scale, interpolation=cv2.INTER_CUBIC)
    gray = cv2.fastNlMeansDenoising(gray, h=12)
    gray = cv2.adaptiveThreshold(
        gray, 255, cv2.ADAPTIVE_THRESH_GAUSSIAN_C, cv2.THRESH_BINARY, 31, 7
    )
    return gray


def ocr_tesseract(gray_img) -> str:
    with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as f:
        cv2.imwrite(f.name, gray_img)
        tmp = f.name
    try:
        out = subprocess.run(
            ["tesseract", tmp, "stdout", "--psm", "6", "-l", "eng"],
            capture_output=True, text=True, timeout=30
        )
        return out.stdout.strip()
    finally:
        Path(tmp).unlink(missing_ok=True)


# ── DeepSeek: classify (Expense/Relief) + extract ──────────────────────
SYSTEM_PROMPT = (
    "You are a Malaysian personal income-tax assistant. You read OCR text from a "
    "receipt, decide whether it is a tax-RELIEF item or a general EXPENSE, assign the "
    "single best category, and extract structured fields. Reply with ONLY valid JSON."
)

USER_PROMPT = textwrap.dedent("""\
    Classify and extract this Malaysian receipt.

    "type" is "Relief" if the purchase qualifies for Malaysian personal income-tax
    relief (e.g. books, computer, smartphone, internet, sports equipment/gym, medical
    or dental, pharmacy, optician, insurance, EPF/PRS, education/course fees, childcare,
    breastfeeding equipment, EV charger, SSPN). Otherwise "type" is "Expense".

    {category_block}

    Return ONLY this JSON object:
    {{
      "type": "Relief" or "Expense",
      "category": "<one exact value from the matching list above>",
      "merchant": "store name",
      "date": "YYYY-MM-DD or null",
      "total": number or null,
      "tax": number or null,
      "currency": "MYR",
      "payment_method": "card / cash / ewallet / transfer / unknown",
      "items": "comma-separated main items",
      "notes": "short reason this category fits (optional)"
    }}

    Rules: default currency MYR. Use null for unknown numbers. Pick exactly one category.
    OCR text:
    ---
    {ocr}
""")


def _coerce_amount(v):
    if v is None or v == "":
        return None
    if isinstance(v, (int, float)):
        return v
    m = re.search(r"-?\d+(?:\.\d+)?", str(v).replace(",", ""))
    return float(m.group()) if m else None


def _normalize(data: dict) -> tuple[str, dict]:
    rtype = (data.get("type") or "").strip().capitalize()
    if rtype not in (cat.TYPE_EXPENSE, cat.TYPE_RELIEF):
        rtype = cat.TYPE_EXPENSE
    category = cat.valid_category(rtype, (data.get("category") or "").strip())
    fields = {
        "merchant": data.get("merchant") or "Unknown",
        "date": data.get("date") or "",
        "total": _coerce_amount(data.get("total")),
        "tax": _coerce_amount(data.get("tax")),
        "currency": data.get("currency") or "MYR",
        "payment_method": data.get("payment_method") or "unknown",
        "category": category,
        "items": data.get("items") or "",
        "notes": data.get("notes") or "",
    }
    return rtype, fields


def classify_and_extract(ocr_text: str, deepseek_key: str) -> tuple[str, dict]:
    if DEEPSEEK_URL and deepseek_key:
        headers = {"Content-Type": "application/json",
                   "Authorization": f"Bearer {deepseek_key}"}
        payload = {
            "model": DEEPSEEK_MODEL,
            "messages": [
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": USER_PROMPT.format(
                    category_block=cat.prompt_category_block(), ocr=ocr_text)},
            ],
            "temperature": 0.1,
            "max_tokens": 700,
            "response_format": {"type": "json_object"},
        }
        try:
            r = httpx.post(DEEPSEEK_URL, headers=headers, json=payload, timeout=60)
            r.raise_for_status()
            content = r.json()["choices"][0]["message"]["content"].strip()
            content = re.sub(r"^```(?:json)?\s*|\s*```$", "", content, flags=re.S).strip()
            s, e = content.find("{"), content.rfind("}")
            if s != -1 and e != -1:
                content = content[s:e + 1]
            return _normalize(json.loads(content))
        except Exception as ex:
            log.warning("DeepSeek failed (%s); using regex fallback.", ex)
    return _regex_fallback(ocr_text)


# ── Regex/keyword fallback ─────────────────────────────────────────────
_RELIEF_HINTS = [
    (r"dental|dentist|gigi|orthodont", "Dental Treatment"),
    (r"vaccin|vaksin|imunisasi|immuni", "Vaccination"),
    (r"pharmacy|clinic|hospital|optic|guardian|watson|caring|farmasi|klinik|hospital", "Medical (Self/Spouse/Child)"),
    (r"book|kinokuniya|mph|popular|computer|laptop|printer|streamyx|unifi|maxis|celcom|digi|internet", "Lifestyle (Books/Computer/Internet)"),
    (r"gym|fitness|sport|decathlon|al[- ]?ikhsan", "Sports Equipment & Activities"),
    (r"insurance|takaful|prudential|aia|great eastern", "Education & Medical Insurance"),
    (r"tuition|college|university|course|academy", "Self Education Fees"),
]


def _regex_fallback(ocr_text: str) -> tuple[str, dict]:
    low = ocr_text.lower()
    rtype, category = cat.TYPE_EXPENSE, cat.DEFAULT_EXPENSE
    for pat, c in _RELIEF_HINTS:
        if re.search(pat, low):
            rtype, category = cat.TYPE_RELIEF, c
            break

    total = re.search(r"(?:total|amount|due|grand|jumlah)[^\d]*([\d,]+\.\d{2})", ocr_text, re.I)
    tax   = re.search(r"(?:tax|sst|gst|service charge)[^\d]*([\d,]+\.\d{2})", ocr_text, re.I)
    date  = re.search(r"(\d{4}-\d{2}-\d{2})|(\d{1,2}[/-]\d{1,2}[/-]\d{2,4})", ocr_text)
    lines = [l.strip() for l in ocr_text.splitlines() if l.strip()]

    fields = {
        "merchant": lines[0][:60] if lines else "Unknown",
        "date": (date.group(0) if date else ""),
        "total": _coerce_amount(total.group(1)) if total else None,
        "tax": _coerce_amount(tax.group(1)) if tax else None,
        "currency": "MYR",
        "payment_method": "unknown",
        "category": category,
        "items": "",
        "notes": "auto (offline fallback)",
    }
    return rtype, fields


# ── Telegram command handlers ──────────────────────────────────────────
def _authorized(uid: int) -> bool:
    return not AUTHORIZED or uid in AUTHORIZED


async def start(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    if db.is_connected(uid):
        await update.message.reply_text(
            "👋 You're all set! Just send a receipt photo and I'll OCR it, sort it into "
            "*Expense* or *tax Relief*, file the image in your Drive and log it to your Sheet.\n\n"
            "/status — see your setup   ·   /setkey — update your DeepSeek key",
            parse_mode="Markdown",
        )
        return
    await update.message.reply_text(
        "👋 *Welcome to Receipt Bot* — Malaysian tax edition.\n\n"
        "Two quick steps and you're done:\n"
        "1️⃣  /connect — link your Google account (I'll auto-create your Receipt Tracker "
        "sheet + Receipts folder)\n"
        "2️⃣  /setkey `sk-...` — paste your DeepSeek key\n\n"
        "Then just send a receipt photo. 📸",
        parse_mode="Markdown",
    )


async def help_cmd(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "*Commands*\n"
        "/connect — link your Google account (auto-creates your sheet + folder)\n"
        "/setkey `sk-...` — set your DeepSeek API key (I delete the message after)\n"
        "/status — show your connection + links\n"
        "/disconnect — revoke Google access and erase your data\n\n"
        "Then just send a receipt photo and I'll handle the rest.",
        parse_mode="Markdown",
    )


async def connect(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    if not _authorized(uid):
        await update.message.reply_text("⛔ Not authorized.")
        return
    if not gauth.is_configured():
        await update.message.reply_text(
            "⚠️ This bot isn't fully set up for hosting yet (missing OAuth config). "
            "Ask the operator to set GOOGLE_CLIENT_ID / GOOGLE_CLIENT_SECRET / BASE_URL."
        )
        return
    url = gauth.consent_url(uid)
    kb = InlineKeyboardMarkup([[InlineKeyboardButton("🔗 Connect Google", url=url)]])
    await update.message.reply_text(
        "Tap to connect your Google account. You'll see Google's normal consent screen — "
        "approve it and come back here. I'll auto-create your Receipt Tracker sheet.",
        reply_markup=kb,
    )


async def setkey(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    if not _authorized(uid):
        await update.message.reply_text("⛔ Not authorized.")
        return
    key = (ctx.args[0].strip() if ctx.args else "")
    # Delete the user's message ASAP so the key isn't left in chat history.
    try:
        await update.message.delete()
    except Exception:
        pass
    if not key or not key.startswith("sk-"):
        await ctx.bot.send_message(
            uid, "Usage: send `/setkey sk-...` with your DeepSeek key.",
            parse_mode="Markdown",
        )
        return
    db.set_deepseek_key(uid, key)
    await ctx.bot.send_message(
        uid, "🔑 DeepSeek key saved (encrypted) and your message was deleted. "
             "You're ready — send a receipt photo!"
    )


async def status(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    user = db.get_user(uid)
    google_ok = bool(user and user.get("google_refresh_token"))
    key_ok = bool(db.get_deepseek_key(uid) or SHARED_DEEPSEEK_KEY)
    lines = ["*Your setup*"]
    lines.append(f"{'✅' if google_ok else '❌'} Google account "
                 f"{'connected' if google_ok else '— tap /connect'}")
    if user and user.get("sheet_id"):
        lines.append(f"📊 [Your Receipt Tracker sheet]"
                     f"(https://docs.google.com/spreadsheets/d/{user['sheet_id']})")
    src = "your key" if db.get_deepseek_key(uid) else ("shared key" if SHARED_DEEPSEEK_KEY else "none")
    lines.append(f"{'✅' if key_ok else '❌'} DeepSeek key — {src}"
                 + ("" if key_ok else " (tap /setkey, or I'll use offline keyword matching)"))
    await update.message.reply_text(
        "\n".join(lines), parse_mode="Markdown", disable_web_page_preview=True
    )


async def disconnect(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    refresh = db.get_google_refresh_token(uid)
    if refresh:
        gauth.revoke(refresh)
    _svc_cache.pop(uid, None)
    db.delete_user(uid)
    await update.message.reply_text(
        "🧹 Done — I revoked Google access and erased your stored data "
        "(your Sheet and Drive files stay in *your* Google account). "
        "Run /connect anytime to start again.",
        parse_mode="Markdown",
    )


# ── Receipt photo handler ──────────────────────────────────────────────
async def handle_photo(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    if not _authorized(uid):
        await update.message.reply_text("⛔ Not authorized.")
        return

    user_ctx = get_user_ctx(uid)
    if user_ctx is None:
        await update.message.reply_text(
            "🔗 First connect your Google account with /connect — then send the receipt again."
        )
        return

    msg = await update.message.reply_text("⏳ Downloading image…")

    if update.message.photo:
        file = await ctx.bot.get_file(update.message.photo[-1].file_id)
    elif update.message.document:
        file = await ctx.bot.get_file(update.message.document.file_id)
    else:
        await msg.edit_text("❌ No image found.")
        return

    img_bytes = bytes(await file.download_as_bytearray())
    log.info("Downloaded %d bytes from user %d", len(img_bytes), uid)

    try:
        await msg.edit_text("🔍 Running OCR…")
        ocr_text = ocr_tesseract(preprocess(img_bytes))
        if not ocr_text:
            await msg.edit_text("❌ Couldn't read any text from that image.")
            return
        log.info("OCR: %d chars", len(ocr_text))

        await msg.edit_text("🧠 Classifying (Relief vs Expense)…")
        receipt_type, fields = classify_and_extract(ocr_text, effective_deepseek_key(uid))
        category = fields["category"]

        drive_link = ""
        if user_ctx.folder_id:
            await msg.edit_text("📤 Filing into Google Drive…")
            date_prefix = fields["date"] or datetime.date.today().isoformat()
            safe_merchant = re.sub(r"[^\w\s-]", "", fields["merchant"])[:30].strip() or "receipt"
            filename = f"{date_prefix}_{safe_merchant}.jpg"
            try:
                drive_link = upload_to_drive(
                    user_ctx.drive, user_ctx.folder_id, img_bytes, filename,
                    receipt_type, category)
            except Exception as e:
                log.error("Drive upload failed: %s", e)
                drive_link = "upload failed"

        await msg.edit_text("📊 Logging to Google Sheets…")
        append_to_sheet(user_ctx.sheets, user_ctx.sheet_id, receipt_type,
                        fields, drive_link, ocr_text)

        icon = "📗 Relief" if receipt_type == cat.TYPE_RELIEF else "📘 Expense"
        amount = fields["total"]
        amount_str = f"RM {amount:,.2f}" if isinstance(amount, (int, float)) else "RM —"
        summary = (
            f"✅ *{icon}* logged!\n\n"
            f"🏪 {fields['merchant']}\n"
            f"📅 {fields['date'] or 'N/A'}\n"
            f"💰 {amount_str}\n"
            f"🏷️ {category}\n"
        )
        if receipt_type == cat.TYPE_EXPENSE:
            box = cat.form_b_box(category)
            summary += f"📦 Form B: {box} · {cat.form_b_box_label(box)}\n"
        else:
            cap = cat.relief_cap(category)
            if cap:
                summary += f"🧾 Relief cap: RM {cap:,.0f}\n"
        if drive_link and drive_link != "upload failed":
            folder = cat.RELIEF_FOLDER if receipt_type == cat.TYPE_RELIEF else cat.EXPENSE_FOLDER
            summary += f"📁 {folder} / {cat.folder_name(category)}\n[View receipt]({drive_link})\n"
        if fields["items"]:
            summary += f"🛒 {fields['items']}\n"

        await msg.edit_text(summary, parse_mode="Markdown", disable_web_page_preview=True)

    except Exception as e:
        log.exception("Processing failed")
        await msg.edit_text(f"❌ Failed: {e}")


# ── Wiring ──────────────────────────────────────────────────────────────
def register_handlers(application: Application) -> None:
    """Attach every handler to the PTB application (called by app.py)."""
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("help", help_cmd))
    application.add_handler(CommandHandler("connect", connect))
    application.add_handler(CommandHandler("setkey", setkey))
    application.add_handler(CommandHandler("status", status))
    application.add_handler(CommandHandler("disconnect", disconnect))
    application.add_handler(MessageHandler(filters.PHOTO | filters.Document.IMAGE, handle_photo))


if __name__ == "__main__":
    raise SystemExit("Run the hosted service with:  python app.py")
