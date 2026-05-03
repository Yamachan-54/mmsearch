"""ローカルDBに対する全文検索層。

検索クエリには `LIKE '%query%'` を使う。`MATCH` ではなく `LIKE` を選ぶ理由:

- FTS5 の `MATCH` は2文字以下のトークンを索引と照合できない（仕様）。
  日本語の2文字キーワード（例: 「朝活」「実装」）が必須要件のためこれは致命的。
- 一方 `posts_fts.message LIKE '%query%'` は trigram 索引で加速されるため、
  任意長クエリで十分な速度が出る。日本語2文字でも動く。

フィルタ条件: チャンネル / ユーザー / 日付範囲 / 件数 を組み合わせて利用可能。
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
    create_at: int  # ミリ秒エポック（Mattermost API の精度に合わせる）
    message: str


# CLI のデフォルト件数。100 件あれば多くのケースで足りるが、
# 大量ヒット時は警告表示と --all フラグで補完する設計（PR #1）。
DEFAULT_LIMIT = 100


def _like_escape(s: str) -> str:
    """LIKE のワイルドカード文字をエスケープする。SQL 側で `ESCAPE '\\'` と組で使う。"""
    return s.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


def _parse_date(s: str) -> int:
    """ISO 形式の日付/日時文字列をミリ秒エポックに変換する。
    タイムゾーン未指定の場合は UTC として解釈する。
    """
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
    limit: int | None = DEFAULT_LIMIT,
    db_path: Path | None = None,
) -> list[SearchHit]:
    """投稿を検索する。

    - `channel` はチャンネル名 / display_name 両方に対する部分一致
    - `user` は username の完全一致
    - `limit=None` は LIMIT 句を発行せず全件返す（CLI の --all 用）
    """
    if not query.strip():
        return []
    if limit is not None and limit <= 0:
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
    if limit is not None:
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
    """単一の投稿を取得する（`mmsearch open` 等で使う）。"""
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
    """Mattermost のパーマリンクを生成する。

    `_redirect/pl/<post_id>` 形式はチーム名を知らなくてもサーバ側で正しい
    投稿にリダイレクトしてくれるため、こちらを採用している。
    """
    return f"{server_url.rstrip('/')}/_redirect/pl/{post_id}"
