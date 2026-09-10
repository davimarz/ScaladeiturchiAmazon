"""Shared Creators API budget and pacing.

Redis is used when REDIS_URL is configured, which lets multiple application
instances share the same counters. A local SQLite fallback remains available
for single-instance deployments and development.
"""
from __future__ import annotations

import json
import os
import sqlite3
import time
from datetime import datetime, timezone
from pathlib import Path

try:
    import redis
except ImportError:  # pragma: no cover
    redis = None

DB_PATH = Path(os.getenv("SCALA_STATE_DB", "").strip() or (Path(__file__).resolve().parent / ".runtime" / "api_usage.sqlite3"))


class BudgetUnavailable(RuntimeError):
    pass


def _day() -> str:
    return datetime.now(timezone.utc).date().isoformat()


def _connect():
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(DB_PATH), timeout=5, isolation_level=None)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA busy_timeout=5000")
    conn.execute("CREATE TABLE IF NOT EXISTS usage (day TEXT PRIMARY KEY, calls INTEGER NOT NULL)")
    conn.execute("CREATE TABLE IF NOT EXISTS pacing (id INTEGER PRIMARY KEY, next_at REAL NOT NULL)")
    return conn


def _redis_client():
    url = os.getenv("REDIS_URL", "").strip()
    if not url or redis is None:
        return None
    return redis.Redis.from_url(url, decode_responses=True, socket_timeout=3, socket_connect_timeout=3)


def _usage_redis(limit: int) -> dict:
    client = _redis_client()
    if client is None:
        raise BudgetUnavailable("Redis non disponibile")
    day = _day()
    used = int(client.get(f"scala:api:usage:{day}") or 0)
    return {"day_utc": day, "calls": used, "limit": limit, "remaining": max(0, limit - used), "backend": "redis"}


def _usage_sqlite(limit: int) -> dict:
    try:
        conn = _connect()
        try:
            row = conn.execute("SELECT calls FROM usage WHERE day=?", (_day(),)).fetchone()
        finally:
            conn.close()
        used = row[0] if row else 0
        return {"day_utc": _day(), "calls": used, "limit": limit, "remaining": max(0, limit - used), "backend": "sqlite"}
    except (OSError, sqlite3.Error) as exc:
        raise BudgetUnavailable("Contatore richieste non disponibile") from exc


def usage(limit: int = 800) -> dict:
    if os.getenv("REDIS_URL", "").strip():
        try:
            return _usage_redis(limit)
        except Exception:
            pass
    return _usage_sqlite(limit)


def _reserve_redis(limit: int, interval: float, max_wait: float) -> None:
    client = _redis_client()
    if client is None:
        raise BudgetUnavailable("Redis non disponibile")
    deadline = time.monotonic() + max_wait
    day = _day()
    usage_key = f"scala:api:usage:{day}"
    pacing_key = "scala:api:pacing"
    lock = client.lock("scala:api:reserve:lock", timeout=max(5, int(max_wait) + 2), blocking_timeout=max_wait)
    while True:
        with lock:
            used = int(client.get(usage_key) or 0)
            if used >= limit:
                raise BudgetUnavailable("Budget giornaliero raggiunto")
            now = time.time()
            next_at = float(client.get(pacing_key) or 0)
            wait = max(0.0, next_at - now)
            if wait <= 0:
                pipe = client.pipeline(transaction=True)
                pipe.incr(usage_key, 1)
                pipe.expire(usage_key, 3 * 24 * 60 * 60)
                pipe.set(pacing_key, now + interval, ex=max(2, int(interval) + 2))
                pipe.execute()
                return
        if time.monotonic() + wait > deadline:
            raise BudgetUnavailable("Ricerca occupata, riprova tra qualche secondo")
        time.sleep(min(wait, 0.25))


def _reserve_sqlite(limit: int, interval: float, max_wait: float) -> None:
    deadline = time.monotonic() + max_wait
    while True:
        try:
            conn = _connect()
            try:
                conn.execute("BEGIN IMMEDIATE")
                day = _day()
                row = conn.execute("SELECT calls FROM usage WHERE day=?", (day,)).fetchone()
                used = row[0] if row else 0
                if used >= limit:
                    raise BudgetUnavailable("Budget giornaliero raggiunto")
                row = conn.execute("SELECT next_at FROM pacing WHERE id=1").fetchone()
                wait = max(0.0, (row[0] if row else 0) - time.time())
                if wait <= 0:
                    conn.execute(
                        "INSERT INTO usage(day,calls) VALUES (?,1) ON CONFLICT(day) DO UPDATE SET calls=calls+1",
                        (day,),
                    )
                    conn.execute("INSERT OR REPLACE INTO pacing VALUES (1,?)", (time.time() + interval,))
                    conn.commit()
                    return
                conn.rollback()
            finally:
                conn.close()
        except BudgetUnavailable:
            raise
        except (OSError, sqlite3.Error) as exc:
            raise BudgetUnavailable("Contatore richieste non disponibile") from exc
        if time.monotonic() + wait > deadline:
            raise BudgetUnavailable("Ricerca occupata, riprova tra qualche secondo")
        time.sleep(min(wait, 0.25))


def reserve(limit: int = 800, interval: float = 1.1, max_wait: float = 5) -> None:
    limit = max(0, int(limit))
    interval = max(0.1, float(interval))
    if limit <= 0:
        raise BudgetUnavailable("Budget giornaliero disabilitato")
    if os.getenv("REDIS_URL", "").strip():
        try:
            _reserve_redis(limit, interval, max_wait)
            return
        except BudgetUnavailable:
            raise
        except Exception:
            # Fallback keeps a single-instance deployment usable if Redis is down.
            pass
    _reserve_sqlite(limit, interval, max_wait)


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser()
    parser.add_argument("--limit", type=int, default=800)
    print(json.dumps(usage(parser.parse_args().limit), indent=2))
