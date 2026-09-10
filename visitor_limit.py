"""Rolling-hour browser allowance with privacy-preserving identifiers.

Uses Redis when REDIS_URL is configured, otherwise falls back to the local
SQLite store used by api_budget. Redis makes the limiter suitable for multiple
application instances.
"""
from __future__ import annotations

import hashlib
import os
import time

import api_budget

try:
    import redis
except ImportError:  # pragma: no cover - optional at runtime
    redis = None

_WINDOW_SECONDS = 3600


def _visitor_key(visitor: str) -> str:
    clean = str(visitor or "").strip()
    if not clean:
        raise ValueError("visitor id required")
    return hashlib.sha256(clean.encode("utf-8")).hexdigest()


def _redis_client():
    url = os.getenv("REDIS_URL", "").strip()
    if not url or redis is None:
        return None
    return redis.Redis.from_url(url, decode_responses=True, socket_timeout=3, socket_connect_timeout=3)


def _check_redis(visitor: str, limit: int, consume: bool) -> dict:
    client = _redis_client()
    if client is None:
        raise RuntimeError("redis unavailable")
    now = time.time()
    key = f"scala:visitor:{_visitor_key(visitor)}"
    lock = client.lock(f"{key}:lock", timeout=5, blocking_timeout=3)
    with lock:
        client.zremrangebyscore(key, 0, now - _WINDOW_SECONDS)
        count = int(client.zcard(key))
        allowed = count < limit
        if consume and allowed:
            member = f"{now:.6f}:{time.time_ns()}"
            client.zadd(key, {member: now})
            count += 1
        client.expire(key, _WINDOW_SECONDS + 120)
        first = client.zrange(key, 0, 0, withscores=True)
    retry_at = float(first[0][1]) + _WINDOW_SECONDS if count >= limit and first else 0
    return {"allowed": allowed, "remaining": max(0, limit - count), "retry_at": retry_at}


def _check_sqlite(visitor: str, limit: int, consume: bool) -> dict:
    visitor_hash = _visitor_key(visitor)
    conn = api_budget._connect()
    try:
        conn.execute("CREATE TABLE IF NOT EXISTS browser_searches (visitor TEXT, at REAL)")
        conn.execute("CREATE INDEX IF NOT EXISTS browser_search_idx ON browser_searches(visitor, at)")
        conn.execute("CREATE INDEX IF NOT EXISTS browser_search_time ON browser_searches(at)")
        conn.execute("BEGIN IMMEDIATE")
        now = time.time()
        conn.execute("DELETE FROM browser_searches WHERE at <= ?", (now - _WINDOW_SECONDS,))
        rows = conn.execute(
            "SELECT at FROM browser_searches WHERE visitor=? ORDER BY at", (visitor_hash,)
        ).fetchall()
        allowed = len(rows) < limit
        if consume and allowed:
            conn.execute("INSERT INTO browser_searches VALUES (?,?)", (visitor_hash, now))
            rows.append((now,))
        conn.commit()
        return {
            "allowed": allowed,
            "remaining": max(0, limit - len(rows)),
            "retry_at": rows[0][0] + _WINDOW_SECONDS if len(rows) >= limit else 0,
        }
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def check(visitor: str, limit: int = 10, consume: bool = False) -> dict:
    limit = max(1, int(limit))
    if os.getenv("REDIS_URL", "").strip():
        try:
            return _check_redis(visitor, limit, consume)
        except Exception:
            # Fail closed only if there is no usable local fallback.
            return _check_sqlite(visitor, limit, consume)
    return _check_sqlite(visitor, limit, consume)
