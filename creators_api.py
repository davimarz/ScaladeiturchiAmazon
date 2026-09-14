from __future__ import annotations

from typing import Iterable

import amazon_api
import app_constants
from product_models import PriceSource, Product


PRIMARY_RETRY_SECONDS = amazon_api.CREATORS_403_COOLDOWN


def primary_source_policy() -> dict[str, object]:
    """Policy applicata alla ricerca: Creators API prima, fallback solo temporaneo."""
    return {
        "primary": "creators_api",
        "primary_available": not amazon_api.creators_circuit_open(),
        "fallback_enabled": amazon_api.html_fallback_enabled(),
        "retry_seconds": PRIMARY_RETRY_SECONDS,
        "partner_tag_configured": bool(amazon_api.get_partner_tag()),
    }


def _normalize_product(product: dict) -> Product:
    normalized: Product = dict(product)
    source = str(normalized.get("source") or "").strip().lower()
    if source.startswith("creators_api"):
        normalized.setdefault("price_source", PriceSource.CREATORS_API.value)
    return normalized


def search(
    keyword: str,
    sort_type: str,
    prime_only: bool,
    item_count: int,
    exclude_asins: Iterable[str] = (),
    cache_buster: str | None = None,
    partner_tag_override: str | None = None,
) -> list[Product]:
    # amazon_api tenta Creators API per prima. In caso di AssociateNotEligible
    # apre un circuit breaker temporaneo; dopo un'ora il primary viene ritentato.
    # Il fallback non rimuove né modifica credenziali o Partner Tag.
    if PRIMARY_RETRY_SECONDS != app_constants.CREATORS_PRIMARY_RETRY_SECONDS:
        raise RuntimeError("Creators primary retry policy mismatch")

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
    return [
        _normalize_product(product)
        for product in (amazon_api.ottieni_offerte_avanzate(**kwargs) or [])
    ]
