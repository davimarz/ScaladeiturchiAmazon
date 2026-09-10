from __future__ import annotations

import os

import api_budget
import visitor_limit


def test_sqlite_limit_is_rolling_and_hashed(tmp_path, monkeypatch):
    monkeypatch.delenv("REDIS_URL", raising=False)
    monkeypatch.setattr(api_budget, "DB_PATH", tmp_path / "state.sqlite3")
    visitor = "123e4567-e89b-12d3-a456-426614174000"

    first = visitor_limit.check(visitor, limit=2, consume=True)
    second = visitor_limit.check(visitor, limit=2, consume=True)
    blocked = visitor_limit.check(visitor, limit=2, consume=False)

    assert first["allowed"] is True and first["remaining"] == 1
    assert second["allowed"] is True and second["remaining"] == 0
    assert blocked["allowed"] is False and blocked["remaining"] == 0

    conn = api_budget._connect()
    try:
        rows = conn.execute("SELECT visitor FROM browser_searches").fetchall()
    finally:
        conn.close()
    assert rows
    assert all(row[0] != visitor for row in rows)
