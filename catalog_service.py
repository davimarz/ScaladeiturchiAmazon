from __future__ import annotations

import hashlib
import math
import random
import time
from typing import Any, Iterable

import amazon_gateway
import amazon_html
import product_dedup
import shared_results
import telemetry

HAUL_POOL_TTL = 300
SHOWCASE_POOL_TTL = 30 * 60
SHOWCASE_STALE_FOR = 24 * 60 * 60
SHOWCASE_FETCH_COUNT = 6
HAUL_HISTORY_LIMIT = 50
SHOWCASE_HISTORY_LIMIT = 24
DISPLAY_BATCH_SIZE = 4

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


def _positive_float(value: Any) -> float | None:
    try:
        candidate = float(value)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(candidate) or candidate <= 0:
        return None
    return candidate


def _prepare_price_display(product: dict[str, Any]) -> dict[str, Any]:
    """Expose prices only when they come from an explicit Amazon price signal.

    Verified detail/HAUL prices remain first-class. Search-result prices may also
    be displayed when the Amazon SERP parser identified the base price node. If
    detail verification later failed, the original SERP values are recovered
    from the preserved `_search_*` fields instead of launching more requests.
    """
    prepared = dict(product)
    verified = prepared.get("prezzo_verificato") is True
    serp_confidence = str(prepared.get("_serp_price_confidence") or "").strip().lower()
    trusted_serp = serp_confidence == "base_price_node"

    final_price = _positive_float(prepared.get("prezzo_finale"))
    old_price = _positive_float(prepared.get("prezzo_iniziale"))

    if final_price is None and trusted_serp:
        final_price = _positive_float(prepared.get("_search_prezzo_finale"))
        old_price = _positive_float(prepared.get("_search_prezzo_iniziale"))
        if final_price is not None:
            prepared["prezzo_finale"] = final_price
            prepared["prezzo_iniziale"] = old_price

    displayable = final_price is not None and (verified or trusted_serp)
    prepared["_price_displayable"] = displayable

    if not displayable:
        prepared["_price_display_source"] = ""
        return prepared

    prepared["_price_display_source"] = "amazon_verified" if verified else "amazon_serp"
    prepared["prezzo_finale"] = final_price

    if old_price is not None and old_price > final_price:
        prepared["prezzo_iniziale"] = old_price
        if not str(prepared.get("sconto") or "").strip():
            discount_pct = int(round((old_price - final_price) / old_price * 100))
            if discount_pct > 0:
                prepared["sconto"] = f"-{discount_pct}%"
                prepared["sconto_val"] = discount_pct
    else:
        prepared["prezzo_iniziale"] = None

    return prepared


def _stamp(products: Iterable[dict[str, Any]], fetched_at: float | None = None) -> list[dict[str, Any]]:
    stamp = float(fetched_at or time.time())
    result: list[dict[str, Any]] = []
    for product in product_dedup.unique(list(products or [])):
        copy = _prepare_price_display(dict(product))
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


def get_haul_selection(item_count: int = DISPLAY_BATCH_SIZE, refresh_token: str | None = None, exclude_asins: Iterable[str] = ()) -> list[dict[str, Any]]:
    tag = amazon_gateway.get_partner_tag()
    if not tag:
        return []
    target = max(1, min(int(item_count or DISPLAY_BATCH_SIZE), 10))
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


def _showcase_keyword(now: float | None = None) -> str:
    """Rotate the showcase category only when its shared cache expires."""
    current = float(now if now is not None else time.time())
    bucket = int(current // SHOWCASE_POOL_TTL)
    return SHOWCASE_KEYWORDS[bucket % len(SHOWCASE_KEYWORDS)]


def _showcase_pool(tag: str) -> list[dict[str, Any]]:
    keyword = _showcase_keyword()
    started = time.perf_counter()
    try:
        products = amazon_html.fetch_search_products_fast(
            keyword=keyword,
            partner_tag=tag,
            item_count=SHOWCASE_FETCH_COUNT,
        )
    except Exception:
        telemetry.increment("showcase_fast_fetch_error")
        raise

    products = _stamp(products or [])
    telemetry.observe("showcase_fast_fetch_seconds", time.perf_counter() - started)
    telemetry.observe_value("showcase_pool_size", len(products))
    if not products:
        raise amazon_gateway.BudgetUnavailable("Nessun prodotto recuperabile per la Vetrina")
    return products


def get_showcase_selection(item_count: int = DISPLAY_BATCH_SIZE, refresh_token: str | None = None, exclude_asins: Iterable[str] = ()) -> list[dict[str, Any]]:
    tag = amazon_gateway.get_partner_tag()
    if not tag:
        return []

    target = max(1, min(int(item_count or DISPLAY_BATCH_SIZE), DISPLAY_BATCH_SIZE))
    token = str(refresh_token or time.time_ns())

    pool = shared_results.get(
        ("showcase-pool-v4", tag),
        SHOWCASE_POOL_TTL,
        lambda: _showcase_pool(tag),
        retry=60,
        stale_for=SHOWCASE_STALE_FOR,
        report_failure=True,
    )
    return _sample_fresh(pool, target, token, exclude_asins)


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
    if product.get("_price_displayable") is True:
        return _positive_float(product.get("prezzo_finale")) is not None
    return product.get("prezzo_verificato") is True and _positive_float(product.get("prezzo_finale")) is not None


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
