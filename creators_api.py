from __future__ import annotations

from typing import Iterable

import amazon_api


def search(
    keyword: str,
    sort_type: str,
    prime_only: bool,
    item_count: int,
    exclude_asins: Iterable[str] = (),
    cache_buster: str | None = None,
    partner_tag_override: str | None = None,
) -> list[dict]:
    kwargs = {
        "keyword": keyword,
        "sort_type": sort_type,
        "solo_spedizione_gratuita": bool(prime_only),
        "item_count": item_count,
        "exclude_asins": tuple(exclude_asins),
    }
    if cache_buster is not None:
        kwargs["_cache_buster"] = cache_buster
    if partner_tag_override is not None:
        kwargs["_partner_tag_override"] = partner_tag_override
    return amazon_api.ottieni_offerte_avanzate(**kwargs)
