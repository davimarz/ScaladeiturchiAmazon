from __future__ import annotations

from typing import Iterable

import amazon_api

MAX_RESULTS = amazon_api.MAX_RESULTS
HAUL_STORE_URL = amazon_api.HAUL_STORE_URL
BudgetUnavailable = amazon_api.api_budget.BudgetUnavailable
RetryPending = amazon_api.shared_results.RetryPending


def get_partner_tag() -> str:
    return amazon_api.get_partner_tag()


def fetch_haul_products(partner_tag: str) -> list[dict]:
    html_text = amazon_api._fetch_amazon_html(amazon_api.HAUL_STORE_URL)
    if not html_text:
        raise BudgetUnavailable("Pagina HAUL temporaneamente non leggibile")
    return amazon_api._extract_haul_products_from_html(html_text, partner_tag=partner_tag)


def search_products(
    keyword: str,
    sort_type: str,
    prime_only: bool,
    item_count: int,
    exclude_asins: Iterable[str] = (),
    cache_buster: str | None = None,
    partner_tag_override: str | None = None,
) -> list[dict]:
    kwargs = {
        "keyword": keyword,
        "sort_type": sort_type,
        "solo_spedizione_gratuita": bool(prime_only),
        "item_count": item_count,
        "exclude_asins": tuple(exclude_asins),
    }
    if cache_buster is not None:
        kwargs["_cache_buster"] = cache_buster
    if partner_tag_override is not None:
        kwargs["_partner_tag_override"] = partner_tag_override
    return amazon_api.ottieni_offerte_avanzate(**kwargs)


def build_search_link(keyword: str) -> str:
    return amazon_api.build_amazon_search_link(keyword)


def build_haul_link() -> str:
    return amazon_api.build_amazon_haul_link()
