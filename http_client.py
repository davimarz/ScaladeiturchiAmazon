"""Public HTTP boundary for Amazon-hosted HTML flows.

The legacy implementation still lives in amazon_api while it is progressively
split, but callers outside that compatibility module no longer depend on its
private HTTP/parser functions directly.
"""
from __future__ import annotations

from typing import Any

import amazon_api
import telemetry

HAUL_STORE_URL = amazon_api.HAUL_STORE_URL
BudgetUnavailable = amazon_api.api_budget.BudgetUnavailable
LOGGER = amazon_api.LOGGER
prime_status = amazon_api.prime_status


def fetch_amazon_html(url: str, *, timeout: float | None = None, single_attempt: bool = False) -> str:
    telemetry.increment("amazon_http_requests")
    return amazon_api._fetch_amazon_html(
        url,
        timeout=timeout,
        single_attempt=single_attempt,
    )


def extract_products_from_html(
    html_text: str,
    *,
    partner_tag: str,
    min_price: float | None = None,
    max_price: float | None = None,
    require_prime: bool = False,
) -> list[dict[str, Any]]:
    return amazon_api._extract_products_from_html(
        html_text,
        partner_tag=partner_tag,
        min_price=min_price,
        max_price=max_price,
        require_prime=require_prime,
    )


def extract_haul_products_from_html(html_text: str, *, partner_tag: str) -> list[dict[str, Any]]:
    return amazon_api._extract_haul_products_from_html(
        html_text,
        partner_tag=partner_tag,
    )
