#!/usr/bin/env python3
"""
One-time Google authorization → writes token.json.

Run this ONCE after placing client_secret.json next to it. It opens a Google
login in your browser, you approve Drive + Sheets access, and it saves the
long-lived token.json that bot.py and setup_sheets.py reuse forever (it
auto-refreshes, so you never log in again unless you revoke access).

OrbStack auto-forwards the Linux machine's localhost to your Mac, so the
login redirect on port 8765 just works — open the printed URL in your Mac
browser. (If it ever doesn't, run this on any computer with a browser and
copy the resulting token.json into the VM.)
"""

import os
from google_auth_oauthlib.flow import InstalledAppFlow

SCOPES = [
    "https://www.googleapis.com/auth/drive.file",
    "https://www.googleapis.com/auth/spreadsheets",
]
CLIENT = os.environ.get("GOOGLE_CLIENT_SECRET", "client_secret.json")
TOKEN = os.environ.get("GOOGLE_TOKEN_FILE", "token.json")

flow = InstalledAppFlow.from_client_secrets_file(CLIENT, SCOPES)
print("\n👉 Open this URL in your browser, approve, and wait for 'authentication flow has completed':\n")
creds = flow.run_local_server(port=8765, open_browser=False)

with open(TOKEN, "w") as fh:
    fh.write(creds.to_json())
os.chmod(TOKEN, 0o600)
print(f"\n✅ Saved {TOKEN} — you can now run setup_sheets.py and the bot.")
