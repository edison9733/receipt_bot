#!/usr/bin/env python3
"""
Per-user auto-provisioning — runs the moment a user finishes Google consent.

Replaces the manual "create a Sheet, copy its ID, create a Drive folder, copy its
ID, run setup_sheets.py" dance. Given a user's fresh credentials we:

  1. create a new **Receipt Tracker** spreadsheet,
  2. apply the full Slate-Professional formatting (setup_sheets.build_sheet),
  3. create a **Receipts** Drive folder,

and hand back both ids for storage against the user's row.

Everything here works on the non-sensitive **drive.file** scope alone: the app is
allowed to read/write the files it creates, and both the spreadsheet and the folder
are created by the app.
"""

import logging

from googleapiclient.discovery import build

import setup_sheets

log = logging.getLogger("receiptbot.provision")

SHEET_TITLE  = "Receipt Tracker"
FOLDER_NAME  = "Receipts"
FOLDER_MIME  = "application/vnd.google-apps.folder"


def provision_user(creds) -> tuple[str, str]:
    """Create + format the sheet and create the Drive folder. Returns (sheet_id, folder_id)."""
    sheets = build("sheets", "v4", credentials=creds, cache_discovery=False)
    drive  = build("drive", "v3", credentials=creds, cache_discovery=False)

    # 1. Create the spreadsheet (drive.file lets the Sheets API own + edit it).
    created = sheets.spreadsheets().create(
        body={"properties": {"title": SHEET_TITLE}},
        fields="spreadsheetId",
    ).execute()
    sheet_id = created["spreadsheetId"]
    log.info("Created spreadsheet %s", sheet_id)

    # 2. Apply the full 3-tab formatting (same code path as setup_sheets CLI).
    setup_sheets.build_sheet(sheets, sheet_id)

    # 3. Create the top-level Receipts folder (bot.py nests Type/Category beneath).
    folder = drive.files().create(
        body={"name": FOLDER_NAME, "mimeType": FOLDER_MIME},
        fields="id",
    ).execute()
    folder_id = folder["id"]
    log.info("Created Drive folder %s", folder_id)

    return sheet_id, folder_id
