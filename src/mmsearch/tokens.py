"""トークンの永続化層（OS keyring + ファイル fallback）。

一部の Linux デスクトップ環境（D-Bus が利用できない headless WSL 等）では、
`keyring` パッケージはインストールされていてもバックエンドが機能せず、
`set_password` がサイレントに「失敗の成功」を返すことがある。その結果
`get_password` は後で None を返し、`init` 直後は動いていたはずなのに次回
セッション以降「no token saved」エラーが出続けるという症状になる。

これを防ぐため `save_token` は書き込み直後に **read-back 検証** を行う。
読み戻しに失敗した場合は 0600 パーミッションのファイル
(`<config_dir>/token`) に自動的に fallback する。

環境変数 `MMSEARCH_TOKEN_STORAGE=file` を設定すると、keyring を一切使わず
ファイル保存に固定できる（CI / 共有環境 / デバッグ用途）。
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
    """OS keyring へ保存し、read-back で実際に永続化されたか検証する。
    実際に保存できた場合のみ True を返す。
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
    """トークンを保存する。実際に格納された場所 ('keyring' / 'file') を返す。"""
    if not _force_file() and _save_to_keyring(token):
        # keyring に成功したら、過去の fallback ファイルが残っていれば削除する
        # (load_token が誤って古いトークンを返してしまうのを防ぐため)
        fp = _fallback_path()
        if fp.exists():
            fp.unlink()
        return "keyring"

    _save_to_file(token)
    # ファイル保存にした場合も、古い keyring エントリが残っていれば消す
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
    """現在トークンが格納されている場所を返す: 'keyring' / 'file' / 'none'。"""
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
