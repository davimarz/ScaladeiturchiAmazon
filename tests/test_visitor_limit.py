from __future__ import annotations

import api_budget
import visitor_limit


def test_sqlite_limit_is_rolling_and_hashed(tmp_path, monkeypatch):
    monkeypatch.delenv("REDIS_URL", raising=False)
    monkeypatch.delenv("STRICT_REDIS", raising=False)
    monkeypatch.setenv("VISITOR_HASH_SECRET", "unit-test-secret")
    monkeypatch.setattr(api_budget, "DB_PATH", tmp_path / "state.sqlite3")
    visitor = "123e4567-e89b-12d3-a456-426614174000"

    first = visitor_limit.check(visitor, limit=2, consume=True)
    second = visitor_limit.check(visitor, limit=2, consume=True)
    blocked = visitor_limit.check(visitor, limit=2, consume=False)

    assert first["allowed"] is True and first["remaining"] == 1
    assert second["allowed"] is True and second["remaining"] == 0
    assert blocked["allowed"] is False and blocked["remaining"] == 0
    assert blocked["backend"] == "sqlite"

    conn = api_budget._connect()
    try:
        rows = conn.execute("SELECT visitor FROM browser_searches").fetchall()
    finally:
        conn.close()
    assert rows
    assert all(row[0] != visitor for row in rows)


def test_hmac_key_changes_with_secret(monkeypatch):
    visitor = "123e4567-e89b-12d3-a456-426614174000"
    monkeypatch.setenv("VISITOR_HASH_SECRET", "secret-one")
    first = visitor_limit._visitor_key(visitor)
    monkeypatch.setenv("VISITOR_HASH_SECRET", "secret-two")
    second = visitor_limit._visitor_key(visitor)
    assert first != second
    assert len(first) == len(second) == 64


def test_strict_redis_fails_closed_without_url(monkeypatch):
    monkeypatch.delenv("REDIS_URL", raising=False)
    monkeypatch.setenv("STRICT_REDIS", "1")
    try:
        visitor_limit.check("123e4567-e89b-12d3-a456-426614174000", limit=2)
    except RuntimeError:
        pass
    else:
        raise AssertionError("STRICT_REDIS must fail closed without REDIS_URL")
