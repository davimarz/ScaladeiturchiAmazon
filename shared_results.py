"""Shared result cache with optional Redis backend and stale fallback."""
from __future__ import annotations

import copy
import hashlib
import json
import logging
import os
import threading
import time
from collections import OrderedDict
from typing import Any

import redis_client
import telemetry


class RetryPending(Exception):
    def __init__(self, retry_at):
        self.retry_at = retry_at
        super().__init__("Recupero temporaneamente non disponibile")


class EmptyResult(Exception):
    pass


_lock = threading.RLock()
_entries: OrderedDict[Any, dict[str, Any]] = OrderedDict()
_running: set[Any] = set()
_changed = threading.Condition(_lock)


def _redis_enabled() -> bool:
    return (
        redis_client.configured()
        and os.getenv("SCALA_SHARED_CACHE_REDIS", "1") != "0"
        and redis_client.get_client() is not None
    )


def _redis_client():
    if not redis_client.configured() or os.getenv("SCALA_SHARED_CACHE_REDIS", "1") == "0":
        return None
    return redis_client.get_client(timeout=2.0)


def _redis_key(key, suffix: str = "fresh") -> str:
    digest = hashlib.sha256(repr(key).encode("utf-8")).hexdigest()
    return f"scala:cache:{digest}:{suffix}"


def retry_at(key):
    with _lock:
        return _entries.get(key, {}).get("retry_at", 0)


def has_fresh(key) -> bool:
    """Best-effort cache-hit probe used only for telemetry."""
    now = time.time()
    with _lock:
        entry = _entries.get(key)
        if entry and now < float(entry.get("expires", 0)):
            return True
    client = _redis_client()
    if client is None:
        return False
    try:
        return bool(client.exists(_redis_key(key, "fresh")))
    except Exception:
        return False


def _redis_read(key, *, allow_stale: bool = False):
    client = _redis_client()
    if client is None:
        return None
    suffix = "stale" if allow_stale else "fresh"
    try:
        raw = client.get(_redis_key(key, suffix))
        if not raw:
            return None
        payload = json.loads(raw)
        now = time.time()
        if allow_stale:
            if now <= float(payload.get("stale_until", 0)):
                telemetry.increment("cache_hit_redis_stale")
                return payload.get("data")
        elif now < float(payload.get("expires", 0)):
            telemetry.increment("cache_hit_redis")
            return payload.get("data")
    except Exception as exc:
        telemetry.increment("cache_redis_error")
        logging.getLogger("amazon_affiliate.cache").warning(
            "redis_cache_read_failed error_type=%s", type(exc).__name__
        )
    return None


def _json_payload(payload: dict[str, Any]) -> str:
    # Niente default=str: tipi inattesi devono emergere in test/log invece di
    # essere convertiti silenziosamente e cambiare tipo al round-trip Redis.
    return json.dumps(payload, separators=(",", ":"), ensure_ascii=False)


def _redis_write(key, data, ttl: int, stale_for: int):
    client = _redis_client()
    if client is None:
        return
    try:
        now = time.time()
        ttl = max(1, int(ttl))
        stale_for = max(0, int(stale_for))
        fresh_payload = {"expires": now + ttl, "data": data}
        client.setex(_redis_key(key, "fresh"), ttl, _json_payload(fresh_payload))
        if stale_for > 0:
            stale_payload = {"stale_until": now + ttl + stale_for, "data": data}
            client.setex(
                _redis_key(key, "stale"),
                ttl + stale_for,
                _json_payload(stale_payload),
            )
    except TypeError:
        telemetry.increment("cache_serialization_error")
        raise
    except Exception as exc:
        telemetry.increment("cache_redis_error")
        logging.getLogger("amazon_affiliate.cache").warning(
            "redis_cache_write_failed error_type=%s", type(exc).__name__
        )


def get(
    key,
    ttl,
    loader,
    retry=30,
    stale_for=900,
    report_failure=False,
    scrub_stale_prices=True,
):
    redis_data = _redis_read(key)
    if redis_data is not None:
        return redis_data

    with _changed:
        wait_until = time.monotonic() + 12
        while key in _running:
            remaining = wait_until - time.monotonic()
            if remaining <= 0:
                entry = _entries.get(key)
                stale = _stale(entry, time.time(), stale_for, scrub_stale_prices) if entry else []
                if stale:
                    return stale
                redis_stale = _redis_read(key, allow_stale=True)
                if redis_stale is not None:
                    return _sanitize_stale(redis_stale, scrub_stale_prices)
                if report_failure:
                    raise RetryPending(time.time() + 1)
                return []
            _changed.wait(timeout=min(0.5, remaining))

        now = time.time()
        entry = _entries.get(key)
        if entry and now < entry["expires"]:
            telemetry.increment("cache_hit_memory")
            return copy.deepcopy(entry["data"])
        telemetry.increment("cache_miss")

        if entry and now < entry.get("retry_at", 0):
            stale = _stale(entry, now, stale_for, scrub_stale_prices)
            if stale:
                return stale
            redis_stale = _redis_read(key, allow_stale=True)
            if redis_stale is not None:
                return _sanitize_stale(redis_stale, scrub_stale_prices)
            if report_failure:
                raise RetryPending(entry["retry_at"])
            return []
        _running.add(key)

    try:
        data = loader()
        if not data:
            raise EmptyResult()
    except BaseException as exc:
        if not isinstance(exc, Exception):
            with _changed:
                _running.discard(key)
                _changed.notify_all()
            raise
        logging.getLogger("amazon_affiliate.cache").warning(
            "cache_loader_failed error_type=%s retry_seconds=%s",
            type(exc).__name__,
            retry,
        )
        with _changed:
            entry = _entries.setdefault(key, {"data": [], "expires": 0})
            entry["retry_at"] = time.time() + retry
            result = _stale(entry, time.time(), stale_for, scrub_stale_prices)
            _running.discard(key)
            _trim()
            _changed.notify_all()

        if result:
            return result

        redis_stale = _redis_read(key, allow_stale=True)
        if redis_stale is not None:
            return _sanitize_stale(redis_stale, scrub_stale_prices)

        if report_failure:
            raise RetryPending(entry["retry_at"]) from exc
        return []

    with _changed:
        _entries[key] = {"data": copy.deepcopy(data), "expires": time.time() + ttl}
        _entries.move_to_end(key)
        _running.discard(key)
        _trim()
        _changed.notify_all()
    _redis_write(key, data, ttl, stale_for)
    return data


def _trim():
    while len(_entries) > 256:
        _entries.popitem(last=False)


def _sanitize_stale(data, scrub_stale_prices: bool):
    result = copy.deepcopy(data)
    if not scrub_stale_prices:
        return result
    if not isinstance(result, list):
        return result
    for product in result:
        if not isinstance(product, dict):
            continue
        variants = product.get("variants", [])
        if not isinstance(variants, list):
            variants = []
        for offer in [product] + [item for item in variants if isinstance(item, dict)]:
            offer.update(
                prezzo_finale=None,
                prezzo_iniziale=None,
                prezzo_verificato=False,
                price_verified_at=0,
                sconto="",
                sconto_val=0,
            )
    return result


def _stale(entry, now, stale_for, scrub_stale_prices=True):
    if not entry or now > entry["expires"] + stale_for:
        return []
    telemetry.increment("cache_stale_served")
    return _sanitize_stale(entry["data"], scrub_stale_prices)
