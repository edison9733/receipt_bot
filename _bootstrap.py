"""
First-import bootstrap for single-user self-host.

MUST be the first import in app.py (before `db`/`gauth`), because gauth reads
BASE_URL and the OAuth client at import time and derives its CSRF state secret
from FERNET_KEY. This module:

  • defaults BASE_URL to the loopback callback (http://localhost:8080), and
  • ensures FERNET_KEY exists — generating one ONCE and persisting it next to
    the database, so the end user never creates or pastes an encryption key.

Deleting the data volume discards this key; the user simply runs /connect again.
An explicit FERNET_KEY / BASE_URL in the environment always takes precedence.
"""

import os
from pathlib import Path

from cryptography.fernet import Fernet

# Loopback OAuth callback — valid for every self-hoster (their own localhost).
os.environ.setdefault("BASE_URL", "http://localhost:8080")

# Persist the encryption key beside the SQLite datastore.
_db_path = os.environ.get("DB_PATH", "data/receiptbot.db")
_data_dir = Path(_db_path).expanduser().resolve().parent
_data_dir.mkdir(parents=True, exist_ok=True)
_key_file = _data_dir / "fernet.key"

if not os.environ.get("FERNET_KEY"):
    if _key_file.exists():
        key = _key_file.read_text().strip()
    else:
        key = Fernet.generate_key().decode()
        _key_file.write_text(key)
        try:
            os.chmod(_key_file, 0o600)
        except OSError:
            pass  # e.g. a Windows-mounted volume — non-fatal
    os.environ["FERNET_KEY"] = key
