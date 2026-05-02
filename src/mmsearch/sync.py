"""Sync Mattermost posts to local SQLite database."""
from __future__ import annotations

import sqlite3
import time
from collections.abc import Callable
from typing import Any

from . import client as mm_client
from . import config as config_mod

PER_PAGE = 200
RATE_LIMIT_DELAY = 0.1   # seconds between paginated requests
MAX_PAGES_PER_CHANNEL = 5000  # safety cap (≈1M posts per channel)
SINCE_OVERLAP_MS = 1000  # re-fetch overlap to handle edge-of-second posts

OnProgress = Callable[[int], None]


def fetch_channels(
    client: mm_client.MattermostClient, cfg: config_mod.Config
) -> list[dict[str, Any]]:
    """Return channels to sync, filtered by configured IDs if any."""
    channels = client.my_channels(cfg.team_id)
    if cfg.sync_channel_ids:
        wanted = set(cfg.sync_channel_ids)
        channels = [c for c in channels if c["id"] in wanted]
    return channels


def upsert_channel(conn: sqlite3.Connection, ch: dict[str, Any]) -> None:
    conn.execute(
        """
        INSERT INTO channels (id, team_id, name, display_name, type, last_synced_at)
        VALUES (?, ?, ?, ?, ?, 0)
        ON CONFLICT(id) DO UPDATE SET
            team_id = excluded.team_id,
            name = excluded.name,
            display_name = excluded.display_name,
            type = excluded.type
        """,
        (ch["id"], ch["team_id"], ch["name"], ch["display_name"], ch["type"]),
    )


def _upsert_posts(conn: sqlite3.Connection, posts: dict[str, dict[str, Any]]) -> int:
    """Upsert posts. Returns count processed."""
    if not posts:
        return 0
    rows = [
        (
            p["id"],
            p["channel_id"],
            p["user_id"],
            p["create_at"],
            p["update_at"],
            (p.get("root_id") or None),
            p.get("message", ""),
        )
        for p in posts.values()
    ]
    conn.executemany(
        """
        INSERT INTO posts (id, channel_id, user_id, create_at, update_at, root_id, message)
        VALUES (?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(id) DO UPDATE SET
            update_at = excluded.update_at,
            message = excluded.message,
            root_id = excluded.root_id
        """,
        rows,
    )
    return len(rows)


def _ensure_users(
    conn: sqlite3.Connection,
    client: mm_client.MattermostClient,
    user_ids: set[str],
    cache: set[str],
) -> None:
    """Fetch missing users from API and cache them in DB. Cache is per-process."""
    todo = user_ids - cache
    if not todo:
        return
    # Filter by what's already in DB
    placeholders = ",".join("?" * len(todo))
    existing = {
        r[0]
        for r in conn.execute(
            f"SELECT id FROM users WHERE id IN ({placeholders})", tuple(todo)
        )
    }
    cache.update(existing)
    todo -= existing
    for uid in todo:
        try:
            u = client.user(uid)
            conn.execute(
                """
                INSERT INTO users (id, username, nickname) VALUES (?, ?, ?)
                ON CONFLICT(id) DO UPDATE SET
                    username = excluded.username,
                    nickname = excluded.nickname
                """,
                (u["id"], u.get("username", "(unknown)"), u.get("nickname")),
            )
        except mm_client.MattermostError:
            # Could be a deleted user — store placeholder so we don't retry
            conn.execute(
                "INSERT OR IGNORE INTO users (id, username) VALUES (?, ?)",
                (uid, "(unknown)"),
            )
        cache.add(uid)


def sync_channel(
    conn: sqlite3.Connection,
    client: mm_client.MattermostClient,
    channel: dict[str, Any],
    *,
    full: bool = False,
    user_cache: set[str] | None = None,
    on_progress: OnProgress | None = None,
    sleep: Callable[[float], None] = time.sleep,
) -> int:
    """Sync one channel. Returns number of posts upserted."""
    user_cache = user_cache if user_cache is not None else set()
    channel_id = channel["id"]

    row = conn.execute(
        "SELECT last_synced_at FROM channels WHERE id = ?", (channel_id,)
    ).fetchone()
    last_synced = (row[0] if row else 0) if not full else 0

    total = 0
    max_create_at = last_synced

    if last_synced > 0:
        # Incremental: ?since=<ms>. Returns up to ~1000 posts modified since then.
        since = max(0, last_synced - SINCE_OVERLAP_MS)
        resp = client.channel_posts(channel_id, since=since, per_page=PER_PAGE)
        posts = resp.get("posts") or {}
        if posts:
            n = _upsert_posts(conn, posts)
            total += n
            user_ids = {p["user_id"] for p in posts.values()}
            _ensure_users(conn, client, user_ids, user_cache)
            for p in posts.values():
                if p["create_at"] > max_create_at:
                    max_create_at = p["create_at"]
            if on_progress:
                on_progress(n)
    else:
        # Full sync: page-based pagination, newest first
        for page in range(MAX_PAGES_PER_CHANNEL):
            resp = client.channel_posts(channel_id, page=page, per_page=PER_PAGE)
            order = resp.get("order") or []
            posts = resp.get("posts") or {}
            if not order:
                break
            n = _upsert_posts(conn, posts)
            total += n
            user_ids = {p["user_id"] for p in posts.values()}
            _ensure_users(conn, client, user_ids, user_cache)
            for p in posts.values():
                if p["create_at"] > max_create_at:
                    max_create_at = p["create_at"]
            if on_progress:
                on_progress(n)
            if len(order) < PER_PAGE:
                break
            sleep(RATE_LIMIT_DELAY)

    if max_create_at > last_synced:
        conn.execute(
            "UPDATE channels SET last_synced_at = ? WHERE id = ?",
            (max_create_at, channel_id),
        )
    return total
