"""Boundary della Vetrina Amazon.

Il parser HTML concreto resta in amazon_html per compatibilità, ma catalogo e
servizi dipendono da questo boundary dedicato invece che dal modulo generico.
"""
from __future__ import annotations

import amazon_html
from product_models import Product

SHOWCASE_PAGES = amazon_html.SHOWCASE_PAGES


def fetch_products(page_index: int, partner_tag: str, item_count: int = 12) -> list[Product]:
    return list(
        amazon_html.fetch_showcase_products_fast(
            page_index=page_index,
            partner_tag=partner_tag,
            item_count=item_count,
        )
        or []
    )
