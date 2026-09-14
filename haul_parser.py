"""Boundary HAUL separato dal gateway generale.

La logica legacy di parsing resta compatibile con amazon_api, ma le chiamate nuove
passano da questo modulo così HAUL può evolvere senza allargare amazon_gateway.
"""
from __future__ import annotations

import amazon_api
from product_models import Product


def fetch_products(partner_tag: str) -> list[Product]:
    html_text = amazon_api._fetch_amazon_html(amazon_api.HAUL_STORE_URL)
    if not html_text:
        raise amazon_api.api_budget.BudgetUnavailable(
            "Pagina HAUL temporaneamente non leggibile"
        )
    return list(
        amazon_api._extract_haul_products_from_html(
            html_text,
            partner_tag=partner_tag,
        )
        or []
    )
