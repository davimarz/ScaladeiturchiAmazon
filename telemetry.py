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
_VALUES: dict[str, list[float]] = defaultdict(list)
_MAX_SAMPLES = 300


def increment(name: str, amount: int = 1) -> None:
    with _LOCK:
        _COUNTERS[str(name)] += int(amount)


def _append(bucket: dict[str, list[float]], name: str, value: float) -> None:
    samples = bucket[str(name)]
    samples.append(float(value))
    if len(samples) > _MAX_SAMPLES:
        del samples[: len(samples) - _MAX_SAMPLES]


def observe(name: str, seconds: float) -> None:
    with _LOCK:
        _append(_TIMINGS, name, max(0.0, float(seconds)))


def observe_value(name: str, value: float) -> None:
    with _LOCK:
        _append(_VALUES, name, float(value))


@contextmanager
def timed(name: str) -> Iterator[None]:
    started = time.perf_counter()
    try:
        yield
    finally:
        observe(name, time.perf_counter() - started)


def _summary(values: list[float], milliseconds: bool = False) -> dict:
    ordered = sorted(values)
    factor = 1000 if milliseconds else 1
    idx50 = min(len(ordered) - 1, int((len(ordered) - 1) * 0.50))
    idx95 = min(len(ordered) - 1, int((len(ordered) - 1) * 0.95))
    return {
        "count": len(values),
        "avg": round(sum(values) / len(values) * factor, 1),
        "p50": round(ordered[idx50] * factor, 1),
        "p95": round(ordered[idx95] * factor, 1),
    }


def snapshot() -> dict:
    with _LOCK:
        timings = {name: _summary(values, milliseconds=True) for name, values in _TIMINGS.items() if values}
        values = {name: _summary(samples) for name, samples in _VALUES.items() if samples}
        return {"counters": dict(_COUNTERS), "timings_ms": timings, "values": values}


def log_snapshot() -> None:
    LOGGER.info("metrics=%s", snapshot())
