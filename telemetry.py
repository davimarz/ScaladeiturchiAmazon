from __future__ import annotations

import logging
import threading
import time
from collections import defaultdict
from contextlib import contextmanager
from typing import Iterator

LOGGER = logging.getLogger("amazon_affiliate.metrics")
_LOCK = threading.RLock()
_COUNTERS: dict[str, int] = defaultdict(int)
_TIMINGS: dict[str, list[float]] = defaultdict(list)
_MAX_SAMPLES = 200


def increment(name: str, amount: int = 1) -> None:
    with _LOCK:
        _COUNTERS[str(name)] += int(amount)


def observe(name: str, seconds: float) -> None:
    with _LOCK:
        samples = _TIMINGS[str(name)]
        samples.append(max(0.0, float(seconds)))
        if len(samples) > _MAX_SAMPLES:
            del samples[: len(samples) - _MAX_SAMPLES]


@contextmanager
def timed(name: str) -> Iterator[None]:
    started = time.perf_counter()
    try:
        yield
    finally:
        observe(name, time.perf_counter() - started)


def snapshot() -> dict:
    with _LOCK:
        timings = {}
        for name, values in _TIMINGS.items():
            if not values:
                continue
            ordered = sorted(values)
            timings[name] = {
                "count": len(values),
                "avg_ms": round(sum(values) / len(values) * 1000, 1),
                "p95_ms": round(ordered[min(len(ordered) - 1, int(len(ordered) * 0.95))] * 1000, 1),
            }
        return {"counters": dict(_COUNTERS), "timings": timings}


def log_snapshot() -> None:
    LOGGER.info("metrics=%s", snapshot())
