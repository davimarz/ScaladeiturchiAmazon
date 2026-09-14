"""Public HTTP boundary for Amazon-hosted HTML flows.

The legacy transport still lives in amazon_api while it is progressively split.
This module classifies outcomes for telemetry and keeps callers off private HTTP
functions as much as possible.
"""
from __future__ import annotations

from typing import Any

import amazon_api
import telemetry

HAUL_STORE_URL = amazon_api.HAUL_STORE_URL
BudgetUnavailable = amazon_api.api_budget.BudgetUnavailable
LOGGER = amazon_api.LOGGER
prime_status = amazon_api.prime_status


class AmazonHtmlError(RuntimeError):
    pass


class AmazonBlocked(AmazonHtmlError):
    pass


class AmazonEmptyResponse(AmazonHtmlError):
    pass


def classify_html(html_text: str | None) -> str:
    if not html_text:
        return "empty"
    lowered = html_text.lower()
    if "captcha" in lowered or "robot check" in lowered or "inserisci i caratteri" in lowered:
        return "blocked"
    if "503 service unavailable" in lowered or "service unavailable" in lowered:
        return "service_unavailable"
    return "ok"


def fetch_amazon_html(
    url: str,
    *,
    timeout: float | None = None,
    single_attempt: bool = False,
) -> str:
    telemetry.increment("amazon_http_requests")
    try:
        html_text = amazon_api._fetch_amazon_html(
            url,
            timeout=timeout,
            single_attempt=single_attempt,
        )
    except Exception as exc:
        telemetry.increment(f"amazon_http_exception_{type(exc).__name__}")
        raise

    classification = classify_html(html_text)
    telemetry.increment(f"amazon_http_result_{classification}")
    if classification in {"blocked", "service_unavailable"}:
        LOGGER.warning("amazon_html_unusable reason=%s", classification)
        return ""
    return str(html_text or "")


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


def extract_haul_products_from_html(
    html_text: str,
    *,
    partner_tag: str,
) -> list[dict[str, Any]]:
    return amazon_api._extract_haul_products_from_html(
        html_text,
        partner_tag=partner_tag,
    )
