#!/usr/bin/env python3
"""
Malaysian Tax Receipt Tracker — Google Sheets builder (YA 2025)

Run this ONCE (it is fully re-runnable / idempotent) to (re)build the spreadsheet
that bot.py writes into. It creates three colour-coded tabs:

  📘 Expenses  — general spending (11 cols)   ← bot writes  Expenses!A:K
  📗 Relief    — LHDN tax-relief items (10 cols) ← bot writes Relief!A:J
  📊 Summary   — auto-totalling dashboard (frequency-ordered)

Design goals (per request):
  • Cells auto-grow in HEIGHT (wrapStrategy = WRAP) so long text is fully visible,
    WITHOUT spilling into or resizing neighbouring columns. The two long "machine"
    columns (Receipt Link, Raw OCR) use CLIP instead, so a single huge value can
    never blow up the height of an entire row.
  • Dropdowns and the Summary are ordered MOST-USED → LEAST-USED (see categories.py)
    so everyday items sit at the very top and you never scroll.
  • Expenses and Relief stay on SEPARATE tabs.

Auth = the SAME OAuth token bot.py uses (token.json). Categories come from ONE
place — categories.py — imported by both this file and bot.py, so dropdowns, Drive
folder names and the SUMIFS formulas all use byte-for-byte identical strings.
"""

import os

from google.oauth2.credentials import Credentials
from google.auth.transport.requests import Request
from googleapiclient.discovery import build

from categories import (
    EXPENSE_CATEGORIES, RELIEF_TYPES, RELIEF_LIMITS,
    EXPENSE_FORM_B_BOX, form_b_box_label,
    ASSESSMENT_YEAR, RECEIPT_RETENTION_YEARS, FILING_DEADLINES,
)

# ── Config (env-driven; defaults work in the VM and on the Mac) ──────────
SHEET_ID = os.environ.get("SHEET_ID")
if not SHEET_ID:
    raise SystemExit(
        "❌ SHEET_ID is not set.\n"
        "   Load your env first, then re-run:\n"
        "     set -a && source /etc/receiptbot.env && set +a && python setup_sheets.py\n"
        "   (or one-off:  SHEET_ID=your-sheet-id python setup_sheets.py )"
    )
TOKEN_FILE = os.environ.get("GOOGLE_TOKEN_FILE") or os.path.expanduser("~/receiptbot/token.json")
CLIENT_SECRET_FILE = os.environ.get("GOOGLE_CLIENT_SECRET") or os.path.expanduser("~/receiptbot/client_secret.json")

SCOPES = [
    "https://www.googleapis.com/auth/drive.file",
    "https://www.googleapis.com/auth/spreadsheets",
]


# ── Auth: reuse the bot's OAuth token (refresh if expired) ──────────────
def get_creds():
    creds = None
    if os.path.exists(TOKEN_FILE):
        creds = Credentials.from_authorized_user_file(TOKEN_FILE, SCOPES)
    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        else:
            from google_auth_oauthlib.flow import InstalledAppFlow
            flow = InstalledAppFlow.from_client_secrets_file(CLIENT_SECRET_FILE, SCOPES)
            creds = flow.run_local_server(port=0, open_browser=False)
        with open(TOKEN_FILE, "w") as fh:
            fh.write(creds.to_json())
        os.chmod(TOKEN_FILE, 0o600)
    return creds


# ── Colours (RGB 0-255 → 0-1 floats) ───────────────────────────────────
def rgb(r, g, b):
    return {"red": r / 255, "green": g / 255, "blue": b / 255}


# ── Date helper for the YA / filing-deadline banner ─────────────────────
_MONTHS = ("Jan", "Feb", "Mar", "Apr", "May", "Jun",
           "Jul", "Aug", "Sep", "Oct", "Nov", "Dec")


def _pretty(iso):
    """'2026-06-30' → '30 Jun 2026' for a human-friendly banner."""
    y, m, d = (int(x) for x in iso.split("-"))
    return f"{d} {_MONTHS[m - 1]} {y}"


WHITE = rgb(255, 255, 255)

# Expenses — Deep Blue
EXP_HDR_BG = rgb(13, 71, 161)
EXP_SUB    = rgb(187, 222, 251)
EXP_ALT    = rgb(227, 242, 253)
EXP_TAB    = rgb(30, 136, 229)

# Relief — Deep Green
REL_HDR_BG = rgb(27, 94, 32)
REL_SUB    = rgb(200, 230, 201)
REL_ALT    = rgb(232, 245, 233)
REL_TAB    = rgb(56, 142, 60)

# Summary — Deep Purple tab
SUM_TAB    = rgb(142, 36, 170)


# ── Headers (MUST match bot.py append order exactly) ────────────────────
EXPENSES_HEADERS = [
    "Timestamp", "Merchant", "Date", "Amount (RM)", "Tax (RM)",
    "Category", "Payment Method", "Description",
    "Receipt Link", "Raw OCR", "Notes",
]
RELIEF_HEADERS = [
    "Timestamp", "Merchant", "Date", "Amount (RM)", "Relief Type",
    "Payment Method", "Description",
    "Receipt Link", "Raw OCR", "Notes",
]

# Per-tab layout. Ranges are half-open [start, end) like the Sheets API.
TAB_CONFIG = {
    "Expenses": {
        "headers":      EXPENSES_HEADERS,
        "widths":       [150, 160, 100, 110, 90, 175, 120, 240, 130, 200, 200],
        "amount_cols":  (3, 5),    # Amount (RM), Tax (RM)
        "dropdown_col": 5,         # Category
        "dropdown":     EXPENSE_CATEGORIES,
        "clip_cols":    (8, 10),   # Receipt Link, Raw OCR
        "hdr_bg":       EXP_HDR_BG,
        "alt":          EXP_ALT,
        "tab":          EXP_TAB,
    },
    "Relief": {
        "headers":      RELIEF_HEADERS,
        "widths":       [150, 160, 100, 110, 250, 120, 240, 130, 200, 200],
        "amount_cols":  (3, 4),    # Amount (RM)
        "dropdown_col": 4,         # Relief Type
        "dropdown":     RELIEF_TYPES,
        "clip_cols":    (7, 9),    # Receipt Link, Raw OCR
        "hdr_bg":       REL_HDR_BG,
        "alt":          REL_ALT,
        "tab":          REL_TAB,
    },
}

DATA_END = 1000  # format/validate rows 2..1000


# ═══════════════════════════════════════════════════════════════════════
def main():
    service = build("sheets", "v4", credentials=get_creds(), cache_discovery=False)
    ss = service.spreadsheets()

    # ── Existing tabs ───────────────────────────────────────────────────
    meta = ss.get(spreadsheetId=SHEET_ID).execute()
    existing = {s["properties"]["title"]: s["properties"]["sheetId"] for s in meta["sheets"]}
    print(f"📋 Existing tabs: {list(existing.keys())}")

    # ── Create the three tabs if missing ────────────────────────────────
    create = []
    for name, color, frozen in [
        ("Expenses", EXP_TAB, 1),
        ("Relief",   REL_TAB, 1),
        ("Summary",  SUM_TAB, 0),
    ]:
        if name not in existing:
            create.append({"addSheet": {"properties": {
                "title": name,
                "tabColorStyle": {"rgbColor": color},
                "gridProperties": {"frozenRowCount": frozen},
            }}})
            print(f"   ➕ Creating tab: {name}")
    if create:
        ss.batchUpdate(spreadsheetId=SHEET_ID, body={"requests": create}).execute()
        meta = ss.get(spreadsheetId=SHEET_ID).execute()
        existing = {s["properties"]["title"]: s["properties"]["sheetId"] for s in meta["sheets"]}

    exp_id = existing["Expenses"]
    rel_id = existing["Relief"]
    sum_id = existing["Summary"]

    # ── Wipe old conditional-format rules on our tabs (avoid stacking) ──
    cf_meta = ss.get(
        spreadsheetId=SHEET_ID,
        fields="sheets(properties.sheetId,conditionalFormats)",
    ).execute()
    del_reqs = []
    for sh in cf_meta["sheets"]:
        sid = sh["properties"]["sheetId"]
        if sid in (exp_id, rel_id, sum_id):
            for i in range(len(sh.get("conditionalFormats", [])) - 1, -1, -1):
                del_reqs.append({"deleteConditionalFormatRule": {"sheetId": sid, "index": i}})
    if del_reqs:
        ss.batchUpdate(spreadsheetId=SHEET_ID, body={"requests": del_reqs}).execute()

    # ── Clear Summary contents before rewriting ─────────────────────────
    ss.values().clear(spreadsheetId=SHEET_ID, range="Summary!A1:Z300").execute()

    # ── Write headers ───────────────────────────────────────────────────
    print("📝 Writing headers…")
    ss.values().update(
        spreadsheetId=SHEET_ID, range="Expenses!A1", valueInputOption="RAW",
        body={"values": [EXPENSES_HEADERS]},
    ).execute()
    ss.values().update(
        spreadsheetId=SHEET_ID, range="Relief!A1", valueInputOption="RAW",
        body={"values": [RELIEF_HEADERS]},
    ).execute()

    # ── Formatting for Expenses + Relief ────────────────────────────────
    print("🎨 Formatting data tabs (auto-wrap rows, dropdowns, colours)…")
    fmt = []
    for name, cfg in TAB_CONFIG.items():
        sid = existing[name]
        n = len(cfg["headers"])

        # Header style
        fmt.append({"repeatCell": {
            "range": {"sheetId": sid, "startRowIndex": 0, "endRowIndex": 1,
                      "startColumnIndex": 0, "endColumnIndex": n},
            "cell": {"userEnteredFormat": {
                "backgroundColor": cfg["hdr_bg"],
                "textFormat": {"foregroundColor": WHITE, "bold": True,
                               "fontSize": 11, "fontFamily": "Google Sans"},
                "horizontalAlignment": "CENTER", "verticalAlignment": "MIDDLE",
                "wrapStrategy": "WRAP",
            }},
            "fields": "userEnteredFormat(backgroundColor,textFormat,"
                      "horizontalAlignment,verticalAlignment,wrapStrategy)",
        }})

        # Header height + freeze + bottom border
        fmt.append({"updateDimensionProperties": {
            "range": {"sheetId": sid, "dimension": "ROWS", "startIndex": 0, "endIndex": 1},
            "properties": {"pixelSize": 46}, "fields": "pixelSize"}})
        fmt.append({"updateSheetProperties": {
            "properties": {"sheetId": sid, "gridProperties": {"frozenRowCount": 1}},
            "fields": "gridProperties.frozenRowCount"}})
        fmt.append({"updateBorders": {
            "range": {"sheetId": sid, "startRowIndex": 0, "endRowIndex": 1,
                      "startColumnIndex": 0, "endColumnIndex": n},
            "bottom": {"style": "SOLID_MEDIUM", "colorStyle": {"rgbColor": cfg["hdr_bg"]}}}})

        # Whole data area: WRAP + top-align → rows grow in height, columns stay put
        fmt.append({"repeatCell": {
            "range": {"sheetId": sid, "startRowIndex": 1, "endRowIndex": DATA_END,
                      "startColumnIndex": 0, "endColumnIndex": n},
            "cell": {"userEnteredFormat": {"wrapStrategy": "WRAP", "verticalAlignment": "TOP"}},
            "fields": "userEnteredFormat(wrapStrategy,verticalAlignment)"}})

        # Long machine columns: CLIP so they can't inflate row height
        c0, c1 = cfg["clip_cols"]
        fmt.append({"repeatCell": {
            "range": {"sheetId": sid, "startRowIndex": 1, "endRowIndex": DATA_END,
                      "startColumnIndex": c0, "endColumnIndex": c1},
            "cell": {"userEnteredFormat": {"wrapStrategy": "CLIP"}},
            "fields": "userEnteredFormat.wrapStrategy"}})

        # Amount/Tax columns: money format, right aligned
        a0, a1 = cfg["amount_cols"]
        fmt.append({"repeatCell": {
            "range": {"sheetId": sid, "startRowIndex": 1, "endRowIndex": DATA_END,
                      "startColumnIndex": a0, "endColumnIndex": a1},
            "cell": {"userEnteredFormat": {
                "numberFormat": {"type": "NUMBER", "pattern": "#,##0.00"},
                "horizontalAlignment": "RIGHT"}},
            "fields": "userEnteredFormat(numberFormat,horizontalAlignment)"}})

        # Column widths
        for i, w in enumerate(cfg["widths"]):
            fmt.append({"updateDimensionProperties": {
                "range": {"sheetId": sid, "dimension": "COLUMNS", "startIndex": i, "endIndex": i + 1},
                "properties": {"pixelSize": w}, "fields": "pixelSize"}})

        # Alternating row stripes
        fmt.append({"addConditionalFormatRule": {"rule": {
            "ranges": [{"sheetId": sid, "startRowIndex": 1, "endRowIndex": DATA_END,
                        "startColumnIndex": 0, "endColumnIndex": n}],
            "booleanRule": {
                "condition": {"type": "CUSTOM_FORMULA",
                              "values": [{"userEnteredValue": "=ISEVEN(ROW())"}]},
                "format": {"backgroundColor": cfg["alt"]}}},
            "index": 0}})

        # Category / Relief-Type dropdown (frequency-ordered)
        dc = cfg["dropdown_col"]
        fmt.append({"setDataValidation": {
            "range": {"sheetId": sid, "startRowIndex": 1, "endRowIndex": DATA_END,
                      "startColumnIndex": dc, "endColumnIndex": dc + 1},
            "rule": {"condition": {"type": "ONE_OF_LIST",
                                   "values": [{"userEnteredValue": v} for v in cfg["dropdown"]]},
                     "showCustomUi": True, "strict": False}}})

    ss.batchUpdate(spreadsheetId=SHEET_ID, body={"requests": fmt}).execute()

    # ════════════════════════════════════════════════════════════════════
    # SUMMARY (frequency-ordered, flat — no scrolling)
    # ════════════════════════════════════════════════════════════════════
    print("📊 Building Summary…")
    data = []

    def add(row):
        data.append(row)
        return len(data)            # 1-indexed row number just written

    # Info banner: assessment year + filing deadlines + receipt retention
    b_due  = _pretty(FILING_DEADLINES["form_b_with_business"]["due"])
    be_due = _pretty(FILING_DEADLINES["form_be_no_business"]["due"])
    banner1 = add([f"🧾  MALAYSIAN TAX RECEIPT TRACKER — {ASSESSMENT_YEAR}", "", "", ""])
    banner2 = add([f"Income earned 1 Jan–31 Dec 2025  ·  e-File by {b_due} (Form B, business) "
                   f"or {be_due} (Form BE)  ·  keep receipts {RECEIPT_RETENTION_YEARS} years",
                   "", "", ""])
    add(["", "", "", ""])

    exp_title = add(["📘  EXPENSES SUMMARY (by category)", "", "", ""])
    exp_sub   = add(["Category", "Total (RM)", "Count", "Avg (RM)"])
    exp_first = len(data) + 1
    cat_row   = {}
    for c in EXPENSE_CATEGORIES:
        r = len(data) + 1
        cat_row[c] = r
        add([c,
             f'=SUMIFS(Expenses!$D$2:$D${DATA_END},Expenses!$F$2:$F${DATA_END},"{c}")',
             f'=COUNTIF(Expenses!$F$2:$F${DATA_END},"{c}")',
             f'=IFERROR(B{r}/C{r},0)'])
    exp_last  = len(data)
    exp_total = add(["TOTAL EXPENSES",
                     f"=SUM(B{exp_first}:B{exp_last})",
                     f"=SUM(C{exp_first}:C{exp_last})",
                     f"=IFERROR(B{len(data) + 1}/C{len(data) + 1},0)"])

    add(["", "", "", ""])

    # Expenses regrouped by Form B Part-N box. Each box total just adds up the
    # category totals above, so the two blocks can never disagree. N-boxes go in
    # numeric order with CAPITAL (capital allowance) listed last.
    def _box_sort(b):
        return (1, 0) if b == "CAPITAL" else (0, int(b[1:]))
    ordered_boxes = sorted(set(EXPENSE_FORM_B_BOX.values()), key=_box_sort)
    box_title = add(["📦  EXPENSES BY FORM B BOX (Part N)", "", "", ""])
    box_sub   = add(["Form B Box", "Total (RM)", "", ""])
    box_first = len(data) + 1
    for box in ordered_boxes:
        cats = [c for c in EXPENSE_CATEGORIES if EXPENSE_FORM_B_BOX.get(c) == box]
        refs = "+".join(f"B{cat_row[c]}" for c in cats)
        add([f"{box} · {form_b_box_label(box)}", f"={refs}", "", ""])
    box_last  = len(data)

    add(["", "", "", ""])
    add(["", "", "", ""])

    rel_title = add([f"📗  TAX RELIEF SUMMARY ({ASSESSMENT_YEAR})", "", "", ""])
    rel_sub   = add(["Relief Type", "Claimed (RM)", "Max Limit (RM)", "Remaining (RM)"])
    rel_first = len(data) + 1
    for rt in RELIEF_TYPES:
        r = len(data) + 1
        limit = RELIEF_LIMITS.get(rt, 0)
        claimed = f'=SUMIFS(Relief!$D$2:$D${DATA_END},Relief!$E$2:$E${DATA_END},"{rt}")'
        if limit > 0:
            add([rt, claimed, limit, f"=MAX(0,C{r}-B{r})"])
        else:
            add([rt, claimed, "No Cap", "—"])
    rel_last  = len(data)
    rel_total = add(["TOTAL RELIEF CLAIMED", f"=SUM(B{rel_first}:B{rel_last})", "", ""])

    add(["", "", "", ""])
    note1 = add(["ⓘ  Medical sub-caps (Vaccination, Dental, Check-up/Mental-health, "
                 "Child learning-disability) share the RM10,000 umbrella — never sum past RM10,000.",
                 "", "", ""])
    note2 = add(["ⓘ  Disabled child: RM8,000 base + RM8,000 if aged 18+ in higher education "
                 "= up to RM16,000.", "", "", ""])
    note3 = add(["ⓘ  First-home loan interest: RM7,000 (house ≤ RM500k) or RM5,000 "
                 "(RM500k–RM750k), claimable for 3 consecutive YAs.", "", "", ""])
    note4 = add(["ⓘ  Expenses follow ITA 1967 s.33 (wholly & exclusively for business); "
                 "s.39 disallows private/capital items. Equipment & Software is a capital "
                 "allowance, not an N-box expense.", "", "", ""])

    ss.values().update(
        spreadsheetId=SHEET_ID, range="Summary!A1",
        valueInputOption="USER_ENTERED", body={"values": data},
    ).execute()

    # ── Summary formatting ──────────────────────────────────────────────
    print("🎨 Formatting Summary…")

    def band(r1, bg, size, white=False, bold=True, fields="backgroundColor,textFormat"):
        tf = {"bold": bold, "fontSize": size, "fontFamily": "Google Sans"}
        if white:
            tf["foregroundColor"] = WHITE
        return {"repeatCell": {
            "range": {"sheetId": sum_id, "startRowIndex": r1 - 1, "endRowIndex": r1,
                      "startColumnIndex": 0, "endColumnIndex": 4},
            "cell": {"userEnteredFormat": {"backgroundColor": bg, "textFormat": tf,
                                           "verticalAlignment": "MIDDLE"}},
            "fields": f"userEnteredFormat({fields},verticalAlignment)"}}

    sfmt = []

    # Money formatting across both blocks (then integer-ise the Count/Limit column)
    for first, total in [(exp_first, exp_total), (rel_first, rel_total)]:
        sfmt.append({"repeatCell": {
            "range": {"sheetId": sum_id, "startRowIndex": first - 1, "endRowIndex": total,
                      "startColumnIndex": 1, "endColumnIndex": 4},
            "cell": {"userEnteredFormat": {
                "numberFormat": {"type": "NUMBER", "pattern": "#,##0.00"},
                "horizontalAlignment": "RIGHT"}},
            "fields": "userEnteredFormat(numberFormat,horizontalAlignment)"}})
        sfmt.append({"repeatCell": {
            "range": {"sheetId": sum_id, "startRowIndex": first - 1, "endRowIndex": total,
                      "startColumnIndex": 2, "endColumnIndex": 3},
            "cell": {"userEnteredFormat": {"numberFormat": {"type": "NUMBER", "pattern": "#,##0"}}},
            "fields": "userEnteredFormat.numberFormat"}})

    # Form B box totals: money format on column B only
    sfmt.append({"repeatCell": {
        "range": {"sheetId": sum_id, "startRowIndex": box_first - 1, "endRowIndex": box_last,
                  "startColumnIndex": 1, "endColumnIndex": 2},
        "cell": {"userEnteredFormat": {
            "numberFormat": {"type": "NUMBER", "pattern": "#,##0.00"},
            "horizontalAlignment": "RIGHT"}},
        "fields": "userEnteredFormat(numberFormat,horizontalAlignment)"}})

    # Long category / relief / box names wrap (height grows; columns stay put)
    for first, last in [(exp_first, exp_last), (box_first, box_last), (rel_first, rel_last)]:
        sfmt.append({"repeatCell": {
            "range": {"sheetId": sum_id, "startRowIndex": first - 1, "endRowIndex": last,
                      "startColumnIndex": 0, "endColumnIndex": 1},
            "cell": {"userEnteredFormat": {"wrapStrategy": "WRAP", "verticalAlignment": "TOP"}},
            "fields": "userEnteredFormat(wrapStrategy,verticalAlignment)"}})

    # Top info banner (assessment year + filing deadlines + retention)
    sfmt.append(band(banner1, SUM_TAB,            13, white=True))
    sfmt.append(band(banner2, rgb(243, 229, 245),  9, bold=False))

    # Banners, sub-headers, totals
    sfmt.append(band(exp_title, EXP_HDR_BG, 14, white=True))
    sfmt.append(band(exp_sub,   EXP_SUB,    10))
    sfmt.append(band(exp_total, EXP_HDR_BG, 11, white=True))
    sfmt.append(band(box_title, EXP_HDR_BG, 12, white=True))
    sfmt.append(band(box_sub,   EXP_SUB,    10))
    sfmt.append(band(rel_title, REL_HDR_BG, 14, white=True))
    sfmt.append(band(rel_sub,   REL_SUB,    10))
    sfmt.append(band(rel_total, REL_HDR_BG, 11, white=True))

    # Centre the numeric sub-header labels
    for sub in (exp_sub, box_sub, rel_sub):
        sfmt.append({"repeatCell": {
            "range": {"sheetId": sum_id, "startRowIndex": sub - 1, "endRowIndex": sub,
                      "startColumnIndex": 1, "endColumnIndex": 4},
            "cell": {"userEnteredFormat": {"horizontalAlignment": "CENTER"}},
            "fields": "userEnteredFormat.horizontalAlignment"}})

    # Footnotes (LHDN caps / ITA notes): small grey italic, spills across the row
    sfmt.append({"repeatCell": {
        "range": {"sheetId": sum_id, "startRowIndex": note1 - 1, "endRowIndex": note4,
                  "startColumnIndex": 0, "endColumnIndex": 4},
        "cell": {"userEnteredFormat": {"textFormat": {
            "italic": True, "fontSize": 9, "fontFamily": "Google Sans",
            "foregroundColor": rgb(110, 110, 110)}}},
        "fields": "userEnteredFormat.textFormat"}})

    # Summary column widths + tab colour + no freeze
    for i, w in enumerate([360, 130, 150, 150]):
        sfmt.append({"updateDimensionProperties": {
            "range": {"sheetId": sum_id, "dimension": "COLUMNS", "startIndex": i, "endIndex": i + 1},
            "properties": {"pixelSize": w}, "fields": "pixelSize"}})
    sfmt.append({"updateSheetProperties": {
        "properties": {"sheetId": sum_id, "tabColorStyle": {"rgbColor": SUM_TAB},
                       "gridProperties": {"frozenRowCount": 0}},
        "fields": "tabColorStyle,gridProperties.frozenRowCount"}})

    ss.batchUpdate(spreadsheetId=SHEET_ID, body={"requests": sfmt}).execute()

    # ── Archive any stray legacy tabs (skip ours + already-archived) ────
    for name, sid in existing.items():
        if name in ("Expenses", "Relief", "Summary") or name.startswith("Archive"):
            continue
        new_name = "Archive" if name == "Sheet1" else f"Archive - {name}"
        try:
            ss.batchUpdate(spreadsheetId=SHEET_ID, body={"requests": [{
                "updateSheetProperties": {
                    "properties": {"sheetId": sid, "title": new_name}, "fields": "title"}}]}).execute()
            print(f"   📦 Renamed '{name}' → '{new_name}'")
        except Exception:
            pass

    # ── Done ────────────────────────────────────────────────────────────
    print("\n✅ Google Sheet rebuilt.")
    print(f"   📘 Expenses — {len(EXPENSES_HEADERS)} cols, {len(EXPENSE_CATEGORIES)} categories (frequency-ordered)")
    print(f"   📗 Relief   — {len(RELIEF_HEADERS)} cols, {len(RELIEF_TYPES)} relief types (frequency-ordered)")
    print(f"   📦 Form B   — {len(ordered_boxes)} Part-N boxes ({', '.join(ordered_boxes)})")
    print(f"   📊 Summary  — auto-totals, most-used first")
    print(f"\n🔗 https://docs.google.com/spreadsheets/d/{SHEET_ID}")


if __name__ == "__main__":
    main()
