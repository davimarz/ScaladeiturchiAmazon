from __future__ import annotations

import os

import pytest

import shared_results


def test_redis_cache_round_trip(monkeypatch):
    if not os.getenv("REDIS_URL"):
        pytest.skip("REDIS_URL not configured")
    monkeypatch.setenv("SCALA_SHARED_CACHE_REDIS", "1")
    key = ("test-cache", "round-trip")
    client = shared_results._redis_client()
    client.delete(shared_results._redis_key(key))
    calls = {"count": 0}

    def loader():
        calls["count"] += 1
        return [{"asin": "B000000001", "prezzo_finale": 10.0, "prezzo_verificato": True}]

    first = shared_results.get(key, 30, loader)
    # Remove local cache to force Redis on the second read.
    with shared_results._lock:
        shared_results._entries.pop(key, None)
    second = shared_results.get(key, 30, loader)
    assert first == second
    assert calls["count"] == 1
