#!/usr/bin/env python3
"""
Multi-tenant datastore for the hosted Receipt Bot.

One row per Telegram user:

    telegram_id → { google_refresh_token, deepseek_key, sheet_id, drive_folder_id }

Secrets (the Google refresh token and the DeepSeek key) are **encrypted at rest**
with Fernet (AES-128-CBC + HMAC) so a leaked database file is useless without the
key. The Fernet key comes from the FERNET_KEY env var — generate one once with:

    python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"

SQLite on a persistent volume is plenty to start; the same interface ports cleanly
to Postgres later (swap the connection + placeholders).
"""

import os
import sqlite3
import datetime
import threading
from typing import Optional

from cryptography.fernet import Fernet

# ── Config ──────────────────────────────────────────────────────────────
DB_PATH = os.environ.get("DB_PATH", "data/receiptbot.db")

_fernet: Optional[Fernet] = None
_lock = threading.Lock()


def _get_fernet() -> Fernet:
    """Lazily build the Fernet cipher from FERNET_KEY (fail loud if missing)."""
    global _fernet
    if _fernet is None:
        key = os.environ.get("FERNET_KEY")
        if not key:
            raise RuntimeError(
                "FERNET_KEY is not set. Generate one once with:\n"
                '  python -c "from cryptography.fernet import Fernet; '
                'print(Fernet.generate_key().decode())"\n'
                "then set it in the environment (keep it secret, never commit it)."
            )
        _fernet = Fernet(key.encode() if isinstance(key, str) else key)
    return _fernet


def _encrypt(plaintext: Optional[str]) -> Optional[str]:
    if plaintext is None:
        return None
    return _get_fernet().encrypt(plaintext.encode()).decode()


def _decrypt(token: Optional[str]) -> Optional[str]:
    if not token:
        return None
    return _get_fernet().decrypt(token.encode()).decode()


def _now() -> str:
    return datetime.datetime.now(datetime.timezone.utc).isoformat(timespec="seconds")


def _connect() -> sqlite3.Connection:
    parent = os.path.dirname(DB_PATH)
    if parent:
        os.makedirs(parent, exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


# ── Schema ──────────────────────────────────────────────────────────────
def init_db() -> None:
    """Create the users + settings tables if they don't exist (idempotent)."""
    with _lock, _connect() as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS users (
                telegram_id           INTEGER PRIMARY KEY,
                google_refresh_token  TEXT,   -- Fernet-encrypted
                deepseek_key          TEXT,   -- Fernet-encrypted
                sheet_id              TEXT,
                drive_folder_id       TEXT,
                created_at            TEXT,
                updated_at            TEXT
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS settings (
                key   TEXT PRIMARY KEY,
                value TEXT
            )
            """
        )


def _upsert(telegram_id: int, **cols) -> None:
    """Insert the user row if new, then update the given columns + updated_at."""
    with _lock, _connect() as conn:
        conn.execute(
            "INSERT OR IGNORE INTO users (telegram_id, created_at, updated_at) "
            "VALUES (?, ?, ?)",
            (telegram_id, _now(), _now()),
        )
        if cols:
            sets = ", ".join(f"{k} = ?" for k in cols) + ", updated_at = ?"
            params = list(cols.values()) + [_now(), telegram_id]
            conn.execute(f"UPDATE users SET {sets} WHERE telegram_id = ?", params)


# ── Public API ──────────────────────────────────────────────────────────
def get_user(telegram_id: int) -> Optional[dict]:
    """Return the raw row as a dict (secrets still encrypted), or None."""
    with _lock, _connect() as conn:
        row = conn.execute(
            "SELECT * FROM users WHERE telegram_id = ?", (telegram_id,)
        ).fetchone()
    return dict(row) if row else None


def set_google_token(telegram_id: int, refresh_token: str) -> None:
    _upsert(telegram_id, google_refresh_token=_encrypt(refresh_token))


def get_google_refresh_token(telegram_id: int) -> Optional[str]:
    u = get_user(telegram_id)
    return _decrypt(u["google_refresh_token"]) if u else None


def set_deepseek_key(telegram_id: int, key: str) -> None:
    _upsert(telegram_id, deepseek_key=_encrypt(key))


def get_deepseek_key(telegram_id: int) -> Optional[str]:
    u = get_user(telegram_id)
    return _decrypt(u["deepseek_key"]) if u else None


def set_provision(telegram_id: int, sheet_id: str, drive_folder_id: str) -> None:
    _upsert(telegram_id, sheet_id=sheet_id, drive_folder_id=drive_folder_id)


def is_connected(telegram_id: int) -> bool:
    u = get_user(telegram_id)
    return bool(u and u.get("google_refresh_token") and u.get("sheet_id"))


def delete_user(telegram_id: int) -> None:
    with _lock, _connect() as conn:
        conn.execute("DELETE FROM users WHERE telegram_id = ?", (telegram_id,))


# ── Owner-lock (single-user self-host) ───────────────────────────────────
def bind_owner_id(telegram_id: int) -> bool:
    """Set the owner only if none is stored yet. Returns True if THIS call did it.

    Uses INSERT OR IGNORE so concurrent first-starts are safe — exactly one user wins.
    The winner becomes the sole owner; everyone else is silently ignored.
    """
    with _lock, _connect() as conn:
        cursor = conn.execute(
            "INSERT OR IGNORE INTO settings (key, value) VALUES ('owner_id', ?)",
            (str(telegram_id),),
        )
        return cursor.rowcount == 1


def get_owner_id() -> Optional[int]:
    """Return the stored owner Telegram id, or None if no one has connected yet."""
    with _lock, _connect() as conn:
        row = conn.execute(
            "SELECT value FROM settings WHERE key = 'owner_id'"
        ).fetchone()
    return int(row[0]) if row else None
