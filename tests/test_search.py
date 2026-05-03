"""ローカル検索のテスト。"""
from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from mmsearch import db, search


def _populate(conn: sqlite3.Connection) -> None:
    conn.executemany(
        "INSERT INTO channels (id, team_id, name, display_name, type, last_synced_at) "
        "VALUES (?, ?, ?, ?, ?, ?)",
        [
            ("c1", "t1", "general", "General", "O", 0),
            ("c2", "t1", "random", "Random", "O", 0),
            ("c3", "t1", "課題質問", "課題-質問", "O", 0),
        ],
    )
    conn.executemany(
        "INSERT INTO users (id, username, nickname) VALUES (?, ?, ?)",
        [
            ("u1", "alice", "Alice"),
            ("u2", "bob", "Bob"),
        ],
    )
    conn.executemany(
        "INSERT INTO posts (id, channel_id, user_id, create_at, update_at, message) "
        "VALUES (?, ?, ?, ?, ?, ?)",
        [
            ("p1", "c1", "u1", 1_700_000_000_000, 1_700_000_000_000, "今日は実装する"),
            ("p2", "c1", "u2", 1_700_000_100_000, 1_700_000_100_000, "再実装が必要"),
            ("p3", "c2", "u1", 1_700_000_200_000, 1_700_000_200_000, "雑談スレッド"),
            ("p4", "c3", "u2", 1_700_000_300_000, 1_700_000_300_000, "宿題の実装が分からない"),
            ("p5", "c1", "u1", 1_700_001_000_000, 1_700_001_000_000, "100% complete!"),
        ],
    )
    conn.commit()


@pytest.fixture
def db_path(tmp_path: Path) -> Path:
    p = tmp_path / "test.db"
    db.init_db(p)
    conn = db.connect(p)
    _populate(conn)
    conn.close()
    return p


def test_search_japanese_2char(db_path: Path) -> None:
    hits = search.search("実装", db_path=db_path)
    ids = {h.post_id for h in hits}
    assert ids == {"p1", "p2", "p4"}


def test_search_results_ordered_newest_first(db_path: Path) -> None:
    hits = search.search("実装", db_path=db_path)
    assert [h.post_id for h in hits] == ["p4", "p2", "p1"]


def test_search_filter_channel_partial(db_path: Path) -> None:
    hits = search.search("実装", channel="general", db_path=db_path)
    assert {h.post_id for h in hits} == {"p1", "p2"}


def test_search_filter_channel_japanese(db_path: Path) -> None:
    hits = search.search("実装", channel="課題", db_path=db_path)
    assert {h.post_id for h in hits} == {"p4"}


def test_search_filter_user(db_path: Path) -> None:
    hits = search.search("実装", user="alice", db_path=db_path)
    assert {h.post_id for h in hits} == {"p1"}


def test_search_filter_since(db_path: Path) -> None:
    # 各投稿の create_at（ミリ秒エポック）と対応するUTC日時:
    # p1: 1_700_000_000_000 = 2023-11-14T22:13:20Z
    # p2: 1_700_000_100_000 = 2023-11-14T22:15:00Z
    # p4: 1_700_000_300_000 = 2023-11-14T22:18:20Z
    hits = search.search("実装", since="2023-11-14T22:14", db_path=db_path)
    assert {h.post_id for h in hits} == {"p2", "p4"}


def test_search_filter_until(db_path: Path) -> None:
    hits = search.search(
        "実装", until="2023-11-14T22:14", db_path=db_path
    )
    assert {h.post_id for h in hits} == {"p1"}


def test_search_filter_invalid_date_raises(db_path: Path) -> None:
    with pytest.raises(ValueError, match="invalid date"):
        search.search("実装", since="not-a-date", db_path=db_path)


def test_search_limit(db_path: Path) -> None:
    hits = search.search("実装", limit=2, db_path=db_path)
    assert len(hits) == 2


def test_search_default_limit_is_100(db_path: Path) -> None:
    """デフォルト件数は 100 件。"""
    assert search.DEFAULT_LIMIT == 100


def test_search_limit_none_returns_all(db_path: Path) -> None:
    """limit=None を渡すと LIMIT 句が発行されず、全件返る（CLI の --all 用）。"""
    hits = search.search("実装", limit=None, db_path=db_path)
    assert {h.post_id for h in hits} == {"p1", "p2", "p4"}


def test_search_empty_query(db_path: Path) -> None:
    assert search.search("", db_path=db_path) == []
    assert search.search("   ", db_path=db_path) == []


def test_search_like_special_chars_escaped(db_path: Path) -> None:
    """`%` をクエリに含めても LIKE のワイルドカードとして展開されないこと。"""
    hits = search.search("100%", db_path=db_path)
    assert {h.post_id for h in hits} == {"p5"}


def test_search_no_match_returns_empty(db_path: Path) -> None:
    hits = search.search("そんな投稿はない", db_path=db_path)
    assert hits == []


def test_get_post(db_path: Path) -> None:
    p = search.get_post("p1", db_path=db_path)
    assert p is not None
    assert p["message"] == "今日は実装する"
    assert p["username"] == "alice"
    assert p["channel_name"] == "general"


def test_get_post_missing(db_path: Path) -> None:
    assert search.get_post("does-not-exist", db_path=db_path) is None


def test_make_permalink() -> None:
    assert (
        search.make_permalink("https://mm.example.com", "abc123")
        == "https://mm.example.com/_redirect/pl/abc123"
    )
    # URL末尾のスラッシュは正規化される
    assert (
        search.make_permalink("https://mm.example.com/", "abc123")
        == "https://mm.example.com/_redirect/pl/abc123"
    )
