"""トークン保存（read-back 検証 + ファイル fallback）のテスト。"""
from __future__ import annotations

import os
import sys
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from mmsearch import tokens


@pytest.fixture(autouse=True)
def _isolate_xdg(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "config"))
    monkeypatch.delenv(tokens.STORAGE_ENV, raising=False)


@pytest.fixture
def fake_keyring(monkeypatch: pytest.MonkeyPatch) -> MagicMock:
    """挙動を制御可能なフェイク `keyring` モジュールを差し込む。"""
    fake = MagicMock()
    fake._store = {}

    def set_pw(svc, key, val):
        fake._store[(svc, key)] = val

    def get_pw(svc, key):
        return fake._store.get((svc, key))

    def del_pw(svc, key):
        fake._store.pop((svc, key), None)

    fake.set_password.side_effect = set_pw
    fake.get_password.side_effect = get_pw
    fake.delete_password.side_effect = del_pw
    monkeypatch.setitem(sys.modules, "keyring", fake)
    return fake


def test_save_to_keyring_when_working(fake_keyring: MagicMock) -> None:
    where = tokens.save_token("abc123")
    assert where == "keyring"
    assert tokens.load_token() == "abc123"
    assert fake_keyring._store[("mmsearch", "mattermost_token")] == "abc123"


def test_save_falls_back_to_file_when_keyring_silently_drops(
    fake_keyring: MagicMock,
) -> None:
    """成功を返すが実際には保存しない keyring バックエンドを再現する。"""
    fake_keyring.set_password.side_effect = lambda *a, **kw: None  # no-op
    fake_keyring.get_password.return_value = None

    where = tokens.save_token("abc123")
    assert where == "file"

    fp = tokens._fallback_path()
    assert fp.exists()
    assert fp.read_text() == "abc123"
    assert os.stat(fp).st_mode & 0o777 == 0o600


def test_save_falls_back_when_keyring_raises(fake_keyring: MagicMock) -> None:
    fake_keyring.set_password.side_effect = RuntimeError("dbus dead")

    where = tokens.save_token("abc123")
    assert where == "file"
    assert tokens.load_token() == "abc123"


def test_force_file_via_env(
    fake_keyring: MagicMock, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv(tokens.STORAGE_ENV, "file")
    where = tokens.save_token("abc123")
    assert where == "file"
    # 環境変数指定時は keyring に一切触れないこと
    assert fake_keyring.set_password.call_count == 0


def test_save_clears_stale_file_on_keyring_success(fake_keyring: MagicMock) -> None:
    # 過去にファイル fallback で保存されていた状態を再現
    tokens._save_to_file("OLD")
    assert tokens._fallback_path().exists()

    # keyring が復活した場合は古いファイルを削除し、load_token が
    # 新しい値を返すようにする
    where = tokens.save_token("NEW")
    assert where == "keyring"
    assert not tokens._fallback_path().exists()
    assert tokens.load_token() == "NEW"


def test_save_clears_stale_keyring_on_file_save(fake_keyring: MagicMock) -> None:
    fake_keyring._store[("mmsearch", "mattermost_token")] = "STALE"
    fake_keyring.set_password.side_effect = RuntimeError("backend died")

    where = tokens.save_token("NEW")
    assert where == "file"
    # 逆方向: keyring が壊れた場合は古い keyring エントリを消し、
    # load_token がファイル経由の新値を返すようにする
    assert ("mmsearch", "mattermost_token") not in fake_keyring._store
    assert tokens.load_token() == "NEW"


def test_load_token_returns_none_when_nothing_saved(fake_keyring: MagicMock) -> None:
    assert tokens.load_token() is None


def test_storage_location(fake_keyring: MagicMock) -> None:
    assert tokens.storage_location() == "none"
    tokens.save_token("abc")
    assert tokens.storage_location() == "keyring"
    fake_keyring._store.clear()
    tokens._save_to_file("abc")
    assert tokens.storage_location() == "file"


def test_delete_token_removes_both(fake_keyring: MagicMock) -> None:
    tokens.save_token("abc")
    tokens._save_to_file("abc")  # ファイル側も用意して両方の削除を検証

    tokens.delete_token()
    assert ("mmsearch", "mattermost_token") not in fake_keyring._store
    assert not tokens._fallback_path().exists()
    assert tokens.load_token() is None
