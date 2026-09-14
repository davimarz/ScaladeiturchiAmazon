from __future__ import annotations

from concurrent.futures import Future, ThreadPoolExecutor, wait
from typing import Iterable

import amazon_api
import amazon_html
import app_constants
import creators_api
import haul_parser
import shared_results
import telemetry
from product_models import PriceConfidence, PriceSource, Product, TRUSTED_PRICE_CONFIDENCE

MAX_RESULTS = amazon_api.MAX_RESULTS
BudgetUnavailable = amazon_api.api_budget.BudgetUnavailable
RetryPending = amazon_api.shared_results.RetryPending


def get_partner_tag() -> str:
    return amazon_api.get_partner_tag()


def fetch_haul_products(partner_tag: str) -> list[Product]:
    return haul_parser.fetch_products(partner_tag)


def _detail_cache_key(product: Product) -> tuple[str, str]:
    asin = str(product.get("asin") or "").strip().upper()
    return (f"amazon-detail-fast-v{app_constants.CACHE_SCHEMA_VERSION}", asin)


def _enrich_one_cached(product: Product) -> Product:
    item: Product = {
        key: value for key, value in dict(product).items() if key != "variants"
    }
    asin = str(item.get("asin") or "").strip().upper()
    if len(asin) != 10:
        return item

    cache_key = _detail_cache_key(item)
    was_cached = shared_results.has_fresh(cache_key)
    telemetry.increment("detail_cache_hit" if was_cached else "detail_cache_miss")
    telemetry.observe_value("detail_cache_hit_ratio", 1.0 if was_cached else 0.0)

    def loader() -> list[Product]:
        telemetry.increment("amazon_http_detail_requests")
        enriched: Product = dict(
            amazon_html.enrich_product_detail_fast(dict(item)) or item
        )
        enriched.setdefault("detail_verified_at", enriched.get("price_verified_at"))
        if enriched.get("prezzo_verificato") is True:
            enriched["price_source"] = PriceSource.AMAZON_DETAIL.value
            enriched["_serp_price_confidence"] = PriceConfidence.VERIFIED_DETAIL.value
        return [enriched]

    cached = shared_results.get(
        cache_key,
        app_constants.SHOWCASE_DETAIL_CACHE_TTL,
        loader,
        retry=20,
        stale_for=app_constants.SHOWCASE_DETAIL_STALE_FOR,
        report_failure=False,
        scrub_stale_prices=True,
    )
    if cached:
        return dict(cached[0])
    return item


def enrich_product_details(products: Iterable[Product]) -> list[Product]:
    """Arricchisce al massimo il batch visibile, con cache e deadline globale."""
    items: list[Product] = [
        {key: value for key, value in dict(product).items() if key != "variants"}
        for product in products or []
    ]
    if not items:
        return []

    executor = ThreadPoolExecutor(
        max_workers=min(app_constants.DISPLAY_BATCH_SIZE, len(items))
    )
    futures: dict[Future, int] = {
        executor.submit(_enrich_one_cached, item): index
        for index, item in enumerate(items)
    }
    results: list[Product] = [dict(item) for item in items]
    try:
        done, pending = wait(
            futures,
            timeout=app_constants.SHOWCASE_DETAIL_ENRICH_TIMEOUT,
        )
        for future in done:
            index = futures[future]
            try:
                results[index] = dict(future.result() or items[index])
            except Exception as exc:
                telemetry.increment("detail_enrich_error")
                telemetry.increment(f"detail_enrich_error_{type(exc).__name__}")
        if pending:
            telemetry.increment("detail_enrich_timeout", len(pending))
            for future in pending:
                future.cancel()
    finally:
        executor.shutdown(wait=False, cancel_futures=True)
    return results


def _needs_search_recovery(product: Product) -> bool:
    image = str(product.get("immagine_url") or "").strip()
    try:
        price = float(product.get("prezzo_finale") or 0)
    except (TypeError, ValueError):
        price = 0.0
    verified_price = product.get("prezzo_verificato") is True and price > 0
    trusted_card_price = (
        str(product.get("_serp_price_confidence") or "").strip().lower()
        in TRUSTED_PRICE_CONFIDENCE
        and price > 0
    )
    return not image or not (verified_price or trusted_card_price)


def _merge_recovered_product(original: Product, recovered: Product) -> Product:
    merged: Product = dict(original)
    if not recovered:
        return merged

    recovered_image = str(recovered.get("immagine_url") or "").strip()
    if recovered_image:
        merged["immagine_url"] = recovered_image

    recovered_price = recovered.get("prezzo_finale")
    try:
        valid_recovered_price = float(recovered_price) > 0
    except (TypeError, ValueError):
        valid_recovered_price = False

    if recovered.get("prezzo_verificato") is True and valid_recovered_price:
        for key in (
            "prezzo_finale",
            "prezzo_iniziale",
            "prezzo_verificato",
            "price_verified_at",
            "detail_verified_at",
            "price_source",
            "_serp_price_confidence",
            "sconto",
            "sconto_val",
            "source",
        ):
            if key in recovered:
                merged[key] = recovered[key]

    for key in (
        "titolo",
        "size",
        "color",
        "sold_qty_month",
        "sold_qty_label",
        "prime",
        "is_prime",
        "prime_detail_verified",
        "prime_source",
    ):
        value = recovered.get(key)
        if value not in (None, ""):
            merged[key] = value

    return merged


def search_products(
    keyword: str,
    sort_type: str,
    prime_only: bool,
    item_count: int,
    exclude_asins: Iterable[str] = (),
    cache_buster: str | None = None,
    partner_tag_override: str | None = None,
) -> list[Product]:
    products: list[Product] = list(
        creators_api.search(
            keyword=keyword,
            sort_type=sort_type,
            prime_only=prime_only,
            item_count=item_count,
            exclude_asins=exclude_asins,
            cache_buster=cache_buster,
            partner_tag_override=partner_tag_override,
        )
        or []
    )

    recovery_indexes = [
        index
        for index, product in enumerate(products)
        if _needs_search_recovery(product)
    ][: app_constants.SEARCH_DETAIL_RECOVERY_LIMIT]

    if recovery_indexes:
        recovered = enrich_product_details(
            products[index] for index in recovery_indexes
        )
        for index, recovered_product in zip(recovery_indexes, recovered):
            products[index] = _merge_recovered_product(
                products[index], recovered_product
            )

    return products


def build_search_link(keyword: str) -> str:
    return amazon_api.build_amazon_search_link(keyword)


def build_haul_link() -> str:
    return amazon_api.build_amazon_haul_link()
