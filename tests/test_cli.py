"""CLI のスモークテスト（typer.testing.CliRunner ベース）。"""
from __future__ import annotations

from pathlib import Path

import pytest
from typer.testing import CliRunner

from mmsearch import db
from mmsearch.cli import _validate_url, app

runner = CliRunner()


@pytest.fixture(autouse=True)
def _isolate_xdg(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """XDG パスを tmp に向けて、ユーザーの実環境を汚染しないようにする。"""
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "config"))
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "data"))


def _seed_posts(n: int, *, message: str = "match") -> None:
    """`message` にマッチする投稿を n 件 DB に投入する（CLI検索テスト用）。"""
    db.init_db()
    with db.transaction() as conn:
        conn.execute(
            "INSERT INTO channels (id, team_id, name, display_name, type, last_synced_at) "
            "VALUES ('c1', 't1', 'general', 'General', 'O', 0)"
        )
        conn.execute(
            "INSERT INTO users (id, username) VALUES ('u1', 'alice')"
        )
        for i in range(n):
            conn.execute(
                "INSERT INTO posts (id, channel_id, user_id, create_at, update_at, message) "
                "VALUES (?, 'c1', 'u1', ?, ?, ?)",
                (f"p{i}", 1_700_000_000_000 + i, 1_700_000_000_000 + i, f"{message} {i}"),
            )


def test_version() -> None:
    result = runner.invoke(app, ["version"])
    assert result.exit_code == 0
    assert "mmsearch" in result.output


def test_help_lists_all_commands() -> None:
    result = runner.invoke(app, ["--help"])
    assert result.exit_code == 0
    for cmd in ("init", "doctor", "sync", "search", "open", "channels", "reset"):
        assert cmd in result.output


def test_search_help_shows_filters() -> None:
    result = runner.invoke(app, ["search", "--help"])
    assert result.exit_code == 0
    for opt in ("--channel", "--user", "--since", "--until", "--limit"):
        assert opt in result.output


def test_doctor_unconfigured_exits_1() -> None:
    result = runner.invoke(app, ["doctor"])
    assert result.exit_code == 1


def test_channels_no_data_does_not_crash() -> None:
    result = runner.invoke(app, ["channels"])
    assert result.exit_code == 0
    assert "no channels" in result.output.lower()


def test_search_empty_db_returns_no_results() -> None:
    result = runner.invoke(app, ["search", "anything"])
    assert result.exit_code == 0
    assert "no results" in result.output.lower()


def test_search_invalid_date_exits_1() -> None:
    result = runner.invoke(app, ["search", "x", "--since", "not-a-date"])
    assert result.exit_code == 1


def test_search_help_mentions_all_flag() -> None:
    result = runner.invoke(app, ["search", "--help"])
    assert result.exit_code == 0
    assert "--all" in result.output


def test_search_warns_when_limit_reached() -> None:
    """ヒット数が limit に達したら「limit reached」の警告が出ること。"""
    _seed_posts(10)
    result = runner.invoke(app, ["search", "match", "-n", "5"])
    assert result.exit_code == 0
    assert "limit reached" in result.output


def test_search_no_warning_below_limit() -> None:
    """ヒット数が limit 未満なら警告は出さないこと。"""
    _seed_posts(3)
    result = runner.invoke(app, ["search", "match", "-n", "10"])
    assert result.exit_code == 0
    assert "limit reached" not in result.output


def test_search_all_flag_returns_everything() -> None:
    _seed_posts(15)
    result = runner.invoke(app, ["search", "match", "--all"])
    assert result.exit_code == 0
    assert "limit reached" not in result.output
    assert "15 result(s)" in result.output


def test_help_lists_login_command() -> None:
    result = runner.invoke(app, ["--help"])
    assert result.exit_code == 0
    assert "login" in result.output


def test_login_unconfigured_exits_1() -> None:
    result = runner.invoke(app, ["login"])
    assert result.exit_code == 1
    assert "not configured" in result.output.lower()


def test_login_help_mentions_browser() -> None:
    result = runner.invoke(app, ["login", "--help"])
    assert result.exit_code == 0
    assert "--browser" in result.output


def test_init_help_mentions_browser_options() -> None:
    result = runner.invoke(app, ["init", "--help"])
    assert result.exit_code == 0
    assert "--browser" in result.output
    assert "--no-browser" in result.output


def test_doctor_unconfigured_shows_actionable_hint() -> None:
    """未設定エラーは `init` と `login` の両方を案内すること。"""
    result = runner.invoke(app, ["doctor"])
    assert result.exit_code == 1
    assert "init" in result.output
    assert "login" in result.output


def test_reset_yes_no_existing_data_succeeds() -> None:
    result = runner.invoke(app, ["reset", "--yes"])
    assert result.exit_code == 0


def test_reset_conflicting_flags_exits_2() -> None:
    result = runner.invoke(app, ["reset", "--config", "--db", "--yes"])
    assert result.exit_code == 2


def test_reset_aborts_on_no() -> None:
    result = runner.invoke(app, ["reset"], input="n\n")
    assert result.exit_code == 0
    assert "aborted" in result.output.lower()


def test_validate_url_accepts_http() -> None:
    assert _validate_url("https://example.com") == "https://example.com"
    assert _validate_url("http://example.com/") == "http://example.com"
    assert _validate_url("  https://example.com/  ") == "https://example.com"


def test_validate_url_rejects_invalid() -> None:
    with pytest.raises(ValueError, match="must start with"):
        _validate_url("example.com")
    with pytest.raises(ValueError, match="must start with"):
        _validate_url("ftp://example.com")
    with pytest.raises(ValueError, match="required"):
        _validate_url("   ")
