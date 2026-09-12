from __future__ import annotations

from urllib.parse import urlencode

import amazon_api


SHOWCASE_FAST_TIMEOUT = 5
SHOWCASE_FAST_MAX_ITEMS = 6


def fetch_haul_products(partner_tag: str) -> list[dict]:
    html_text = amazon_api._fetch_amazon_html(amazon_api.HAUL_STORE_URL)
    if not html_text:
        raise amazon_api.api_budget.BudgetUnavailable("Pagina HAUL temporaneamente non leggibile")
    return amazon_api._extract_haul_products_from_html(html_text, partner_tag=partner_tag)


def fetch_search_products_fast(keyword: str, partner_tag: str, item_count: int = SHOWCASE_FAST_MAX_ITEMS) -> list[dict]:
    """Fast Amazon-only search used by the passive showcase.

    It deliberately performs a single Amazon SERP request, does not invoke
    external discovery engines and does not run per-product detail recovery.
    """
    clean_keyword = " ".join(str(keyword or "").split())
    tag = str(partner_tag or "").strip()
    if not clean_keyword or not tag:
        return []

    target = max(1, min(int(item_count or SHOWCASE_FAST_MAX_ITEMS), SHOWCASE_FAST_MAX_ITEMS))
    query = urlencode({"k": clean_keyword, "s": "relevanceblender", "tag": tag})
    url = f"https://www.amazon.it/s?{query}"

    html_text = amazon_api._fetch_amazon_html(
        url,
        timeout=SHOWCASE_FAST_TIMEOUT,
        single_attempt=True,
    )
    if not html_text:
        raise amazon_api.api_budget.BudgetUnavailable("Vetrina Amazon temporaneamente non leggibile")

    products = amazon_api._extract_products_from_html(
        html_text,
        partner_tag=tag,
        min_price=None,
        max_price=None,
        require_prime=False,
    )
    return list(products or [])[:target]
