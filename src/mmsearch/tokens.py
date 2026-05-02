"""Token storage with OS keyring + file fallback.

Some Linux desktops install the `keyring` Python package but lack a working
backend (e.g., headless WSL with no D-Bus). In that case `keyring.set_password`
silently succeeds against the "fail" backend and `get_password` returns None
later, so users see "no token saved" after init reported success.

To prevent this, `save_token` performs a **read-back verification** after
writing to keyring. If the token cannot be read back, it falls back to a
0600-mode file at `<config_dir>/token`.

Set the environment variable `MMSEARCH_TOKEN_STORAGE=file` to bypass keyring
entirely and always use the file backend (useful for headless / shared / CI
environments).
"""
from __future__ import annotations

import contextlib
import os

from . import config

SERVICE = "mmsearch"
TOKEN_KEY = "mattermost_token"
STORAGE_ENV = "MMSEARCH_TOKEN_STORAGE"


def _fallback_path():
    return config.config_dir() / "token"


def _force_file() -> bool:
    return os.environ.get(STORAGE_ENV, "").strip().lower() == "file"


def _save_to_file(token: str) -> None:
    fp = _fallback_path()
    fp.write_text(token)
    os.chmod(fp, 0o600)


def _save_to_keyring(token: str) -> bool:
    """Attempt to save to OS keyring, then verify by read-back.
    Returns True only if the token was actually persisted.
    """
    try:
        import keyring
    except ImportError:
        return False
    try:
        keyring.set_password(SERVICE, TOKEN_KEY, token)
    except Exception:
        return False
    try:
        return keyring.get_password(SERVICE, TOKEN_KEY) == token
    except Exception:
        return False


def save_token(token: str) -> str:
    """Save token. Returns 'keyring' or 'file' indicating where it ended up."""
    if not _force_file() and _save_to_keyring(token):
        # Clean any stale fallback file
        fp = _fallback_path()
        if fp.exists():
            fp.unlink()
        return "keyring"

    _save_to_file(token)
    # Also clear any stale keyring entry so load_token doesn't get a stale value
    if not _force_file():
        with contextlib.suppress(Exception):
            import keyring

            with contextlib.suppress(Exception):
                keyring.delete_password(SERVICE, TOKEN_KEY)
    return "file"


def load_token() -> str | None:
    if not _force_file():
        try:
            import keyring

            t = keyring.get_password(SERVICE, TOKEN_KEY)
            if t:
                return t
        except Exception:
            pass
    fp = _fallback_path()
    if fp.exists():
        return fp.read_text().strip() or None
    return None


def storage_location() -> str:
    """Where is the token currently stored? 'keyring' / 'file' / 'none'."""
    if _force_file():
        return "file" if _fallback_path().exists() else "none"
    try:
        import keyring

        if keyring.get_password(SERVICE, TOKEN_KEY):
            return "keyring"
    except Exception:
        pass
    return "file" if _fallback_path().exists() else "none"


def delete_token() -> None:
    with contextlib.suppress(Exception):
        import keyring

        with contextlib.suppress(Exception):
            keyring.delete_password(SERVICE, TOKEN_KEY)
    fp = _fallback_path()
    if fp.exists():
        fp.unlink()
