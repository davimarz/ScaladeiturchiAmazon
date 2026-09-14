from __future__ import annotations

from typing import TypedDict


class Product(TypedDict, total=False):
    asin: str
    titolo: str
    link_affiliato: str
    detail_page_url: str
    immagine_url: str
    immagine_fallback_urls: list[str]
    prezzo_finale: float | None
    prezzo_iniziale: float | None
    prezzo_verificato: bool
    price_verified_at: float
    detail_verified_at: float
    sconto: str
    sconto_val: float
    size: str
    color: str
    sold_qty_label: str
    sold_qty_month: int
    sales_rank: int
    prime: bool
    is_prime: bool
    prime_detail_verified: bool
    source: str
    _amazon_position: int
    _fetched_at: float
    _source_label: str
    _serp_price_confidence: str
    _search_prezzo_finale: float | None
    _search_prezzo_iniziale: float | None
    _price_displayable: bool
    _price_display_source: str
    variants: list["Product"]


class SearchConfig(TypedDict):
    keyword: str
    sort: str
    prime_only: bool
