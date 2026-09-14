from __future__ import annotations

import hashlib
import math
import random
import time
from typing import Any, Iterable

import amazon_gateway
import app_constants
import product_dedup
import shared_results
import showcase_parser
import telemetry
from product_models import PriceSource, Product, TRUSTED_PRICE_CONFIDENCE

HAUL_POOL_TTL = 300
SHOWCASE_POOL_TTL = 30 * 60
SHOWCASE_STALE_FOR = 24 * 60 * 60
SHOWCASE_FETCH_COUNT = 12
HAUL_HISTORY_LIMIT = 50
SHOWCASE_HISTORY_LIMIT = 24
DISPLAY_BATCH_SIZE = app_constants.DISPLAY_BATCH_SIZE


def _asin(product: Product) -> str:
    return str(product.get("asin") or "").strip().upper()


def _positive_float(value: Any) -> float | None:
    try:
        candidate = float(value)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(candidate) or candidate <= 0:
        return None
    return candidate


def _price_is_fresh(product: Product, now: float | None = None) -> bool:
    verified_at = _positive_float(product.get("price_verified_at"))
    if verified_at is None:
        return False
    current = float(now if now is not None else time.time())
    return current - verified_at <= app_constants.PRICE_FRESHNESS_SECONDS


def _prepare_price_display(product: Product, now: float | None = None) -> Product:
    """Espone prezzi Amazon espliciti soltanto entro la finestra di freschezza."""
    prepared: Product = dict(product)
    stamp = float(now if now is not None else time.time())
    verified = prepared.get("prezzo_verificato") is True
    confidence = str(prepared.get("_serp_price_confidence") or "").strip().lower()
    trusted_serp = confidence in TRUSTED_PRICE_CONFIDENCE

    final_price = _positive_float(prepared.get("prezzo_finale"))
    old_price = _positive_float(prepared.get("prezzo_iniziale"))

    if final_price is None and trusted_serp:
        final_price = _positive_float(prepared.get("_search_prezzo_finale"))
        old_price = _positive_float(prepared.get("_search_prezzo_iniziale"))
        if final_price is not None:
            prepared["prezzo_finale"] = final_price
            prepared["prezzo_iniziale"] = old_price

    if final_price is not None and not prepared.get("price_verified_at"):
        prepared["price_verified_at"] = stamp

    fresh = _price_is_fresh(prepared, stamp)
    displayable = final_price is not None and fresh and (verified or trusted_serp)
    prepared["_price_displayable"] = displayable

    if not displayable:
        prepared["_price_display_source"] = ""
        return prepared

    if verified:
        prepared["_price_display_source"] = "amazon_verified"
        prepared.setdefault("price_source", PriceSource.AMAZON_DETAIL.value)
    else:
        prepared["_price_display_source"] = "amazon_card"
        prepared.setdefault("price_source", PriceSource.AMAZON_CARD.value)
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


def _stamp(products: Iterable[Product], fetched_at: float | None = None) -> list[Product]:
    stamp = float(fetched_at or time.time())
    result: list[Product] = []
    for product in product_dedup.unique(list(products or [])):
        copy: Product = dict(product)
        copy.setdefault("_fetched_at", stamp)
        copy.setdefault("_source_label", str(copy.get("source") or "Amazon"))
        copy = _prepare_price_display(copy, stamp)
        result.append(copy)
    return result


def _mark_displayed(products: Iterable[Product]) -> list[Product]:
    now = time.time()
    result: list[Product] = []
    for product in products:
        copy: Product = dict(product)
        copy["displayed_at"] = now
        result.append(copy)
    return result


def _seed(token: str) -> int:
    digest = hashlib.sha256(str(token).encode("utf-8")).digest()
    return int.from_bytes(digest[:8], "big")


def _sample_fresh(
    pool: Iterable[Product],
    count: int,
    token: str,
    exclude_asins: Iterable[str] = (),
) -> list[Product]:
    target = max(1, int(count))
    excluded = {
        str(value).strip().upper()
        for value in exclude_asins
        if str(value).strip()
    }
    unique_pool = product_dedup.unique(list(pool or []))
    fresh = [product for product in unique_pool if _asin(product) not in excluded]
    previous = [product for product in unique_pool if _asin(product) in excluded]
    rng = random.Random(_seed(token))
    rng.shuffle(fresh)
    rng.shuffle(previous)
    selected = fresh[:target]
    if len(selected) < target:
        selected.extend(previous[: target - len(selected)])
    telemetry.increment(
        "catalog_sample_fresh",
        len([p for p in selected if _asin(p) not in excluded]),
    )
    telemetry.increment(
        "catalog_sample_repeated",
        len([p for p in selected if _asin(p) in excluded]),
    )
    return selected[:target]


def _observe_batch(prefix: str, products: list[Product]) -> None:
    if not products:
        return
    visible_prices = sum(1 for product in products if price_is_displayable(product))
    visible_images = sum(
        1 for product in products if str(product.get("immagine_url") or "").strip()
    )
    telemetry.observe_value(
        f"{prefix}_price_visible_ratio", visible_prices / len(products)
    )
    telemetry.observe_value(
        f"{prefix}_image_visible_ratio", visible_images / len(products)
    )


def _haul_pool(partner_tag: str) -> list[Product]:
    products = _stamp(amazon_gateway.fetch_haul_products(partner_tag))
    if not products:
        raise amazon_gateway.BudgetUnavailable("Nessun prodotto HAUL leggibile")
    telemetry.observe_value("haul_pool_size", len(products))
    return products


def get_haul_selection(
    item_count: int = DISPLAY_BATCH_SIZE,
    refresh_token: str | None = None,
    exclude_asins: Iterable[str] = (),
) -> list[Product]:
    tag = amazon_gateway.get_partner_tag()
    if not tag:
        return []
    target = max(1, min(int(item_count or DISPLAY_BATCH_SIZE), 10))
    pool = shared_results.get(
        (f"haul-pool-v{app_constants.CACHE_SCHEMA_VERSION}", tag),
        HAUL_POOL_TTL,
        lambda: _haul_pool(tag),
        retry=30,
        stale_for=900,
        report_failure=True,
    )
    selected = _mark_displayed(
        _sample_fresh(
            pool,
            target,
            str(refresh_token or time.time_ns()),
            exclude_asins,
        )
    )
    _observe_batch("haul", selected)
    return selected


def _showcase_page_index(now: float | None = None) -> int:
    current = float(now if now is not None else time.time())
    bucket = int(current // SHOWCASE_POOL_TTL)
    return bucket % len(showcase_parser.SHOWCASE_PAGES)


def _showcase_pool(tag: str) -> list[Product]:
    page_index = _showcase_page_index()
    started = time.perf_counter()
    try:
        products = showcase_parser.fetch_products(
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
        raise amazon_gateway.BudgetUnavailable(
            "Nessun prodotto recuperabile per la Vetrina"
        )
    return products


def get_showcase_selection(
    item_count: int = DISPLAY_BATCH_SIZE,
    refresh_token: str | None = None,
    exclude_asins: Iterable[str] = (),
) -> list[Product]:
    tag = amazon_gateway.get_partner_tag()
    if not tag:
        return []

    target = max(
        1,
        min(int(item_count or DISPLAY_BATCH_SIZE), DISPLAY_BATCH_SIZE),
    )
    token = str(refresh_token or time.time_ns())
    pool = shared_results.get(
        (f"showcase-pool-v{app_constants.CACHE_SCHEMA_VERSION}", tag),
        SHOWCASE_POOL_TTL,
        lambda: _showcase_pool(tag),
        retry=60,
        stale_for=SHOWCASE_STALE_FOR,
        report_failure=True,
    )

    selected = _sample_fresh(pool, target, token, exclude_asins)
    if not selected:
        return []
    selected_for_detail: list[Product] = [
        {key: value for key, value in dict(product).items() if key != "variants"}
        for product in selected
    ]

    started = time.perf_counter()
    enriched = _stamp(amazon_gateway.enrich_product_details(selected_for_detail))
    telemetry.observe(
        "showcase_detail_enrich_seconds", time.perf_counter() - started
    )
    enriched = _mark_displayed(enriched[:target])
    _observe_batch("showcase", enriched)
    return enriched


def search_products(
    keyword: str,
    sort_type: str,
    prime_only: bool,
    item_count: int,
    exclude_asins: Iterable[str] = (),
) -> list[Product]:
    clean = " ".join(str(keyword or "").split())
    if not clean:
        return []
    products = amazon_gateway.search_products(
        keyword=clean,
        sort_type=sort_type,
        prime_only=bool(prime_only),
        item_count=max(1, min(int(item_count), amazon_gateway.MAX_RESULTS)),
        exclude_asins=tuple(
            str(value).strip().upper()
            for value in exclude_asins
            if str(value).strip()
        ),
    )
    stamped = _mark_displayed(_stamp(products or []))
    _observe_batch("search", stamped)
    return stamped


def price_is_displayable(product: Product) -> bool:
    if product.get("_price_displayable") is True:
        return (
            _positive_float(product.get("prezzo_finale")) is not None
            and _price_is_fresh(product)
        )
    confidence = str(product.get("_serp_price_confidence") or "").strip().lower()
    trusted = (
        product.get("prezzo_verificato") is True
        or confidence in TRUSTED_PRICE_CONFIDENCE
    )
    return (
        trusted
        and _positive_float(product.get("prezzo_finale")) is not None
        and _price_is_fresh(product)
    )


def extend_history(
    history: Iterable[str],
    products: Iterable[Product],
    limit: int,
) -> list[str]:
    values = [
        str(value).strip().upper()
        for value in history
        if str(value).strip()
    ]
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
