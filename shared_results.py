"""Shared result cache with optional Redis backend and stale fallback."""
from __future__ import annotations

import copy
import json
import logging
import os
import threading
import time
from collections import OrderedDict

import telemetry

try:
    import redis
except ImportError:  # pragma: no cover
    redis = None


class RetryPending(Exception):
    def __init__(self, retry_at):
        self.retry_at = retry_at
        super().__init__("Recupero temporaneamente non disponibile")


class EmptyResult(Exception):
    pass


_lock = threading.RLock()
_entries = OrderedDict()
_running = set()
_changed = threading.Condition(_lock)


def _redis_enabled() -> bool:
    return bool(os.getenv("REDIS_URL", "").strip()) and os.getenv("SCALA_SHARED_CACHE_REDIS", "1") != "0" and redis is not None


def _redis_client():
    if not _redis_enabled():
        return None
    return redis.Redis.from_url(os.getenv("REDIS_URL", ""), decode_responses=True, socket_timeout=2, socket_connect_timeout=2)


def _redis_key(key) -> str:
    import hashlib
    digest = hashlib.sha256(repr(key).encode("utf-8")).hexdigest()
    return f"scala:cache:{digest}"


def retry_at(key):
    with _lock:
        return _entries.get(key, {}).get("retry_at", 0)


def _redis_read(key):
    client = _redis_client()
    if client is None:
        return None
    try:
        raw = client.get(_redis_key(key))
        if not raw:
            return None
        payload = json.loads(raw)
        if time.time() < float(payload.get("expires", 0)):
            telemetry.increment("cache_hit_redis")
            return payload.get("data")
    except Exception:
        telemetry.increment("cache_redis_error")
    return None


def _redis_write(key, data, ttl: int):
    client = _redis_client()
    if client is None:
        return
    try:
        payload = {"expires": time.time() + ttl, "data": data}
        client.setex(_redis_key(key), max(1, int(ttl)), json.dumps(payload, separators=(",", ":"), default=str))
    except Exception:
        telemetry.increment("cache_redis_error")


def get(key, ttl, loader, retry=30, stale_for=900, report_failure=False):
    redis_data = _redis_read(key)
    if redis_data is not None:
        return redis_data

    with _changed:
        wait_until = time.monotonic() + 12
        while key in _running:
            remaining = wait_until - time.monotonic()
            if remaining <= 0:
                entry = _entries.get(key)
                if report_failure:
                    raise RetryPending(time.time() + 1)
                return _stale(entry, time.time(), stale_for) if entry else []
            _changed.wait(timeout=min(0.5, remaining))
        now = time.time()
        entry = _entries.get(key)
        if entry and now < entry["expires"]:
            telemetry.increment("cache_hit_memory")
            return copy.deepcopy(entry["data"])
        telemetry.increment("cache_miss")
        if entry and now < entry.get("retry_at", 0):
            if report_failure:
                raise RetryPending(entry["retry_at"])
            return _stale(entry, now, stale_for)
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
        logger = logging.getLogger("amazon_affiliate")
        logger.warning("Cache loader failed error_type=%s retry_seconds=%s", type(exc).__name__, retry)
        with _changed:
            entry = _entries.setdefault(key, {"data": [], "expires": 0})
            entry["retry_at"] = time.time() + retry
            result = _stale(entry, time.time(), stale_for)
            _running.discard(key)
            _trim()
            _changed.notify_all()
        if report_failure:
            raise RetryPending(entry["retry_at"]) from exc
        return result

    with _changed:
        _entries[key] = {"data": copy.deepcopy(data), "expires": time.time() + ttl}
        _entries.move_to_end(key)
        _running.discard(key)
        _trim()
        _changed.notify_all()
    _redis_write(key, data, ttl)
    return data


def _trim():
    while len(_entries) > 256:
        _entries.popitem(last=False)


def _stale(entry, now, stale_for):
    if not entry or now > entry["expires"] + stale_for:
        return []
    data = copy.deepcopy(entry["data"])
    for product in data:
        for offer in [product] + list(product.get("variants", [])):
            offer.update(prezzo_finale=None, prezzo_iniziale=None, prezzo_verificato=False, sconto="", sconto_val=0)
    telemetry.increment("cache_stale_served")
    return data
