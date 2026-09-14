from __future__ import annotations

import os
import time

import pytest

import shared_results


def test_redis_cache_round_trip(monkeypatch):
    if not os.getenv("REDIS_URL"):
        pytest.skip("REDIS_URL not configured")
    monkeypatch.setenv("SCALA_SHARED_CACHE_REDIS", "1")
    key = ("test-cache", "round-trip")
    client = shared_results._redis_client()
    client.delete(shared_results._redis_key(key, "fresh"))
    client.delete(shared_results._redis_key(key, "stale"))
    calls = {"count": 0}

    def loader():
        calls["count"] += 1
        return [{"asin": "B000000001", "prezzo_finale": 10.0, "prezzo_verificato": True}]

    first = shared_results.get(key, 30, loader)
    with shared_results._lock:
        shared_results._entries.pop(key, None)
    second = shared_results.get(key, 30, loader)
    assert first == second
    assert calls["count"] == 1


def test_loader_failure_returns_memory_stale_even_when_report_failure_is_true(monkeypatch):
    monkeypatch.delenv("REDIS_URL", raising=False)
    key = ("stale", time.time_ns())
    with shared_results._lock:
        shared_results._entries[key] = {
            "data": [{"asin": "B000000002", "prezzo_finale": 20.0, "prezzo_verificato": True}],
            "expires": time.time() - 1,
            "retry_at": 0,
        }

    def broken_loader():
        raise RuntimeError("temporary failure")

    result = shared_results.get(
        key,
        ttl=30,
        loader=broken_loader,
        retry=30,
        stale_for=60,
        report_failure=True,
    )
    assert result
    assert result[0]["asin"] == "B000000002"
    # stale catalog data never claims a current price
    assert result[0]["prezzo_finale"] is None


def test_detail_stale_can_preserve_payload_when_explicitly_requested(monkeypatch):
    monkeypatch.delenv("REDIS_URL", raising=False)
    key = ("detail-stale", time.time_ns())
    with shared_results._lock:
        shared_results._entries[key] = {
            "data": [{"asin": "B000000003", "prezzo_finale": 30.0, "prezzo_verificato": True}],
            "expires": time.time() - 1,
            "retry_at": time.time() + 20,
        }

    result = shared_results.get(
        key,
        ttl=30,
        loader=lambda: [],
        stale_for=60,
        report_failure=True,
        scrub_stale_prices=False,
    )
    assert result[0]["prezzo_finale"] == 30.0
