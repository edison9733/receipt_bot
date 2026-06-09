#!/usr/bin/env python3
"""
Telegram Receipt Bot — Malaysian Tax Edition
OCR → DeepSeek classify (Expense vs Relief) → Google Drive (Type/Category folders) → Google Sheets (Expenses/Relief tabs).

Auth: OAuth user credentials (uploads land in YOUR Drive, owned by you).
"""

import os, io, re, json, logging, datetime, textwrap, subprocess, tempfile
from pathlib import Path

import cv2
import numpy as np
import httpx

from google.oauth2.credentials import Credentials
from google.auth.transport.requests import Request
from googleapiclient.discovery import build
from googleapiclient.http import MediaIoBaseUpload

from telegram import Update
from telegram.ext import (
    ApplicationBuilder, CommandHandler, MessageHandler, filters, ContextTypes
)

import categories as cat

# ── Config ──────────────────────────────────────────────────────────────
BOT_TOKEN       = os.environ["TELEGRAM_TOKEN"]
SHEET_ID        = os.environ["SHEET_ID"]
DRIVE_FOLDER_ID = os.environ.get("DRIVE_FOLDER_ID", "")
DEEPSEEK_URL    = os.environ.get("DEEPSEEK_URL", "https://api.deepseek.com/v1/chat/completions")
DEEPSEEK_KEY    = os.environ.get("DEEPSEEK_API_KEY", "")
DEEPSEEK_MODEL  = os.environ.get("DEEPSEEK_MODEL", "deepseek-chat")
AUTHORIZED      = {int(x) for x in os.environ.get("AUTHORIZED_USERS", "").split(",") if x.strip()}

CLIENT_SECRET_FILE = os.environ.get("GOOGLE_CLIENT_SECRET", "/home/apple/receiptbot/client_secret.json")
TOKEN_FILE         = os.environ.get("GOOGLE_TOKEN_FILE", "/home/apple/receiptbot/token.json")

SCOPES = [
    "https://www.googleapis.com/auth/drive.file",
    "https://www.googleapis.com/auth/spreadsheets",
]

logging.basicConfig(
    format="%(asctime)s [%(levelname)s] %(message)s", level=logging.INFO
)
logging.getLogger("httpx").setLevel(logging.WARNING)
log = logging.getLogger("receiptbot")


# ── Google auth (OAuth) ─────────────────────────────────────────────────
def get_google_creds() -> Credentials:
    creds = None
    if os.path.exists(TOKEN_FILE):
        creds = Credentials.from_authorized_user_file(TOKEN_FILE, SCOPES)
    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        else:
            # Lazy import — only needed for the very first interactive auth.
            from google_auth_oauthlib.flow import InstalledAppFlow
            flow = InstalledAppFlow.from_client_secrets_file(CLIENT_SECRET_FILE, SCOPES)
            creds = flow.run_local_server(port=0, open_browser=False)
        with open(TOKEN_FILE, "w") as fh:
            fh.write(creds.to_json())
        os.chmod(TOKEN_FILE, 0o600)
    return creds


_creds = get_google_creds()
drive_svc  = build("drive", "v3", credentials=_creds, cache_discovery=False)
sheets_svc = build("sheets", "v4", credentials=_creds, cache_discovery=False)


# ── Drive: two-level folder routing (Type → Category) ──────────────────
_folder_cache: dict[tuple, str] = {}


def _drive_escape(name: str) -> str:
    return name.replace("\\", "\\\\").replace("'", "\\'")


def _get_or_create_folder(parent_id: str, name: str) -> str:
    """Return the Drive folder id for `name` under `parent_id`, creating it if needed."""
    key = (parent_id, name)
    if key in _folder_cache:
        return _folder_cache[key]

    q = (
        f"'{parent_id}' in parents and name='{_drive_escape(name)}' "
        f"and mimeType='application/vnd.google-apps.folder' and trashed=false"
    )
    resp = drive_svc.files().list(q=q, fields="files(id,name)", spaces="drive").execute()
    files = resp.get("files", [])
    if files:
        fid = files[0]["id"]
    else:
        meta = {
            "name": name,
            "mimeType": "application/vnd.google-apps.folder",
            "parents": [parent_id],
        }
        fid = drive_svc.files().create(body=meta, fields="id").execute()["id"]
        log.info("Created Drive folder: %s", name)
    _folder_cache[key] = fid
    return fid


def _target_folder(receipt_type: str, category: str) -> str:
    """Root → 'Expenses'/'Relief' → category subfolder. Returns leaf folder id."""
    type_name = cat.RELIEF_FOLDER if receipt_type == cat.TYPE_RELIEF else cat.EXPENSE_FOLDER
    type_id = _get_or_create_folder(DRIVE_FOLDER_ID, type_name)
    return _get_or_create_folder(type_id, cat.folder_name(category))


def upload_to_drive(image_bytes: bytes, filename: str, receipt_type: str, category: str) -> str:
    if not DRIVE_FOLDER_ID:
        return ""
    folder_id = _target_folder(receipt_type, category)
    media = MediaIoBaseUpload(io.BytesIO(image_bytes), mimetype="image/jpeg", resumable=True)
    meta = {"name": filename, "parents": [folder_id]}
    f = drive_svc.files().create(body=meta, media_body=media, fields="id,webViewLink").execute()
    log.info("Uploaded %s → %s/%s", filename,
             cat.RELIEF_FOLDER if receipt_type == cat.TYPE_RELIEF else cat.EXPENSE_FOLDER,
             cat.folder_name(category))
    return f.get("webViewLink", "")


# ── Sheets: route to Expenses or Relief tab ────────────────────────────
def append_to_sheet(receipt_type: str, fields: dict, link: str, ocr_text: str):
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

    sheets_svc.spreadsheets().values().append(
        spreadsheetId=SHEET_ID, range=rng,
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


def classify_and_extract(ocr_text: str) -> tuple[str, dict]:
    if DEEPSEEK_URL and DEEPSEEK_KEY:
        headers = {"Content-Type": "application/json",
                   "Authorization": f"Bearer {DEEPSEEK_KEY}"}
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
    (r"pharmacy|clinic|hospital|dental|optic|guardian|watson|caring|farmasi", "Medical (Self/Spouse/Child)"),
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


# ── Telegram handlers ──────────────────────────────────────────────────
async def start(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "📸 Send me a receipt photo.\n\n"
        "I'll OCR it, decide if it's a *tax Relief* or an *Expense*, file the image into "
        "the matching Google Drive folder, and log it to the right Google Sheets tab.",
        parse_mode="Markdown",
    )


async def help_cmd(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "/start — welcome\n/help — this message\n\n"
        "Just send a receipt photo (or an image file) and I'll handle the rest."
    )


async def handle_photo(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if AUTHORIZED and user_id not in AUTHORIZED:
        await update.message.reply_text("⛔ Not authorized.")
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
    log.info("Downloaded %d bytes from user %d", len(img_bytes), user_id)

    try:
        await msg.edit_text("🔍 Running OCR…")
        ocr_text = ocr_tesseract(preprocess(img_bytes))
        if not ocr_text:
            await msg.edit_text("❌ Couldn't read any text from that image.")
            return
        log.info("OCR: %d chars", len(ocr_text))

        await msg.edit_text("🧠 Classifying (Relief vs Expense)…")
        receipt_type, fields = classify_and_extract(ocr_text)
        category = fields["category"]

        drive_link = ""
        if DRIVE_FOLDER_ID:
            await msg.edit_text("📤 Filing into Google Drive…")
            date_prefix = fields["date"] or datetime.date.today().isoformat()
            safe_merchant = re.sub(r"[^\w\s-]", "", fields["merchant"])[:30].strip() or "receipt"
            filename = f"{date_prefix}_{safe_merchant}.jpg"
            try:
                drive_link = upload_to_drive(img_bytes, filename, receipt_type, category)
            except Exception as e:
                log.error("Drive upload failed: %s", e)
                drive_link = "upload failed"

        await msg.edit_text("📊 Logging to Google Sheets…")
        append_to_sheet(receipt_type, fields, drive_link, ocr_text)

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
        if drive_link and drive_link != "upload failed":
            folder = cat.RELIEF_FOLDER if receipt_type == cat.TYPE_RELIEF else cat.EXPENSE_FOLDER
            summary += f"📁 {folder} / {cat.folder_name(category)}\n[View receipt]({drive_link})\n"
        if fields["items"]:
            summary += f"🛒 {fields['items']}\n"

        await msg.edit_text(summary, parse_mode="Markdown", disable_web_page_preview=True)

    except Exception as e:
        log.exception("Processing failed")
        await msg.edit_text(f"❌ Failed: {e}")


# ── Main (Python 3.14-safe event loop) ─────────────────────────────────
def main():
    import asyncio, signal

    app = ApplicationBuilder().token(BOT_TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("help", help_cmd))
    app.add_handler(MessageHandler(filters.PHOTO | filters.Document.IMAGE, handle_photo))

    log.info("Bot started. Authorized users: %s", AUTHORIZED or "ALL")

    async def run():
        stop_event = asyncio.Event()
        loop = asyncio.get_running_loop()
        for sig in (signal.SIGINT, signal.SIGTERM):
            loop.add_signal_handler(sig, stop_event.set)
        async with app:
            await app.updater.start_polling(drop_pending_updates=True)
            await app.start()
            await stop_event.wait()
            await app.updater.stop()
            await app.stop()
            await app.shutdown()

    asyncio.run(run())


if __name__ == "__main__":
    main()
