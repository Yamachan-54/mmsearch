"""設定ファイルの保存・読み込みテスト。"""
from __future__ import annotations

import os
from pathlib import Path

from mmsearch import config


def test_config_roundtrip(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    cfg = config.Config(
        server_url="https://example.com",
        team_id="t123",
        sync_channel_ids=["c1", "c2"],
    )
    cfg.save()
    assert config.config_path().exists()

    # POSIX では 0600 になっていること
    mode = os.stat(config.config_path()).st_mode & 0o777
    assert mode == 0o600

    loaded = config.Config.load()
    assert loaded.server_url == "https://example.com"
    assert loaded.team_id == "t123"
    assert loaded.sync_channel_ids == ["c1", "c2"]


def test_config_default_when_missing(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    loaded = config.Config.load()
    assert loaded.server_url == ""
    assert loaded.team_id == ""
    assert loaded.sync_channel_ids == []
