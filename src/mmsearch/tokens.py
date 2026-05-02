"""Token storage with OS keyring + file fallback."""
from __future__ import annotations

import contextlib
import os

from . import config

SERVICE = "mmsearch"
TOKEN_KEY = "mattermost_token"


def _fallback_path():
    return config.config_dir() / "token"


def save_token(token: str) -> str:
    """Save token. Returns 'keyring' or 'file' indicating where it was stored."""
    try:
        import keyring

        keyring.set_password(SERVICE, TOKEN_KEY, token)
        fp = _fallback_path()
        if fp.exists():
            fp.unlink()
        return "keyring"
    except Exception:
        fp = _fallback_path()
        fp.write_text(token)
        os.chmod(fp, 0o600)
        return "file"


def load_token() -> str | None:
    try:
        import keyring

        t = keyring.get_password(SERVICE, TOKEN_KEY)
        if t:
            return t
    except Exception:
        pass
    fp = _fallback_path()
    if fp.exists():
        return fp.read_text().strip()
    return None


def delete_token() -> None:
    with contextlib.suppress(Exception):
        import keyring

        with contextlib.suppress(Exception):
            keyring.delete_password(SERVICE, TOKEN_KEY)
    fp = _fallback_path()
    if fp.exists():
        fp.unlink()
