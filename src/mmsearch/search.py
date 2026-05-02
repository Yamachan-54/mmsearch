"""Local full-text search against synced posts.

Uses LIKE '%query%' which is accelerated by the FTS5 trigram index.
This works for any query length (including 1-2 char Japanese substrings),
where MATCH would fail.

Filters can be combined: channel/user/date range/limit.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from . import db


@dataclass(frozen=True)
class SearchHit:
    post_id: str
    channel_id: str
    channel_name: str
    channel_display_name: str
    username: str
    create_at: int  # ms epoch
    message: str


def _like_escape(s: str) -> str:
    """Escape LIKE wildcards. Use with `ESCAPE '\\'`."""
    return s.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


def _parse_date(s: str) -> int:
    """ISO date/datetime → ms epoch. Naive datetimes interpreted as UTC."""
    s = s.strip().replace(" ", "T")
    try:
        dt = datetime.fromisoformat(s)
    except ValueError as e:
        raise ValueError(
            f"invalid date format (expected YYYY-MM-DD or YYYY-MM-DDTHH:MM): {s}"
        ) from e
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=UTC)
    return int(dt.timestamp() * 1000)


def search(
    query: str,
    *,
    channel: str | None = None,
    user: str | None = None,
    since: str | None = None,
    until: str | None = None,
    limit: int = 50,
    db_path: Path | None = None,
) -> list[SearchHit]:
    """Search posts. `channel` matches against name OR display_name (substring)."""
    if not query.strip():
        return []
    if limit <= 0:
        return []

    sql_parts = [
        "SELECT p.id, p.channel_id, p.create_at, p.message,",
        "       c.name AS channel_name,",
        "       c.display_name AS channel_display_name,",
        "       COALESCE(u.username, '(unknown)') AS username",
        "FROM posts p",
        "JOIN posts_fts ON p.rowid = posts_fts.rowid",
        "JOIN channels c ON p.channel_id = c.id",
        "LEFT JOIN users u ON p.user_id = u.id",
        "WHERE posts_fts.message LIKE ? ESCAPE '\\'",
    ]
    params: list[Any] = [f"%{_like_escape(query)}%"]

    if channel:
        ch_pat = f"%{_like_escape(channel)}%"
        sql_parts.append(
            "AND (c.name LIKE ? ESCAPE '\\' OR c.display_name LIKE ? ESCAPE '\\')"
        )
        params.extend([ch_pat, ch_pat])

    if user:
        sql_parts.append("AND u.username = ?")
        params.append(user)

    if since:
        sql_parts.append("AND p.create_at >= ?")
        params.append(_parse_date(since))

    if until:
        sql_parts.append("AND p.create_at <= ?")
        params.append(_parse_date(until))

    sql_parts.append("ORDER BY p.create_at DESC")
    sql_parts.append("LIMIT ?")
    params.append(limit)

    sql = " ".join(sql_parts)

    conn = db.connect(db_path)
    try:
        rows = conn.execute(sql, params).fetchall()
    finally:
        conn.close()

    return [
        SearchHit(
            post_id=r["id"],
            channel_id=r["channel_id"],
            channel_name=r["channel_name"],
            channel_display_name=r["channel_display_name"],
            username=r["username"],
            create_at=r["create_at"],
            message=r["message"],
        )
        for r in rows
    ]


def get_post(post_id: str, *, db_path: Path | None = None) -> dict[str, Any] | None:
    """Look up a single post for the `open` command."""
    conn = db.connect(db_path)
    try:
        row = conn.execute(
            "SELECT p.id, p.channel_id, p.create_at, p.message, "
            "c.name AS channel_name, c.team_id, "
            "COALESCE(u.username, '(unknown)') AS username "
            "FROM posts p "
            "LEFT JOIN channels c ON p.channel_id = c.id "
            "LEFT JOIN users u ON p.user_id = u.id "
            "WHERE p.id = ?",
            (post_id,),
        ).fetchone()
    finally:
        conn.close()
    return dict(row) if row else None


def make_permalink(server_url: str, post_id: str) -> str:
    """Build a Mattermost permalink. `_redirect/pl/<id>` works without knowing team name."""
    return f"{server_url.rstrip('/')}/_redirect/pl/{post_id}"
