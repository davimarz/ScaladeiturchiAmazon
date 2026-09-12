from __future__ import annotations

import json
import re
from urllib.parse import parse_qsl, urlencode, urljoin, urlsplit, urlunsplit

from bs4 import BeautifulSoup

import amazon_api
import product_dedup


SHOWCASE_FAST_TIMEOUT = 5
SHOWCASE_DETAIL_TIMEOUT = 6
SHOWCASE_FAST_MAX_ITEMS = 16
SHOWCASE_PAGES = (
    ("offerte", "https://www.amazon.it/deals"),
    ("piu-venduti", "https://www.amazon.it/gp/bestsellers/"),
    ("novita", "https://www.amazon.it/gp/new-releases/"),
    ("tendenze", "https://www.amazon.it/gp/movers-and-shakers/"),
)
_PRICE_RE = re.compile(r"(\d{1,3}(?:\.\d{3})*|\d+)[,.](\d{2})")
_DISCOUNT_RE = re.compile(r"-\s*(\d{1,2})\s*%")
_ASIN_URL_RE = re.compile(r"/(?:dp|gp/product|gp/aw/d)/([A-Z0-9]{10})(?:[/?#]|$)", re.I)


def fetch_haul_products(partner_tag: str) -> list[dict]:
    html_text = amazon_api._fetch_amazon_html(amazon_api.HAUL_STORE_URL)
    if not html_text:
        raise amazon_api.api_budget.BudgetUnavailable("Pagina HAUL temporaneamente non leggibile")
    return amazon_api._extract_haul_products_from_html(html_text, partner_tag=partner_tag)


def _price(text: str | None) -> float | None:
    match = _PRICE_RE.search(str(text or ""))
    if not match:
        return None
    try:
        return float(f"{match.group(1).replace('.', '')}.{match.group(2)}")
    except ValueError:
        return None


def _numeric_price(value) -> float | None:
    if isinstance(value, (int, float)):
        try:
            candidate = float(value)
            return candidate if 0 < candidate < 1_000_000 else None
        except (TypeError, ValueError, OverflowError):
            return None
    parsed = _price(str(value or ""))
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


def _affiliate_url(raw_url: str, partner_tag: str) -> str:
    absolute = urljoin("https://www.amazon.it", str(raw_url or ""))
    try:
        parsed = urlsplit(absolute)
    except Exception:
        return ""
    host = (parsed.hostname or "").lower()
    if parsed.scheme != "https" or not (host == "amazon.it" or host.endswith(".amazon.it")):
        return ""
    query = dict(parse_qsl(parsed.query, keep_blank_values=True))
    if partner_tag:
        query["tag"] = partner_tag
    return urlunsplit((parsed.scheme, parsed.netloc, parsed.path, urlencode(query), ""))


def _text(node, selectors: tuple[str, ...]) -> str:
    for selector in selectors:
        found = node.select_one(selector)
        if found:
            value = " ".join(found.get_text(" ", strip=True).split())
            if value:
                return value
    return ""


def _price_from_element(element) -> float | None:
    """Read an Amazon price from visible text, a11y text or split price spans."""
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
        value = _numeric_price(candidate)
        if value is not None:
            return value

    whole = element.select_one(".a-price-whole")
    fraction = element.select_one(".a-price-fraction")
    if whole:
        whole_digits = re.sub(r"\D", "", whole.get_text("", strip=True))
        fraction_digits = re.sub(r"\D", "", fraction.get_text("", strip=True) if fraction else "00")
        if whole_digits:
            try:
                return float(f"{whole_digits}.{(fraction_digits or '00')[:2].ljust(2, '0')}")
            except ValueError:
                return None
    return None


def _first_price(node, selectors: tuple[str, ...]) -> float | None:
    for selector in selectors:
        for found in node.select(selector):
            value = _price_from_element(found)
            if value is not None and value > 0:
                return value
    return None


def _extract_card_prices(node) -> tuple[float | None, float | None]:
    """Extract current/list price across Amazon deals and ranking card layouts."""
    current_price = _first_price(node, (
        ".a-price:not(.a-text-price):not([data-a-strike='true'])",
        "[data-a-color='price'] .a-price",
        "[data-a-color='price']",
        ".a-price.aok-align-center",
        ".a-price",
    ))

    old_price = _first_price(node, (
        ".a-text-price",
        ".a-price[data-a-strike='true']",
        "[data-a-strike='true']",
        "[data-a-color='secondary'] .a-price",
    ))

    if old_price is None:
        for found in node.select("[aria-label], [title]"):
            text = f"{found.get('aria-label') or ''} {found.get('title') or ''}".lower()
            if any(marker in text for marker in ("prezzo consigliato", "prezzo precedente", "list price", "was:")):
                candidate = _price_from_element(found)
                if candidate is not None:
                    old_price = candidate
                    break

    if old_price is not None and current_price is not None and old_price <= current_price:
        old_price = None
    return current_price, old_price


def _asin_from_url(url: str) -> str:
    match = _ASIN_URL_RE.search(str(url or ""))
    return match.group(1).upper() if match else ""


def _detail_identity_asin(soup: BeautifulSoup) -> str:
    hidden = soup.select_one("input#ASIN, input[name='ASIN']")
    if hidden:
        value = str(hidden.get("value") or "").strip().upper()
        if re.fullmatch(r"[A-Z0-9]{10}", value):
            return value

    for selector, attr in (
        ("link[rel='canonical']", "href"),
        ("meta[property='og:url']", "content"),
    ):
        node = soup.select_one(selector)
        if node:
            value = _asin_from_url(str(node.get(attr) or ""))
            if value:
                return value

    candidates = {
        str(node.get("data-asin") or "").strip().upper()
        for node in soup.select("[data-asin]")
        if re.fullmatch(r"[A-Z0-9]{10}", str(node.get("data-asin") or "").strip().upper())
    }
    return next(iter(candidates)) if len(candidates) == 1 else ""


def _jsonld_offer_prices(soup: BeautifulSoup) -> tuple[float | None, float | None]:
    current_candidates: list[float] = []
    old_candidates: list[float] = []

    def visit(value) -> None:
        if isinstance(value, list):
            for item in value:
                visit(item)
            return
        if not isinstance(value, dict):
            return

        type_value = value.get("@type")
        types = {str(item).lower() for item in type_value} if isinstance(type_value, list) else {str(type_value or "").lower()}
        if types & {"offer", "aggregateoffer"}:
            currency = str(value.get("priceCurrency") or "").upper()
            if not currency or currency == "EUR":
                for key in ("price", "lowPrice"):
                    candidate = _numeric_price(value.get(key))
                    if candidate is not None:
                        current_candidates.append(candidate)
                        break

            specification = value.get("priceSpecification")
            specs = specification if isinstance(specification, list) else [specification]
            for spec in specs:
                if not isinstance(spec, dict):
                    continue
                label = " ".join(str(spec.get(key) or "") for key in ("@type", "priceType", "name")).lower()
                if any(marker in label for marker in ("list", "strike", "was", "rrp", "recommended")):
                    candidate = _numeric_price(spec.get("price"))
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


def _detail_prices(soup: BeautifulSoup, card_price: float | None = None) -> tuple[float | None, float | None, int]:
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
                value = _price_from_element(node)
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
            if any(marker in context for marker in ("installment", "subscription", "sns-", "monthly", "used", "trade-in")):
                continue
            value = _price_from_element(node)
            if value is not None:
                current, current_node = value, node
                break

    structured_current, structured_old = _jsonld_offer_prices(soup)
    if current is None:
        current = structured_current

    if current is None:
        for selector in ("meta[itemprop='price']", "[itemprop='price'][content]", "meta[property='product:price:amount']"):
            node = soup.select_one(selector)
            value = _price_from_element(node)
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
            value = _price_from_element(node)
            if current is not None and value is not None and value > current:
                old_candidates.append(value)

    if structured_old is not None and current is not None and structured_old > current:
        old_candidates.append(structured_old)
    old = min(old_candidates) if old_candidates else None

    discount = 0
    if current is not None and old is not None and old > current:
        discount = int(round((old - current) / old * 100))
    if not discount:
        text_scope = current_node.parent.get_text(" ", strip=True) if current_node is not None and current_node.parent is not None else ""
        text_scope += " " + " ".join(
            node.get_text(" ", strip=True)
            for node in soup.select("#corePrice_feature_div, #apex_offerDisplay_desktop, #apex_offerDisplay_mobile, #price")[:3]
        )
        match = _DISCOUNT_RE.search(text_scope) or re.search(r"(\d{1,2})\s*%\s*(?:di\s+)?sconto", text_scope, re.I)
        if match:
            discount = int(match.group(1))

    return current, old, discount


def enrich_product_detail_fast(product: dict) -> dict:
    """Enrich one selected showcase product with one direct Amazon detail request.

    This parser accepts both standard product pages and HAUL layouts. It verifies
    the ASIN via hidden input, canonical URL, OpenGraph URL or a unique data-asin
    before trusting price data. No external search engine is involved.
    """
    enriched = {key: value for key, value in dict(product or {}).items() if key != "variants"}
    asin = str(enriched.get("asin") or "").strip().upper()
    if not re.fullmatch(r"[A-Z0-9]{10}", asin):
        return enriched

    detail_url = f"https://www.amazon.it/dp/{asin}?th=1&psc=1"
    html_text = amazon_api._fetch_amazon_html(
        detail_url,
        timeout=SHOWCASE_DETAIL_TIMEOUT,
        single_attempt=True,
    )
    if not html_text:
        return enriched

    soup = BeautifulSoup(html_text, "html.parser")
    actual_asin = _detail_identity_asin(soup)
    if actual_asin != asin:
        amazon_api.LOGGER.info("Vetrina detail asin=%s reason=identity_%s", asin, "mismatch" if actual_asin else "unconfirmed")
        return enriched

    card_price = None
    if str(enriched.get("_serp_price_confidence") or "").lower() == "base_price_node":
        card_price = _numeric_price(enriched.get("prezzo_finale"))

    current, old, discount = _detail_prices(soup, card_price=card_price)

    title = _text(soup, ("#productTitle", "h1"))
    if not title:
        meta_title = soup.select_one("meta[property='og:title']")
        title = " ".join(str(meta_title.get("content") or "").split()) if meta_title else ""
    if title:
        enriched["titolo"] = title

    image = soup.select_one("#landingImage, #imgBlkFront, img[data-a-dynamic-image]")
    if image is not None:
        image_url = str(image.get("data-old-hires") or image.get("src") or "").strip()
        if image_url.startswith("https://"):
            enriched["immagine_url"] = image_url
    elif soup.select_one("meta[property='og:image']"):
        image_url = str(soup.select_one("meta[property='og:image']").get("content") or "").strip()
        if image_url.startswith("https://"):
            enriched["immagine_url"] = image_url

    try:
        prime = bool(amazon_api.prime_status.confirmed(html_text, asin))
        enriched["is_prime"] = prime
        enriched["prime"] = prime
        enriched["prime_detail_verified"] = prime
    except Exception:
        pass

    if current is not None and current > 0:
        enriched["prezzo_finale"] = float(current)
        enriched["prezzo_iniziale"] = float(old) if old is not None and old > current else None
        enriched["prezzo_verificato"] = True
        enriched["_serp_price_confidence"] = "base_price_node"
        enriched["sconto_val"] = int(discount or 0)
        enriched["sconto"] = f"-{int(discount)}%" if discount else ""
        enriched["source"] = "amazon_detail_fast_verified"
    else:
        enriched.setdefault("prezzo_verificato", False)
        enriched["source"] = "amazon_detail_fast_unverified"

    amazon_api.LOGGER.info(
        "Vetrina detail asin=%s price=%s old=%s discount=%s prime=%s",
        asin,
        f"{current:.2f}" if current is not None else "n/a",
        f"{old:.2f}" if old is not None else "n/a",
        discount,
        enriched.get("prime_detail_verified", "n/a"),
    )
    return enriched


def _extract_storefront_cards(html_text: str, partner_tag: str) -> list[dict]:
    """Parse product cards from Amazon deals/bestseller/storefront pages."""
    soup = BeautifulSoup(html_text or "", "html.parser")
    products: list[dict] = []
    seen: set[str] = set()

    for node in soup.select("[data-asin]"):
        asin = str(node.get("data-asin") or "").strip().upper()
        if len(asin) != 10 or not asin.isalnum() or asin in seen:
            continue

        link_node = (
            node.select_one("a[href*='/dp/']")
            or node.select_one("a[href*='/gp/product/']")
            or node.select_one("a.a-link-normal[href]")
        )
        if not link_node:
            continue
        link = _affiliate_url(str(link_node.get("href") or ""), partner_tag)
        if not link:
            continue

        title = _text(node, (
            "h2 a span",
            "h2 span",
            ".a-size-base-plus.a-color-base.a-text-normal",
            ".p13n-sc-truncate-desktop-type2",
            ".p13n-sc-truncate",
            "a.a-link-normal span.a-text-normal",
        ))
        image_node = node.select_one("img[src]")
        image_url = str(image_node.get("src") or "").strip() if image_node else ""
        if not title and image_node:
            title = " ".join(str(image_node.get("alt") or "").split())
        if len(title) < 4:
            continue

        final_price, old_price = _extract_card_prices(node)

        discount = ""
        if old_price is not None and final_price is not None:
            pct = int(round((old_price - final_price) / old_price * 100))
            if pct > 0:
                discount = f"-{pct}%"
        if not discount:
            discount_match = _DISCOUNT_RE.search(node.get_text(" ", strip=True))
            if discount_match:
                discount = f"-{int(discount_match.group(1))}%"

        products.append({
            "asin": asin,
            "titolo": title,
            "immagine_url": image_url,
            "prezzo_finale": final_price,
            "prezzo_iniziale": old_price,
            "prezzo_verificato": False,
            "_serp_price_confidence": "base_price_node" if final_price is not None else "missing",
            "sconto": discount,
            "sconto_val": int(discount.strip("-%")) if discount else 0,
            "link_affiliato": link,
            "detail_page_url": link,
            "prime": bool(node.select_one(".a-icon-prime")),
            "source": "amazon_showcase_card",
        })
        seen.add(asin)

    return product_dedup.unique(products)


def fetch_showcase_products_fast(page_index: int, partner_tag: str, item_count: int = 12) -> list[dict]:
    """Fetch Vetrina from one direct Amazon showcase page, with one Amazon fallback."""
    tag = str(partner_tag or "").strip()
    if not tag:
        return []
    target = max(1, min(int(item_count or 12), SHOWCASE_FAST_MAX_ITEMS))
    source_name, url = SHOWCASE_PAGES[int(page_index) % len(SHOWCASE_PAGES)]

    html_text = amazon_api._fetch_amazon_html(
        url,
        timeout=SHOWCASE_FAST_TIMEOUT,
        single_attempt=True,
    )
    products: list[dict] = []
    if html_text:
        products.extend(_extract_storefront_cards(html_text, tag))
        if len(products) < target:
            try:
                generic_products = amazon_api._extract_products_from_html(
                    html_text,
                    partner_tag=tag,
                    min_price=None,
                    max_price=None,
                    require_prime=False,
                )
                for product in generic_products:
                    copy = dict(product)
                    if copy.get("prezzo_finale") is not None and not copy.get("_serp_price_confidence"):
                        copy["_serp_price_confidence"] = "base_price_node"
                    products.append(copy)
            except Exception:
                pass
    unique_products = product_dedup.unique(products)
    priced_count = sum(1 for product in unique_products if product.get("prezzo_finale") is not None)
    amazon_api.LOGGER.info(
        "Vetrina direct Amazon source=%s products=%s priced=%s target=%s",
        source_name,
        len(unique_products),
        priced_count,
        target,
    )

    if len(unique_products) < 4:
        haul_html = amazon_api._fetch_amazon_html(
            amazon_api.HAUL_STORE_URL,
            timeout=SHOWCASE_FAST_TIMEOUT,
            single_attempt=True,
        )
        if haul_html:
            try:
                fallback = amazon_api._extract_haul_products_from_html(haul_html, partner_tag=tag)
                for product in fallback:
                    copy = dict(product)
                    copy["source"] = "amazon_haul_showcase_fallback"
                    products.append(copy)
            except Exception:
                pass
        unique_products = product_dedup.unique(products)
        amazon_api.LOGGER.info(
            "Vetrina Amazon fallback=haul products_total=%s priced=%s",
            len(unique_products),
            sum(1 for product in unique_products if product.get("prezzo_finale") is not None),
        )

    result = product_dedup.unique(products)
    if not result:
        raise amazon_api.api_budget.BudgetUnavailable("Vetrina Amazon temporaneamente non leggibile")
    return result[:target]


# Kept for compatibility with older imports. It is intentionally Amazon-only.
def fetch_search_products_fast(keyword: str, partner_tag: str, item_count: int = SHOWCASE_FAST_MAX_ITEMS) -> list[dict]:
    del keyword
    return fetch_showcase_products_fast(0, partner_tag, item_count)
