from __future__ import annotations

import json
import re
from typing import Any

from bs4 import BeautifulSoup

PRICE_RE = re.compile(r"(\d{1,3}(?:\.\d{3})*|\d+)[,.](\d{2})")
DISCOUNT_RE = re.compile(r"-\s*(\d{1,2})\s*%")


def parse_price(text: str | None) -> float | None:
    match = PRICE_RE.search(str(text or ""))
    if not match:
        return None
    try:
        return float(f"{match.group(1).replace('.', '')}.{match.group(2)}")
    except ValueError:
        return None


def numeric_price(value: Any) -> float | None:
    if isinstance(value, (int, float)):
        try:
            candidate = float(value)
            return candidate if 0 < candidate < 1_000_000 else None
        except (TypeError, ValueError, OverflowError):
            return None
    parsed = parse_price(str(value or ""))
    if parsed is not None:
        return parsed
    text = str(value or "").strip().replace("\xa0", " ")
    match = re.fullmatch(r"(?:€\s*)?(\d+(?:[.,]\d{1,2})?)(?:\s*€)?", text)
    if not match:
        return None
    try:
        candidate = float(match.group(1).replace(",", "."))
        return candidate if 0 < candidate < 1_000_000 else None
    except ValueError:
        return None


def price_from_element(element: Any) -> float | None:
    if element is None:
        return None
    candidates = [
        element.get_text(" ", strip=True),
        element.get("aria-label"),
        element.get("title"),
        element.get("data-a-price"),
        element.get("content"),
    ]
    for candidate in candidates:
        value = numeric_price(candidate)
        if value is not None:
            return value

    whole = element.select_one(".a-price-whole")
    fraction = element.select_one(".a-price-fraction")
    if whole:
        whole_digits = re.sub(r"\D", "", whole.get_text("", strip=True))
        fraction_digits = re.sub(
            r"\D",
            "",
            fraction.get_text("", strip=True) if fraction else "00",
        )
        if whole_digits:
            try:
                return float(
                    f"{whole_digits}.{(fraction_digits or '00')[:2].ljust(2, '0')}"
                )
            except ValueError:
                return None
    return None


def first_price(node: Any, selectors: tuple[str, ...]) -> float | None:
    for selector in selectors:
        for found in node.select(selector):
            value = price_from_element(found)
            if value is not None and value > 0:
                return value
    return None


def extract_card_prices(node: Any) -> tuple[float | None, float | None]:
    current_price = first_price(
        node,
        (
            ".a-price:not(.a-text-price):not([data-a-strike='true'])",
            "[data-a-color='price'] .a-price",
            "[data-a-color='price']",
            ".a-price.aok-align-center",
            ".a-price",
        ),
    )
    old_price = first_price(
        node,
        (
            ".a-text-price",
            ".a-price[data-a-strike='true']",
            "[data-a-strike='true']",
            "[data-a-color='secondary'] .a-price",
        ),
    )
    if old_price is None:
        for found in node.select("[aria-label], [title]"):
            text = f"{found.get('aria-label') or ''} {found.get('title') or ''}".lower()
            if any(
                marker in text
                for marker in (
                    "prezzo consigliato",
                    "prezzo precedente",
                    "list price",
                    "was:",
                )
            ):
                candidate = price_from_element(found)
                if candidate is not None:
                    old_price = candidate
                    break
    if old_price is not None and current_price is not None and old_price <= current_price:
        old_price = None
    return current_price, old_price


def _jsonld_offer_prices(soup: BeautifulSoup) -> tuple[float | None, float | None]:
    current_candidates: list[float] = []
    old_candidates: list[float] = []

    def visit(value: Any) -> None:
        if isinstance(value, list):
            for item in value:
                visit(item)
            return
        if not isinstance(value, dict):
            return
        type_value = value.get("@type")
        types = (
            {str(item).lower() for item in type_value}
            if isinstance(type_value, list)
            else {str(type_value or "").lower()}
        )
        if types & {"offer", "aggregateoffer"}:
            currency = str(value.get("priceCurrency") or "").upper()
            if not currency or currency == "EUR":
                for key in ("price", "lowPrice"):
                    candidate = numeric_price(value.get(key))
                    if candidate is not None:
                        current_candidates.append(candidate)
                        break
            specification = value.get("priceSpecification")
            specs = specification if isinstance(specification, list) else [specification]
            for spec in specs:
                if not isinstance(spec, dict):
                    continue
                label = " ".join(
                    str(spec.get(key) or "")
                    for key in ("@type", "priceType", "name")
                ).lower()
                if any(
                    marker in label
                    for marker in ("list", "strike", "was", "rrp", "recommended")
                ):
                    candidate = numeric_price(spec.get("price"))
                    if candidate is not None:
                        old_candidates.append(candidate)
        for child in value.values():
            if isinstance(child, (dict, list)):
                visit(child)

    for script in soup.select("script[type='application/ld+json']"):
        raw = script.string or script.get_text("", strip=True)
        if not raw:
            continue
        try:
            visit(json.loads(raw))
        except (json.JSONDecodeError, TypeError, ValueError):
            continue

    current = current_candidates[0] if current_candidates else None
    old = None
    if current is not None:
        above = sorted({round(value, 2) for value in old_candidates if value > current})
        old = above[0] if above else None
    return current, old


def extract_detail_prices(
    soup: BeautifulSoup,
    card_price: float | None = None,
) -> tuple[float | None, float | None, int]:
    price_scopes = (
        "#corePrice_feature_div",
        "#corePriceDisplay_desktop_feature_div",
        "#corePriceDisplay_mobile_feature_div",
        "#apex_offerDisplay_desktop",
        "#apex_offerDisplay_mobile",
        "#buybox",
        "#buyBoxAccordion",
        "#price",
        "[data-feature-name='corePrice']",
    )
    current_selectors = (
        ".priceToPay:not(.a-text-price)",
        ".apexPriceToPay:not(.a-text-price)",
        ".a-price[data-a-color='base']:not(.a-text-price):not([data-a-strike='true'])",
        ".a-price[data-a-color='price']:not(.a-text-price):not([data-a-strike='true'])",
        ".a-price:not(.a-text-price):not([data-a-strike='true'])",
        "#price_inside_buybox",
        "#priceblock_ourprice",
        "#priceblock_dealprice",
        "#priceblock_saleprice",
    )

    current = None
    current_node = None
    for scope_selector in price_scopes:
        scope = soup.select_one(scope_selector)
        if scope is None:
            continue
        for selector in current_selectors:
            for node in scope.select(selector):
                context = " ".join(
                    str(parent.get("id") or "") + " " + " ".join(parent.get("class") or [])
                    for parent in [node, *list(node.parents)[:4]]
                ).lower()
                if any(marker in context for marker in ("installment", "subscription", "sns-", "monthly")):
                    continue
                value = price_from_element(node)
                if value is not None:
                    current, current_node = value, node
                    break
            if current is not None:
                break
        if current is not None:
            break

    if current is None:
        for node in soup.select("span.a-price:not(.a-text-price):not([data-a-strike='true'])"):
            context = " ".join(
                str(parent.get("id") or "") + " " + " ".join(parent.get("class") or [])
                for parent in [node, *list(node.parents)[:5]]
            ).lower()
            if any(
                marker in context
                for marker in (
                    "installment",
                    "subscription",
                    "sns-",
                    "monthly",
                    "used",
                    "trade-in",
                )
            ):
                continue
            value = price_from_element(node)
            if value is not None:
                current, current_node = value, node
                break

    structured_current, structured_old = _jsonld_offer_prices(soup)
    if current is None:
        current = structured_current

    if current is None:
        for selector in (
            "meta[itemprop='price']",
            "[itemprop='price'][content]",
            "meta[property='product:price:amount']",
        ):
            value = price_from_element(soup.select_one(selector))
            if value is not None:
                current = value
                break

    if current is None and card_price is not None and card_price > 0:
        current = card_price

    old_candidates: list[float] = []
    for selector in (
        ".a-price.a-text-price",
        ".a-text-price",
        ".a-price[data-a-strike='true']",
        "[data-a-strike='true']",
        ".basisPrice .a-price",
        ".basisPrice",
    ):
        for node in soup.select(selector):
            value = price_from_element(node)
            if current is not None and value is not None and value > current:
                old_candidates.append(value)

    if structured_old is not None and current is not None and structured_old > current:
        old_candidates.append(structured_old)
    old = min(old_candidates) if old_candidates else None

    discount = 0
    if current is not None and old is not None and old > current:
        discount = int(round((old - current) / old * 100))
    if not discount:
        text_scope = (
            current_node.parent.get_text(" ", strip=True)
            if current_node is not None and current_node.parent is not None
            else ""
        )
        text_scope += " " + " ".join(
            node.get_text(" ", strip=True)
            for node in soup.select(
                "#corePrice_feature_div, #apex_offerDisplay_desktop, #apex_offerDisplay_mobile, #price"
            )[:3]
        )
        match = DISCOUNT_RE.search(text_scope) or re.search(
            r"(\d{1,2})\s*%\s*(?:di\s+)?sconto",
            text_scope,
            re.I,
        )
        if match:
            discount = int(match.group(1))

    return current, old, discount
