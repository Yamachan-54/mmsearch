"""Tests for sync engine using mocked Mattermost API."""
from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from mmsearch import client as mm_client
from mmsearch import db, sync

BASE = "https://mm.example.com"


@pytest.fixture
def conn(tmp_path: Path) -> sqlite3.Connection:
    p = tmp_path / "test.db"
    db.init_db(p)
    c = db.connect(p)
    yield c
    c.close()


@pytest.fixture
def client() -> mm_client.MattermostClient:
    return mm_client.MattermostClient(BASE, "fake-token")


def _ch(id_: str = "c1", name: str = "general") -> dict:
    return {
        "id": id_,
        "team_id": "t1",
        "name": name,
        "display_name": name.title(),
        "type": "O",
    }


def _post(pid: str, channel: str, user: str, msg: str, ts: int) -> dict:
    return {
        "id": pid,
        "channel_id": channel,
        "user_id": user,
        "create_at": ts,
        "update_at": ts,
        "root_id": "",
        "message": msg,
    }


def test_upsert_channel_idempotent(conn: sqlite3.Connection) -> None:
    sync.upsert_channel(conn, _ch())
    sync.upsert_channel(conn, _ch())  # second call should not error
    rows = conn.execute("SELECT id, name FROM channels").fetchall()
    assert len(rows) == 1
    assert rows[0][1] == "general"


def test_upsert_channel_preserves_last_synced(conn: sqlite3.Connection) -> None:
    sync.upsert_channel(conn, _ch())
    conn.execute("UPDATE channels SET last_synced_at = 12345 WHERE id = 'c1'")
    conn.commit()
    # Update channel meta — last_synced_at must NOT be reset
    sync.upsert_channel(conn, _ch(name="general-renamed"))
    row = conn.execute(
        "SELECT name, display_name, last_synced_at FROM channels WHERE id = 'c1'"
    ).fetchone()
    assert row[0] == "general-renamed"
    assert row[1] == "General-Renamed"
    assert row[2] == 12345


def test_sync_channel_full_paginates(
    conn: sqlite3.Connection, httpx_mock, client: mm_client.MattermostClient
) -> None:
    sync.upsert_channel(conn, _ch())

    # Page 0: full page (200 posts simulated as 2 to keep test fast,
    # so we set per_page to 2 via monkeypatch below isn't needed — we mock pagination
    # by returning a "full" page (== PER_PAGE) followed by a partial page)
    # Easier: use monkeypatched PER_PAGE
    posts_p0 = {f"p{i}": _post(f"p{i}", "c1", "u1", f"msg{i}", 1000 + i) for i in range(2)}
    posts_p1 = {f"p{i}": _post(f"p{i}", "c1", "u1", f"msg{i}", 900 + i) for i in range(2, 4)}
    posts_p2: dict = {}

    httpx_mock.add_response(
        url=f"{BASE}/api/v4/channels/c1/posts?page=0&per_page=2",
        json={"order": list(posts_p0), "posts": posts_p0},
    )
    httpx_mock.add_response(
        url=f"{BASE}/api/v4/channels/c1/posts?page=1&per_page=2",
        json={"order": list(posts_p1), "posts": posts_p1},
    )
    httpx_mock.add_response(
        url=f"{BASE}/api/v4/channels/c1/posts?page=2&per_page=2",
        json={"order": [], "posts": posts_p2},
    )
    httpx_mock.add_response(
        url=f"{BASE}/api/v4/users/u1",
        json={"id": "u1", "username": "alice", "nickname": "A"},
    )

    # Patch PER_PAGE for this test
    orig = sync.PER_PAGE
    sync.PER_PAGE = 2
    try:
        n = sync.sync_channel(
            conn,
            client,
            _ch(),
            full=True,
            sleep=lambda _: None,
        )
    finally:
        sync.PER_PAGE = orig

    assert n == 4
    rows = conn.execute("SELECT id FROM posts ORDER BY id").fetchall()
    assert [r[0] for r in rows] == ["p0", "p1", "p2", "p3"]
    # last_synced_at should equal max create_at = 1001
    last = conn.execute(
        "SELECT last_synced_at FROM channels WHERE id = 'c1'"
    ).fetchone()[0]
    assert last == 1001
    # User was upserted
    u = conn.execute("SELECT username FROM users WHERE id = 'u1'").fetchone()
    assert u[0] == "alice"


def test_sync_channel_incremental_uses_since(
    conn: sqlite3.Connection, httpx_mock, client: mm_client.MattermostClient
) -> None:
    sync.upsert_channel(conn, _ch())
    conn.execute("UPDATE channels SET last_synced_at = 5000 WHERE id = 'c1'")
    conn.commit()

    new_posts = {"pNew": _post("pNew", "c1", "u1", "新着", 6000)}
    httpx_mock.add_response(
        # since = 5000 - SINCE_OVERLAP_MS = 4000
        url=f"{BASE}/api/v4/channels/c1/posts?page=0&per_page={sync.PER_PAGE}&since=4000",
        json={"order": ["pNew"], "posts": new_posts},
    )
    httpx_mock.add_response(
        url=f"{BASE}/api/v4/users/u1",
        json={"id": "u1", "username": "alice"},
    )

    n = sync.sync_channel(conn, client, _ch(), full=False, sleep=lambda _: None)
    assert n == 1
    last = conn.execute(
        "SELECT last_synced_at FROM channels WHERE id = 'c1'"
    ).fetchone()[0]
    assert last == 6000


def test_fetch_channels_filter_applies(
    httpx_mock, client: mm_client.MattermostClient
) -> None:
    from mmsearch import config as config_mod

    httpx_mock.add_response(
        url=f"{BASE}/api/v4/users/me/teams/t1/channels",
        json=[_ch("c1", "general"), _ch("c2", "random"), _ch("c3", "off-topic")],
    )
    cfg = config_mod.Config(server_url=BASE, team_id="t1", sync_channel_ids=["c1", "c3"])
    out = sync.fetch_channels(client, cfg)
    assert {c["id"] for c in out} == {"c1", "c3"}


def test_ensure_users_skips_existing(
    conn: sqlite3.Connection, httpx_mock, client: mm_client.MattermostClient
) -> None:
    # Pre-populate one user
    conn.execute("INSERT INTO users (id, username) VALUES ('u1', 'alice')")
    conn.commit()

    httpx_mock.add_response(
        url=f"{BASE}/api/v4/users/u2",
        json={"id": "u2", "username": "bob"},
    )

    cache: set[str] = set()
    sync._ensure_users(conn, client, {"u1", "u2"}, cache)
    # u1 should not have triggered an HTTP call (only u2 mocked); pytest-httpx fails
    # if unmatched calls occur, so the test's existence proves it.
    rows = sorted(r[0] for r in conn.execute("SELECT username FROM users"))
    assert rows == ["alice", "bob"]
