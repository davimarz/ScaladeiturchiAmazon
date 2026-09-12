from __future__ import annotations

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
