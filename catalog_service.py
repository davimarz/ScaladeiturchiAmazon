from __future__ import annotations

import hashlib
import random
import time
from typing import Any, Iterable

import amazon_gateway
import product_dedup
import shared_results
import telemetry

HAUL_POOL_TTL = 300
SHOWCASE_POOL_TTL = 300
HAUL_HISTORY_LIMIT = 50
SHOWCASE_HISTORY_LIMIT = 24

SHOWCASE_KEYWORDS = (
    "offerte tecnologia",
    "offerte casa cucina",
    "offerte cuffie bluetooth",
    "offerte smartwatch",
    "offerte sport fitness",
    "offerte cura persona",
    "offerte accessori smartphone",
    "offerte elettrodomestici",
    "offerte scarpe",
    "offerte zaini accessori",
    "offerte amazon",
    "offerte del giorno",
)


def _asin(product: dict[str, Any]) -> str:
    return str(product.get("asin") or "").strip().upper()


def _stamp(products: Iterable[dict[str, Any]], fetched_at: float | None = None) -> list[dict[str, Any]]:
    stamp = float(fetched_at or time.time())
    result: list[dict[str, Any]] = []
    for product in product_dedup.unique(list(products or [])):
        copy = dict(product)
        copy.setdefault("_fetched_at", stamp)
        copy.setdefault("_source_label", str(copy.get("source") or "Amazon"))
        result.append(copy)
    return result


def _seed(token: str) -> int:
    digest = hashlib.sha256(str(token).encode("utf-8")).digest()
    return int.from_bytes(digest[:8], "big")


def _sample_fresh(pool: Iterable[dict[str, Any]], count: int, token: str, exclude_asins: Iterable[str] = ()) -> list[dict[str, Any]]:
    target = max(1, int(count))
    excluded = {str(value).strip().upper() for value in exclude_asins if str(value).strip()}
    unique_pool = product_dedup.unique(list(pool or []))
    fresh = [product for product in unique_pool if _asin(product) not in excluded]
    previous = [product for product in unique_pool if _asin(product) in excluded]
    rng = random.Random(_seed(token))
    rng.shuffle(fresh)
    rng.shuffle(previous)
    selected = fresh[:target]
    if len(selected) < target:
        selected.extend(previous[: target - len(selected)])
    telemetry.increment("catalog_sample_fresh", len([p for p in selected if _asin(p) not in excluded]))
    telemetry.increment("catalog_sample_repeated", len([p for p in selected if _asin(p) in excluded]))
    return selected[:target]


def _haul_pool(partner_tag: str) -> list[dict[str, Any]]:
    products = amazon_gateway.fetch_haul_products(partner_tag)
    products = _stamp(products)
    if not products:
        raise amazon_gateway.BudgetUnavailable("Nessun prodotto HAUL leggibile")
    telemetry.observe_value("haul_pool_size", len(products))
    return products


def get_haul_selection(item_count: int = 10, refresh_token: str | None = None, exclude_asins: Iterable[str] = ()) -> list[dict[str, Any]]:
    tag = amazon_gateway.get_partner_tag()
    if not tag:
        return []
    target = max(1, min(int(item_count or 10), 10))
    pool = shared_results.get(
        ("haul-pool-v3", tag),
        HAUL_POOL_TTL,
        lambda: _haul_pool(tag),
        retry=30,
        stale_for=900,
        report_failure=True,
    )
    token = str(refresh_token or time.time_ns())
    return _sample_fresh(pool, target, token, exclude_asins)


def _showcase_pool(tag: str, keyword: str) -> list[dict[str, Any]]:
    products = amazon_gateway.search_products(
        keyword=keyword,
        sort_type="Quantità vendite",
        prime_only=False,
        item_count=10,
        partner_tag_override=tag,
        cache_buster=f"showcase-pool:{keyword}",
    )
    return _stamp(products or [])


def get_showcase_selection(item_count: int = 3, refresh_token: str | None = None, exclude_asins: Iterable[str] = ()) -> list[dict[str, Any]]:
    tag = amazon_gateway.get_partner_tag()
    if not tag:
        return []
    target = max(1, min(int(item_count or 3), 3))
    token = str(refresh_token or time.time_ns())
    start = _seed(token) % len(SHOWCASE_KEYWORDS)
    combined: list[dict[str, Any]] = []
    for offset in range(min(5, len(SHOWCASE_KEYWORDS))):
        keyword = SHOWCASE_KEYWORDS[(start + offset) % len(SHOWCASE_KEYWORDS)]
        try:
            chunk = shared_results.get(
                ("showcase-pool-v3", tag, keyword),
                SHOWCASE_POOL_TTL,
                lambda keyword=keyword: _showcase_pool(tag, keyword),
                retry=30,
                stale_for=900,
            )
        except Exception:
            chunk = []
        combined.extend(chunk or [])
        if len(product_dedup.unique(combined)) >= max(target * 3, target):
            break
    telemetry.observe_value("showcase_pool_size", len(product_dedup.unique(combined)))
    return _sample_fresh(product_dedup.unique(combined), target, token, exclude_asins)


def search_products(keyword: str, sort_type: str, prime_only: bool, item_count: int, exclude_asins: Iterable[str] = ()) -> list[dict[str, Any]]:
    clean = " ".join(str(keyword or "").split())
    if not clean:
        return []
    products = amazon_gateway.search_products(
        keyword=clean,
        sort_type=sort_type,
        prime_only=bool(prime_only),
        item_count=max(1, min(int(item_count), amazon_gateway.MAX_RESULTS)),
        exclude_asins=tuple(str(value).strip().upper() for value in exclude_asins if str(value).strip()),
    )
    return _stamp(products or [])


def price_is_displayable(product: dict[str, Any]) -> bool:
    return product.get("prezzo_verificato") is True and product.get("prezzo_finale") is not None


def extend_history(history: Iterable[str], products: Iterable[dict[str, Any]], limit: int) -> list[str]:
    values = [str(value).strip().upper() for value in history if str(value).strip()]
    for product in products:
        value = _asin(product)
        if value:
            values.append(value)
    deduped: list[str] = []
    seen: set[str] = set()
    for value in reversed(values):
        if value in seen:
            continue
        seen.add(value)
        deduped.append(value)
    deduped.reverse()
    return deduped[-max(1, int(limit)):]
