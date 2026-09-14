"""Redis opzionale centralizzato.

L'app resta pienamente funzionante senza Redis. Quando REDIS_URL è configurato,
questo modulo uniforma timeout, TLS e modalità strict per cache/rate limit/budget.
"""
from __future__ import annotations

import logging
import os
from urllib.parse import urlparse

try:
    import redis
except ImportError:  # pragma: no cover
    redis = None

LOGGER = logging.getLogger("amazon_affiliate.redis")


def configured() -> bool:
    return bool(os.getenv("REDIS_URL", "").strip())


def strict() -> bool:
    return os.getenv("STRICT_REDIS", "0").strip().lower() in {"1", "true", "yes", "on"}


def uses_tls() -> bool:
    url = os.getenv("REDIS_URL", "").strip()
    return bool(url) and urlparse(url).scheme.lower() == "rediss"


def get_client(*, decode_responses: bool = True, timeout: float = 3.0):
    url = os.getenv("REDIS_URL", "").strip()
    if not url or redis is None:
        return None
    scheme = urlparse(url).scheme.lower()
    if scheme not in {"redis", "rediss"}:
        raise ValueError("REDIS_URL deve usare redis:// o rediss://")
    if scheme == "redis" and os.getenv("REDIS_REMOTE", "0") == "1":
        LOGGER.warning("redis_remote_without_tls")
    return redis.Redis.from_url(
        url,
        decode_responses=decode_responses,
        socket_timeout=timeout,
        socket_connect_timeout=timeout,
        health_check_interval=30,
    )
