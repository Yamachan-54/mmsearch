"""SQLite データベース層。日本語検索のため FTS5 trigram tokenizer を使用する。

trigram tokenizer を選ぶ理由:
- 標準ビルドの SQLite に含まれており、追加のネイティブ依存が不要
- 3文字単位で索引を張るため、`LIKE '%query%'` が trigram 索引で加速される
- 形態素解析（MeCab/Lindera 等）と異なり、単語境界を持たない日本語でも
  「実装」「再実装」「実装する」のような部分一致が自然に動く

注意:
- `MATCH` クエリは2文字以下のトークンを索引と照合できない（FTS5 仕様）。
  検索層 (search.py) は `LIKE '%query%'` を使うことでこの制限を回避している。
- `posts_fts` は外部コンテンツテーブル方式（content='posts'）を使用。
  本体テーブルへの INSERT/UPDATE/DELETE と同期させるためトリガが必須。
"""
from __future__ import annotations

import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

from . import config

SCHEMA = """
CREATE TABLE IF NOT EXISTS channels (
    id TEXT PRIMARY KEY,
    team_id TEXT NOT NULL,
    name TEXT NOT NULL,
    display_name TEXT NOT NULL,
    type TEXT NOT NULL,
    last_synced_at INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS users (
    id TEXT PRIMARY KEY,
    username TEXT NOT NULL,
    nickname TEXT
);

CREATE TABLE IF NOT EXISTS posts (
    id TEXT PRIMARY KEY,
    channel_id TEXT NOT NULL,
    user_id TEXT NOT NULL,
    create_at INTEGER NOT NULL,
    update_at INTEGER NOT NULL,
    root_id TEXT,
    message TEXT NOT NULL,
    raw_json TEXT
);

CREATE INDEX IF NOT EXISTS idx_posts_channel_create ON posts(channel_id, create_at DESC);
CREATE INDEX IF NOT EXISTS idx_posts_user ON posts(user_id);
CREATE INDEX IF NOT EXISTS idx_posts_root ON posts(root_id);

CREATE VIRTUAL TABLE IF NOT EXISTS posts_fts USING fts5(
    message,
    content='posts',
    content_rowid='rowid',
    tokenize='trigram'
);

-- 外部コンテンツ FTS5 は本体テーブル変更を自動追従しないため、トリガで同期する
CREATE TRIGGER IF NOT EXISTS posts_ai AFTER INSERT ON posts BEGIN
    INSERT INTO posts_fts(rowid, message) VALUES (new.rowid, new.message);
END;

CREATE TRIGGER IF NOT EXISTS posts_ad AFTER DELETE ON posts BEGIN
    INSERT INTO posts_fts(posts_fts, rowid, message) VALUES('delete', old.rowid, old.message);
END;

CREATE TRIGGER IF NOT EXISTS posts_au AFTER UPDATE ON posts BEGIN
    INSERT INTO posts_fts(posts_fts, rowid, message) VALUES('delete', old.rowid, old.message);
    INSERT INTO posts_fts(rowid, message) VALUES (new.rowid, new.message);
END;
"""


def connect(path: Path | None = None) -> sqlite3.Connection:
    db = path or config.db_path()
    conn = sqlite3.connect(db)
    conn.row_factory = sqlite3.Row
    # WAL モード: 書き込み中も読み取りがブロックされないため、
    # sync 中に search を走らせても応答性が落ちない
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


def init_db(path: Path | None = None) -> None:
    """スキーマを作成する。すでに存在する場合は何もしない（冪等）。"""
    conn = connect(path)
    try:
        conn.executescript(SCHEMA)
        conn.commit()
    finally:
        conn.close()


@contextmanager
def transaction(path: Path | None = None) -> Iterator[sqlite3.Connection]:
    conn = connect(path)
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()
