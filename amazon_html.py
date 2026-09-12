from __future__ import annotations

import amazon_api


def fetch_haul_products(partner_tag: str) -> list[dict]:
    html_text = amazon_api._fetch_amazon_html(amazon_api.HAUL_STORE_URL)
    if not html_text:
        raise amazon_api.api_budget.BudgetUnavailable("Pagina HAUL temporaneamente non leggibile")
    return amazon_api._extract_haul_products_from_html(html_text, partner_tag=partner_tag)
