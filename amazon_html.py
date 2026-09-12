from __future__ import annotations

import re
from urllib.parse import parse_qsl, urlencode, urljoin, urlsplit, urlunsplit

from bs4 import BeautifulSoup

import amazon_api
import product_dedup


SHOWCASE_FAST_TIMEOUT = 5
SHOWCASE_FAST_MAX_ITEMS = 16
SHOWCASE_PAGES = (
    ("offerte", "https://www.amazon.it/deals"),
    ("piu-venduti", "https://www.amazon.it/gp/bestsellers/"),
    ("novita", "https://www.amazon.it/gp/new-releases/"),
    ("tendenze", "https://www.amazon.it/gp/movers-and-shakers/"),
)
_PRICE_RE = re.compile(r"(\d{1,3}(?:\.\d{3})*|\d+)[,.](\d{2})")
_DISCOUNT_RE = re.compile(r"-\s*(\d{1,2})\s*%")


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
    ]
    for candidate in candidates:
        value = _price(candidate)
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

    # Some deal cards expose the list price only in accessibility text.
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


def _extract_storefront_cards(html_text: str, partner_tag: str) -> list[dict]:
    """Parse product cards from Amazon deals/bestseller/storefront pages.

    The parser is intentionally local: no detail-page requests and no external
    search engines are used. Price data is trusted only when it is read from an
    explicit Amazon price node on the card.
    """
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
    """Fetch Vetrina from one direct Amazon showcase page, with one Amazon fallback.

    This path never calls Creators search, Google, Bing or DuckDuckGo. The first
    request targets an Amazon deals/bestseller/storefront page, which is not
    affected by the search-SERP circuit breaker. If that page yields too few
    cards, HAUL is used only as an Amazon-hosted safety fallback.
    """
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
                    # Preserve trusted generic card prices when that parser found
                    # an explicit Amazon base-price node.
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
