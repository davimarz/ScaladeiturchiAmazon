from __future__ import annotations

from typing import NotRequired, TypedDict


class Product(TypedDict, total=False):
    asin: str
    titolo: str
    link_affiliato: str
    detail_page_url: str
    immagine_url: str
    prezzo_finale: float | None
    prezzo_iniziale: float | None
    prezzo_verificato: bool
    sconto: str
    sconto_val: float
    size: str
    color: str
    sold_qty_label: str
    sold_qty_month: int
    sales_rank: int
    _amazon_position: int
    _fetched_at: float
    _source_label: str
    variants: list["Product"]


class SearchConfig(TypedDict):
    keyword: str
    sort: str
    prime_only: bool
