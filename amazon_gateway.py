from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from typing import Iterable

import amazon_api
import amazon_html
import creators_api

MAX_RESULTS = amazon_api.MAX_RESULTS
BudgetUnavailable = amazon_api.api_budget.BudgetUnavailable
RetryPending = amazon_api.shared_results.RetryPending
SEARCH_RECOVERY_LIMIT = 4


def get_partner_tag() -> str:
    return amazon_api.get_partner_tag()


def fetch_haul_products(partner_tag: str) -> list[dict]:
    return amazon_html.fetch_haul_products(partner_tag)


def enrich_product_details(products: Iterable[dict]) -> list[dict]:
    # Drop the presentation-only `variants` wrapper before enriching. Keeping it
    # would cause product_dedup.unique() to flatten back to the pre-enrichment
    # variant and discard the newly verified price fields.
    items = [
        {key: value for key, value in dict(product).items() if key != "variants"}
        for product in products or []
    ]
    if not items:
        return []

    def enrich(product: dict) -> dict:
        try:
            return dict(amazon_html.enrich_product_detail_fast(dict(product)) or product)
        except Exception:
            return dict(product)

    with ThreadPoolExecutor(max_workers=min(4, len(items))) as executor:
        return list(executor.map(enrich, items))


def _needs_search_recovery(product: dict) -> bool:
    image = str(product.get("immagine_url") or "").strip()
    try:
        price = float(product.get("prezzo_finale") or 0)
    except (TypeError, ValueError):
        price = 0.0
    verified_price = product.get("prezzo_verificato") is True and price > 0
    trusted_serp_price = (
        str(product.get("_serp_price_confidence") or "").strip().lower() == "base_price_node"
        and price > 0
    )
    return not image or not (verified_price or trusted_serp_price)


def _merge_recovered_product(original: dict, recovered: dict) -> dict:
    merged = dict(original)
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
            "_serp_price_confidence",
            "sconto",
            "sconto_val",
            "source",
        ):
            if key in recovered:
                merged[key] = recovered[key]

    for key in ("titolo", "size", "color", "sold_qty_month", "sold_qty_label"):
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
) -> list[dict]:
    products = list(creators_api.search(
        keyword=keyword,
        sort_type=sort_type,
        prime_only=prime_only,
        item_count=item_count,
        exclude_asins=exclude_asins,
        cache_buster=cache_buster,
        partner_tag_override=partner_tag_override,
    ) or [])

    # SearchItems/HTML fallback can occasionally return a valid Amazon product
    # before its image or current price is available. Recover only the first few
    # incomplete cards, in parallel, so normal searches stay fast while the UI
    # gets a second chance to obtain the canonical image and price from the
    # corresponding Amazon product page.
    recovery_indexes = [
        index for index, product in enumerate(products)
        if _needs_search_recovery(product)
    ][:SEARCH_RECOVERY_LIMIT]

    if recovery_indexes:
        recovered = enrich_product_details(products[index] for index in recovery_indexes)
        for index, recovered_product in zip(recovery_indexes, recovered):
            products[index] = _merge_recovered_product(products[index], recovered_product)

    return products


def build_search_link(keyword: str) -> str:
    return amazon_api.build_amazon_search_link(keyword)


def build_haul_link() -> str:
    return amazon_api.build_amazon_haul_link()
