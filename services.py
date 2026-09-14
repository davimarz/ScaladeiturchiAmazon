"""Small service facade for Streamlit orchestration.

Keeps app.py focused on state/UI while preserving existing catalog_service API.
"""
from __future__ import annotations

from typing import Iterable

import catalog_service
from product_models import Product


class HaulService:
    def get(self, count: int, token: str, seen: Iterable[str]) -> list[Product]:
        return catalog_service.get_haul_selection(count, token, seen)


class ShowcaseService:
    def get(self, count: int, token: str, seen: Iterable[str]) -> list[Product]:
        return catalog_service.get_showcase_selection(count, token, seen)


class SearchService:
    def search(
        self,
        keyword: str,
        sort_type: str,
        prime_only: bool,
        item_count: int,
        exclude_asins: Iterable[str] = (),
    ) -> list[Product]:
        return catalog_service.search_products(
            keyword=keyword,
            sort_type=sort_type,
            prime_only=prime_only,
            item_count=item_count,
            exclude_asins=exclude_asins,
        )


haul_service = HaulService()
showcase_service = ShowcaseService()
search_service = SearchService()
