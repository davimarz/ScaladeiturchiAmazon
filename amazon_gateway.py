from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from typing import Iterable

import amazon_api
import amazon_html
import creators_api

MAX_RESULTS = amazon_api.MAX_RESULTS
BudgetUnavailable = amazon_api.api_budget.BudgetUnavailable
RetryPending = amazon_api.shared_results.RetryPending


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
            return dict(amazon_api._verify_product_detail_price(dict(product)) or product)
        except Exception:
            return dict(product)

    with ThreadPoolExecutor(max_workers=min(4, len(items))) as executor:
        return list(executor.map(enrich, items))


def search_products(
    keyword: str,
    sort_type: str,
    prime_only: bool,
    item_count: int,
    exclude_asins: Iterable[str] = (),
    cache_buster: str | None = None,
    partner_tag_override: str | None = None,
) -> list[dict]:
    return creators_api.search(
        keyword=keyword,
        sort_type=sort_type,
        prime_only=prime_only,
        item_count=item_count,
        exclude_asins=exclude_asins,
        cache_buster=cache_buster,
        partner_tag_override=partner_tag_override,
    )


def build_search_link(keyword: str) -> str:
    return amazon_api.build_amazon_search_link(keyword)


def build_haul_link() -> str:
    return amazon_api.build_amazon_haul_link()
