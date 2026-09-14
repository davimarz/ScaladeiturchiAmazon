"""Boundary HAUL separato dal gateway generale."""
from __future__ import annotations

import http_client
from product_models import Product


def fetch_products(partner_tag: str) -> list[Product]:
    html_text = http_client.fetch_amazon_html(http_client.HAUL_STORE_URL)
    if not html_text:
        raise http_client.BudgetUnavailable("Pagina HAUL temporaneamente non leggibile")
    return list(
        http_client.extract_haul_products_from_html(
            html_text,
            partner_tag=partner_tag,
        )
        or []
    )
