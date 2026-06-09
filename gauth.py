#!/usr/bin/env python3
"""
Hosted Google OAuth — the web flow that replaces authorize.py's desktop
`run_local_server`.

YOU own ONE Google Cloud project + ONE "Web" OAuth client. Every user connects
THROUGH it: /connect builds a consent URL whose `state` is a signed copy of the
Telegram user id, Google redirects to {BASE_URL}/oauth2callback, and we swap the
code for a long-lived refresh token that we store (encrypted) against that user.

Scope is **drive.file ONLY** — the non-sensitive scope. Because the bot CREATES
the spreadsheet itself, drive.file is enough for the Sheets API to read/write that
same file, and it keeps the app on Google's *light* verification path (no costly
CASA security audit that the sensitive `spreadsheets` scope would trigger).
"""

import os
import time
import hmac
import base64
import hashlib

# Google sometimes returns extra granted scopes (e.g. openid); relax so the
# token exchange doesn't raise "Scope has changed".
os.environ.setdefault("OAUTHLIB_RELAX_TOKEN_SCOPE", "1")

import httpx
from google.oauth2.credentials import Credentials
from google.auth.transport.requests import Request
from google_auth_oauthlib.flow import Flow

# ── Config (all from env — set once on the host) ────────────────────────
CLIENT_ID     = os.environ.get("GOOGLE_CLIENT_ID", "")
CLIENT_SECRET = os.environ.get("GOOGLE_CLIENT_SECRET", "")
BASE_URL      = os.environ.get("BASE_URL", "").rstrip("/")
REDIRECT_URI  = os.environ.get("OAUTH_REDIRECT_URI") or (BASE_URL + "/oauth2callback")

# drive.file ONLY (non-sensitive). The bot creates the sheet, so this suffices.
SCOPES = ["https://www.googleapis.com/auth/drive.file"]

AUTH_URI  = "https://accounts.google.com/o/oauth2/auth"
TOKEN_URI = "https://oauth2.googleapis.com/token"
REVOKE_URI = "https://oauth2.googleapis.com/revoke"

# Secret used to sign the OAuth `state` (HMAC). Falls back to FERNET_KEY so a
# single configured secret is enough to run the service.
_STATE_SECRET = (
    os.environ.get("STATE_SECRET")
    or os.environ.get("FERNET_KEY")
    or "dev-insecure-state-secret"
).encode()

_STATE_MAX_AGE = 900  # signed consent links are valid for 15 minutes


def is_configured() -> bool:
    """True only when the host has wired up the OAuth client + base URL."""
    return bool(CLIENT_ID and CLIENT_SECRET and REDIRECT_URI.startswith("http"))


# ── Signed state (stateless CSRF + user binding, no extra deps) ─────────
def _b64e(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode()


def _b64d(s: str) -> bytes:
    return base64.urlsafe_b64decode(s + "=" * (-len(s) % 4))


def sign_state(telegram_id: int) -> str:
    """Pack `telegram_id:issued_at` with an HMAC tag → opaque state token."""
    payload = f"{telegram_id}:{int(time.time())}".encode()
    sig = hmac.new(_STATE_SECRET, payload, hashlib.sha256).digest()[:16]
    return f"{_b64e(payload)}.{_b64e(sig)}"


def verify_state(state: str, max_age: int = _STATE_MAX_AGE) -> int:
    """Validate the HMAC + freshness, returning the Telegram id. Raises on tamper."""
    payload_b64, sig_b64 = state.split(".", 1)
    payload = _b64d(payload_b64)
    expected = hmac.new(_STATE_SECRET, payload, hashlib.sha256).digest()[:16]
    if not hmac.compare_digest(expected, _b64d(sig_b64)):
        raise ValueError("bad state signature")
    tid_str, issued_str = payload.decode().split(":")
    if time.time() - int(issued_str) > max_age:
        raise ValueError("state expired")
    return int(tid_str)


# ── OAuth flow ──────────────────────────────────────────────────────────
def _client_config() -> dict:
    return {
        "web": {
            "client_id": CLIENT_ID,
            "client_secret": CLIENT_SECRET,
            "auth_uri": AUTH_URI,
            "token_uri": TOKEN_URI,
            "redirect_uris": [REDIRECT_URI],
        }
    }


def _build_flow(state: str | None = None) -> Flow:
    return Flow.from_client_config(
        _client_config(), scopes=SCOPES, redirect_uri=REDIRECT_URI, state=state
    )


def consent_url(telegram_id: int) -> str:
    """Build the Google consent URL for this user (offline + force refresh token)."""
    flow = _build_flow()
    url, _ = flow.authorization_url(
        access_type="offline",
        prompt="consent",                # always issue a refresh token
        include_granted_scopes="true",
        state=sign_state(telegram_id),
    )
    return url


def exchange_code(code: str) -> Credentials:
    """Swap an authorization code for credentials (with a refresh token)."""
    flow = _build_flow()
    flow.fetch_token(code=code)
    return flow.credentials


def creds_from_refresh(refresh_token: str) -> Credentials:
    """Rebuild usable credentials from a stored refresh token + refresh them."""
    creds = Credentials(
        token=None,
        refresh_token=refresh_token,
        token_uri=TOKEN_URI,
        client_id=CLIENT_ID,
        client_secret=CLIENT_SECRET,
        scopes=SCOPES,
    )
    creds.refresh(Request())
    return creds


def revoke(refresh_token: str) -> bool:
    """Best-effort revoke of a refresh token at Google (for /disconnect)."""
    try:
        r = httpx.post(
            REVOKE_URI,
            data={"token": refresh_token},
            headers={"Content-Type": "application/x-www-form-urlencoded"},
            timeout=15,
        )
        return r.status_code == 200
    except Exception:
        return False
