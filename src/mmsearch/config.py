"""Configuration and platform paths (XDG-compliant)."""
from __future__ import annotations

import os
import tomllib
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

import tomli_w

APP_NAME = "mmsearch"


def _xdg_config_home() -> Path:
    return Path(os.environ.get("XDG_CONFIG_HOME") or Path.home() / ".config")


def _xdg_data_home() -> Path:
    return Path(os.environ.get("XDG_DATA_HOME") or Path.home() / ".local" / "share")


def config_dir() -> Path:
    p = _xdg_config_home() / APP_NAME
    p.mkdir(parents=True, exist_ok=True)
    return p


def data_dir() -> Path:
    p = _xdg_data_home() / APP_NAME
    p.mkdir(parents=True, exist_ok=True)
    return p


def config_path() -> Path:
    return config_dir() / "config.toml"


def db_path() -> Path:
    return data_dir() / "mmsearch.db"


@dataclass
class Config:
    server_url: str = ""
    team_id: str = ""
    sync_channel_ids: list[str] = field(default_factory=list)  # empty = all my channels

    @classmethod
    def load(cls) -> Config:
        p = config_path()
        if not p.exists():
            return cls()
        with open(p, "rb") as f:
            data = tomllib.load(f)
        return cls(
            server_url=data.get("server_url", ""),
            team_id=data.get("team_id", ""),
            sync_channel_ids=list(data.get("sync_channel_ids", [])),
        )

    def save(self) -> None:
        p = config_path()
        payload: dict[str, Any] = asdict(self)
        with open(p, "wb") as f:
            tomli_w.dump(payload, f)
        os.chmod(p, 0o600)
