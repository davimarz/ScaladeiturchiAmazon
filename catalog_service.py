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
SHOWCASE_FETCH_COUNT = 12
HAUL_HISTORY_LIMIT = 50
SHOWCASE_HISTORY_LIMIT = 24
DISPLAY_BATCH_SIZE = 4
SEARCH_DETAIL_RECOVERY_LIMIT = 4


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
    """Expose prices only when they come from an explicit Amazon price signal."""
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


def _has_image(product: dict[str, Any]) -> bool:
    if str(product.get("immagine_url") or "").strip():
        return True
    fallbacks = product.get("immagine_fallback_urls") or []
    if isinstance(fallbacks, str):
        fallbacks = [fallbacks]
    return any(str(value or "").strip() for value in fallbacks)


def _recover_search_details(products: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
    """Retry only the first incomplete search cards, once and in parallel.

    The core search already tries its normal sources. This small recovery pass is
    intentionally capped so a blocked Amazon detail endpoint cannot turn one
    search into dozens of additional requests.
    """
    items = [dict(product) for product in products or []]
    indexes = [
        index for index, product in enumerate(items)
        if not _has_image(product) or not price_is_displayable(_prepare_price_display(product))
    ][:SEARCH_DETAIL_RECOVERY_LIMIT]
    if not indexes:
        return items

    candidates = [
        {key: value for key, value in items[index].items() if key != "variants"}
        for index in indexes
    ]
    started = time.perf_counter()
    try:
        recovered = list(amazon_gateway.enrich_product_details(candidates) or [])
    except Exception:
        telemetry.increment("search_detail_recovery_error")
        return items

    for index, richer in zip(indexes, recovered):
        original = items[index]
        richer = dict(richer or {})
        merged = dict(original)

        recovered_image = str(richer.get("immagine_url") or "").strip()
        if recovered_image:
            previous_image = str(original.get("immagine_url") or "").strip()
            merged["immagine_url"] = recovered_image
            fallback_values = []
            if previous_image and previous_image != recovered_image:
                fallback_values.append(previous_image)
            for value in original.get("immagine_fallback_urls") or []:
                clean = str(value or "").strip()
                if clean and clean != recovered_image and clean not in fallback_values:
                    fallback_values.append(clean)
            for value in richer.get("immagine_fallback_urls") or []:
                clean = str(value or "").strip()
                if clean and clean != recovered_image and clean not in fallback_values:
                    fallback_values.append(clean)
            merged["immagine_fallback_urls"] = fallback_values

        if richer.get("prezzo_verificato") is True and _positive_float(richer.get("prezzo_finale")) is not None:
            for field in ("prezzo_finale", "prezzo_iniziale", "prezzo_verificato", "sconto", "sconto_val", "source"):
                if field in richer:
                    merged[field] = richer[field]

        for field in ("titolo", "size", "color", "sold_qty_month", "sold_qty_label", "sales_rank"):
            if richer.get(field) not in (None, ""):
                merged[field] = richer[field]
        items[index] = merged

    telemetry.observe("search_detail_recovery_seconds", time.perf_counter() - started)
    telemetry.observe_value("search_detail_recovery_count", len(indexes))
    return items


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


def _showcase_page_index(now: float | None = None) -> int:
    """Rotate the direct Amazon showcase page only when shared cache expires."""
    current = float(now if now is not None else time.time())
    bucket = int(current // SHOWCASE_POOL_TTL)
    return bucket % len(amazon_html.SHOWCASE_PAGES)


def _showcase_pool(tag: str) -> list[dict[str, Any]]:
    page_index = _showcase_page_index()
    started = time.perf_counter()
    try:
        products = amazon_html.fetch_showcase_products_fast(
            page_index=page_index,
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
        ("showcase-pool-v6", tag),
        SHOWCASE_POOL_TTL,
        lambda: _showcase_pool(tag),
        retry=60,
        stale_for=SHOWCASE_STALE_FOR,
        report_failure=True,
    )

    selected = _sample_fresh(pool, target, token, exclude_asins)
    if not selected:
        return []

    selected_for_detail = [
        {key: value for key, value in dict(product).items() if key != "variants"}
        for product in selected
    ]

    started = time.perf_counter()
    enriched = amazon_gateway.enrich_product_details(selected_for_detail)
    enriched = _stamp(enriched)
    telemetry.observe("showcase_detail_enrich_seconds", time.perf_counter() - started)
    telemetry.observe_value(
        "showcase_detail_prices_visible",
        sum(1 for product in enriched if price_is_displayable(product)),
    )
    return enriched[:target]


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
    products = _stamp(products or [])
    products = _recover_search_details(products)
    return _stamp(products)


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
