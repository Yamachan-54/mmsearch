"""Mattermost の投稿をローカル SQLite に同期するエンジン。"""
from __future__ import annotations

import sqlite3
import time
from collections.abc import Callable
from typing import Any

from . import client as mm_client
from . import config as config_mod

# 1ページあたりの取得件数。Mattermost のデフォルト上限と整合させた値
PER_PAGE = 200

# ページ間の待機時間。サーバのレートリミット（一般的に 10req/s）に
# 余裕を持たせる
RATE_LIMIT_DELAY = 0.1

# チャンネル単位の上限ページ数。暴走防止の安全装置として用意。
# 200件 × 5000ページ ≒ 100万投稿まで取得可能で、現実的に十分な値
MAX_PAGES_PER_CHANNEL = 5000

# 差分同期で `since` パラメータに渡す際のオーバーラップ幅（ミリ秒）。
# 1秒の境界をまたぐ投稿が取りこぼされるのを防ぐため、最後の同期時刻から
# 1秒だけ遡って再取得する（同じ投稿は ON CONFLICT で上書きされるので無害）
SINCE_OVERLAP_MS = 1000

OnProgress = Callable[[int], None]


def fetch_channels(
    client: mm_client.MattermostClient, cfg: config_mod.Config
) -> list[dict[str, Any]]:
    """同期対象のチャンネル一覧を返す。

    `cfg.sync_channel_ids` が指定されていれば、そのIDに含まれるものだけに絞る。
    指定がなければ自分が参加している全チャンネルが対象。
    """
    channels = client.my_channels(cfg.team_id)
    if cfg.sync_channel_ids:
        wanted = set(cfg.sync_channel_ids)
        channels = [c for c in channels if c["id"] in wanted]
    return channels


def upsert_channel(conn: sqlite3.Connection, ch: dict[str, Any]) -> None:
    # `last_synced_at` は INSERT 時のみ 0 で初期化し、UPDATE 時は触らない。
    # チャンネル名変更などで再 upsert された場合に同期進捗が失われないようにするため。
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
    """投稿を upsert する。処理した件数を返す。"""
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
    # Mattermost では投稿の編集が許可されている場合があり、その場合 update_at と
    # message が変わる。再取得時に差分を反映するため ON CONFLICT で更新している
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
    """投稿者情報をDBに揃える。

    2段階キャッシュで API 呼び出しを最小化する設計:
    - `cache` (プロセス内 set): 同一 sync 実行中の重複呼び出しを防ぐ
    - DB の users テーブル: 既知ユーザーは API を再度叩かずスキップ
    """
    todo = user_ids - cache
    if not todo:
        return
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
            # 削除済みユーザー等で取得に失敗した場合は、無限リトライを避けるため
            # プレースホルダ値で記録しておく
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
    """1チャンネル分の同期を行う。upsert された投稿数を返す。"""
    user_cache = user_cache if user_cache is not None else set()
    channel_id = channel["id"]

    row = conn.execute(
        "SELECT last_synced_at FROM channels WHERE id = ?", (channel_id,)
    ).fetchone()
    last_synced = (row[0] if row else 0) if not full else 0

    total = 0
    max_create_at = last_synced

    if last_synced > 0:
        # 差分同期: ?since=<ms> で最終同期以降の投稿を取得
        # API は1リクエストで最大 ~1000 件返すため、通常はページングなしで済む
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
        # フル同期: 新しい順にページネーションで取得
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
            # `posts` 辞書はスレッドの親投稿も含むため `order` よりも要素数が多くなりうる。
            # 終端判定は実際のページ件数を表す `order` の長さで行う必要がある。
            if len(order) < PER_PAGE:
                break
            sleep(RATE_LIMIT_DELAY)

    if max_create_at > last_synced:
        conn.execute(
            "UPDATE channels SET last_synced_at = ? WHERE id = ?",
            (max_create_at, channel_id),
        )
    return total
