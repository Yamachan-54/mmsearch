"""Tests for database schema and FTS5 trigram tokenizer behavior.

Notes on FTS5 + trigram tokenizer for Japanese:
- The trigram tokenizer indexes 3-character sequences.
- `MATCH 'query'` requires 3+ characters; 1-2 char queries return no rows.
- For substring search of any length, use `LIKE '%query%'` against the FTS5
  table — SQLite accelerates this through the trigram index automatically.
- This is the query pattern P3 (`mmsearch search`) will use.
"""
from __future__ import annotations

import sqlite3
from pathlib import Path

from mmsearch import db


def _insert_posts(conn: sqlite3.Connection, rows: list[tuple]) -> None:
    conn.executemany(
        "INSERT INTO posts (id, channel_id, user_id, create_at, update_at, message) "
        "VALUES (?, ?, ?, ?, ?, ?)",
        rows,
    )
    conn.commit()


def test_init_db_creates_schema(tmp_path: Path) -> None:
    p = tmp_path / "test.db"
    db.init_db(p)
    conn = sqlite3.connect(p)
    try:
        tables = {
            r[0]
            for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")
        }
    finally:
        conn.close()
    assert {"channels", "users", "posts", "posts_fts"}.issubset(tables)


def test_fts5_like_japanese_2char_substring(tmp_path: Path) -> None:
    """2文字の日本語クエリでも LIKE で部分一致できる（trigram索引で加速）。"""
    p = tmp_path / "test.db"
    db.init_db(p)
    conn = sqlite3.connect(p)
    try:
        _insert_posts(
            conn,
            [
                ("p1", "c1", "u1", 1, 1, "今日は実装する"),
                ("p2", "c1", "u1", 2, 2, "再実装が必要"),
                ("p3", "c1", "u1", 3, 3, "完全に無関係なメッセージ"),
            ],
        )
        rows = conn.execute(
            "SELECT p.id FROM posts p "
            "JOIN posts_fts ON p.rowid = posts_fts.rowid "
            "WHERE posts_fts.message LIKE '%実装%' "
            "ORDER BY p.create_at"
        ).fetchall()
    finally:
        conn.close()
    assert [r[0] for r in rows] == ["p1", "p2"]


def test_fts5_match_3char_word(tmp_path: Path) -> None:
    """3文字以上のクエリは MATCH も動作する（より高速・関連度スコア取得可）。"""
    p = tmp_path / "test.db"
    db.init_db(p)
    conn = sqlite3.connect(p)
    try:
        _insert_posts(
            conn,
            [
                ("p1", "c1", "u1", 1, 1, "今日は実装する"),
                ("p2", "c1", "u1", 2, 2, "再実装が必要"),
            ],
        )
        rows = conn.execute(
            "SELECT p.id FROM posts p "
            "JOIN posts_fts ON p.rowid = posts_fts.rowid "
            "WHERE posts_fts MATCH '再実装'"
        ).fetchall()
    finally:
        conn.close()
    assert [r[0] for r in rows] == ["p2"]


def test_fts5_update_reflects_in_index(tmp_path: Path) -> None:
    """UPDATE トリガで FTS インデックスが追従することを確認。"""
    p = tmp_path / "test.db"
    db.init_db(p)
    conn = sqlite3.connect(p)
    try:
        _insert_posts(conn, [("p1", "c1", "u1", 1, 1, "before")])
        conn.execute("UPDATE posts SET message = 'after実装' WHERE id = 'p1'")
        conn.commit()
        rows = conn.execute(
            "SELECT p.id FROM posts p "
            "JOIN posts_fts ON p.rowid = posts_fts.rowid "
            "WHERE posts_fts.message LIKE '%実装%'"
        ).fetchall()
    finally:
        conn.close()
    assert [r[0] for r in rows] == ["p1"]


def test_init_db_is_idempotent(tmp_path: Path) -> None:
    p = tmp_path / "test.db"
    db.init_db(p)
    db.init_db(p)
