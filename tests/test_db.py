"""データベーススキーマと FTS5 trigram tokenizer の動作テスト。

trigram tokenizer + 日本語の挙動メモ:
- trigram tokenizer は3文字単位で索引を張る
- `MATCH 'query'` は3文字以上のクエリが必要。1〜2文字では何もヒットしない
- 任意長の部分一致検索には FTS5 テーブルに対して `LIKE '%query%'` を使う。
  SQLite は trigram 索引を自動的に活用してくれる
- 検索コマンド (mmsearch search) はこの `LIKE` パターンを採用している
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
    """3文字以上のクエリは MATCH でもヒットする（参考: 関連度スコアを取りたい場合に使う）。"""
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
