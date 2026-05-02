"""CLI smoke tests via typer.testing."""
from __future__ import annotations

from pathlib import Path

import pytest
from typer.testing import CliRunner

from mmsearch.cli import _validate_url, app

runner = CliRunner()


@pytest.fixture(autouse=True)
def _isolate_xdg(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Redirect XDG paths to tmp so tests never touch the user's real config."""
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "config"))
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "data"))


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
