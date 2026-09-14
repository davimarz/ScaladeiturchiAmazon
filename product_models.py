from __future__ import annotations

from enum import StrEnum
from typing import TypedDict


class PriceConfidence(StrEnum):
    MISSING = "missing"
    BASE_NODE = "base_price_node"
    VERIFIED_DETAIL = "verified_detail"


class PriceSource(StrEnum):
    CREATORS_API = "creators_api"
    AMAZON_DETAIL = "amazon_detail"
    AMAZON_CARD = "amazon_card"
    AMAZON_HAUL = "amazon_haul"
    UNKNOWN = "unknown"


TRUSTED_PRICE_CONFIDENCE = {
    PriceConfidence.BASE_NODE.value,
    PriceConfidence.VERIFIED_DETAIL.value,
}


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
    displayed_at: float
    price_source: str
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
    prime_source: str
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
