"""ブラウザCookie抽出のテスト。"""
from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from mmsearch import auth


def _cookie(name: str, value: str) -> SimpleNamespace:
    return SimpleNamespace(name=name, value=value)


@pytest.fixture
def fake_bc3(monkeypatch: pytest.MonkeyPatch) -> MagicMock:
    """browser_cookie3 のエイリアスを差し替えて挙動を制御可能にする。"""
    fake = MagicMock()
    monkeypatch.setattr(auth, "_bc3", fake)
    return fake


def test_extract_specific_browser(fake_bc3: MagicMock) -> None:
    fake_bc3.chrome.return_value = [
        _cookie("OTHER", "x"),
        _cookie("MMAUTHTOKEN", "tkn123"),
    ]
    token, used = auth.extract_cookie("https://mm.example.com", browser="chrome")
    assert token == "tkn123"
    assert used == "chrome"
    fake_bc3.chrome.assert_called_once_with(domain_name="mm.example.com")


def test_extract_auto_tries_browsers_in_order(fake_bc3: MagicMock) -> None:
    """auto は chrome → chromium → firefox → ... の順で試行し、最初の成功で打ち切ること。"""
    fake_bc3.chrome.side_effect = RuntimeError("no chrome profile")
    fake_bc3.chromium.side_effect = RuntimeError("no chromium profile")
    fake_bc3.firefox.return_value = [_cookie("MMAUTHTOKEN", "ff_token")]

    token, used = auth.extract_cookie("https://mm.example.com")
    assert token == "ff_token"
    assert used == "firefox"
    fake_bc3.edge.assert_not_called()
    fake_bc3.brave.assert_not_called()
    fake_bc3.vivaldi.assert_not_called()
    fake_bc3.opera.assert_not_called()
    fake_bc3.safari.assert_not_called()


def test_extract_chromium_specifically(fake_bc3: MagicMock) -> None:
    """Chromium は Chrome と別プロファイルパスのため、独立してサポートする必要がある。"""
    fake_bc3.chromium.return_value = [_cookie("MMAUTHTOKEN", "chromium_token")]
    token, used = auth.extract_cookie("https://mm.example.com", browser="chromium")
    assert token == "chromium_token"
    assert used == "chromium"
    fake_bc3.chromium.assert_called_once_with(domain_name="mm.example.com")


def test_extract_auto_collects_errors_when_all_fail(fake_bc3: MagicMock) -> None:
    fake_bc3.chrome.side_effect = RuntimeError("err1")
    fake_bc3.firefox.return_value = []  # MMAUTHTOKEN が見つからないケース
    fake_bc3.edge.side_effect = RuntimeError("err3")
    fake_bc3.brave.side_effect = RuntimeError("err4")
    fake_bc3.safari.side_effect = RuntimeError("err5")

    with pytest.raises(auth.CookieError) as ei:
        auth.extract_cookie("https://mm.example.com")

    msg = str(ei.value)
    assert "chrome" in msg and "err1" in msg
    assert "firefox" in msg
    assert "edge" in msg


def test_extract_unknown_browser_raises(fake_bc3: MagicMock) -> None:
    with pytest.raises(auth.CookieError, match="unknown browser"):
        auth.extract_cookie("https://mm.example.com", browser="netscape")


def test_extract_invalid_url_raises(fake_bc3: MagicMock) -> None:
    with pytest.raises(auth.CookieError, match="invalid URL"):
        auth.extract_cookie("not-a-url", browser="chrome")


def test_extract_specific_browser_no_cookie_raises(fake_bc3: MagicMock) -> None:
    fake_bc3.chrome.return_value = [_cookie("OTHER", "x")]
    with pytest.raises(auth.CookieError, match="no MMAUTHTOKEN"):
        auth.extract_cookie("https://mm.example.com", browser="chrome")


def test_extract_when_bc3_not_installed(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(auth, "_bc3", None)
    with pytest.raises(auth.CookieError, match="not installed"):
        auth.extract_cookie("https://mm.example.com", browser="chrome")


def test_extract_passes_domain_only_not_full_url(fake_bc3: MagicMock) -> None:
    """URL からスキームとパスを取り除いた domain だけを browser_cookie3 に渡すこと。"""
    fake_bc3.chrome.return_value = [_cookie("MMAUTHTOKEN", "x")]
    auth.extract_cookie("https://mm.example.com:8443/path?q=1", browser="chrome")
    fake_bc3.chrome.assert_called_once_with(domain_name="mm.example.com:8443")
