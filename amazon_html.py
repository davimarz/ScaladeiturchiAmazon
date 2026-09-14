from __future__ import annotations

import re
import time
from urllib.parse import parse_qsl, urlencode, urljoin, urlsplit, urlunsplit

from bs4 import BeautifulSoup

import app_constants
import http_client
import price_parser
import product_dedup
from product_models import Product

SHOWCASE_FAST_TIMEOUT = 5
SHOWCASE_DETAIL_TIMEOUT = 6
SHOWCASE_FAST_MAX_ITEMS = 16
SHOWCASE_PAGES = (
    ("offerte", "https://www.amazon.it/deals"),
    ("piu-venduti", "https://www.amazon.it/gp/bestsellers/"),
    ("novita", "https://www.amazon.it/gp/new-releases/"),
    ("tendenze", "https://www.amazon.it/gp/movers-and-shakers/"),
)
_DISCOUNT_RE = re.compile(r"-\s*(\d{1,2})\s*%")
_ASIN_URL_RE = re.compile(r"/(?:dp|gp/product|gp/aw/d)/([A-Z0-9]{10})(?:[/?#]|$)", re.I)


def fetch_haul_products(partner_tag: str) -> list[Product]:
    html_text = http_client.fetch_amazon_html(http_client.HAUL_STORE_URL)
    if not html_text:
        raise http_client.BudgetUnavailable("Pagina HAUL temporaneamente non leggibile")
    return list(http_client.extract_haul_products_from_html(html_text, partner_tag=partner_tag))


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
        if re.fullmatch(
            r"[A-Z0-9]{10}",
            str(node.get("data-asin") or "").strip().upper(),
        )
    }
    return next(iter(candidates)) if len(candidates) == 1 else ""


def enrich_product_detail_fast(product: Product) -> Product:
    """Arricchisce una card selezionata con una sola richiesta dettaglio Amazon."""
    enriched: Product = {
        key: value for key, value in dict(product or {}).items() if key != "variants"
    }
    asin = str(enriched.get("asin") or "").strip().upper()
    if not re.fullmatch(r"[A-Z0-9]{10}", asin):
        return enriched

    detail_url = f"https://www.amazon.it/dp/{asin}?th=1&psc=1"
    html_text = http_client.fetch_amazon_html(
        detail_url,
        timeout=SHOWCASE_DETAIL_TIMEOUT,
        single_attempt=True,
    )
    if not html_text:
        return enriched

    soup = BeautifulSoup(html_text, "html.parser")
    actual_asin = _detail_identity_asin(soup)
    if actual_asin != asin:
        http_client.LOGGER.info(
            "Vetrina detail asin=%s reason=identity_%s",
            asin,
            "mismatch" if actual_asin else "unconfirmed",
        )
        return enriched

    card_price = None
    if str(enriched.get("_serp_price_confidence") or "").lower() == "base_price_node":
        card_price = price_parser.numeric_price(enriched.get("prezzo_finale"))

    current, old, discount = price_parser.extract_detail_prices(
        soup,
        card_price=card_price,
    )

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
    else:
        meta_image = soup.select_one("meta[property='og:image']")
        if meta_image:
            image_url = str(meta_image.get("content") or "").strip()
            if image_url.startswith("https://"):
                enriched["immagine_url"] = image_url

    try:
        prime = bool(http_client.prime_status.confirmed(html_text, asin))
        enriched["is_prime"] = prime
        enriched["prime"] = prime
        enriched["prime_detail_verified"] = prime
    except Exception:
        pass

    verified_at = time.time()
    enriched["detail_verified_at"] = verified_at
    if current is not None and current > 0:
        enriched["prezzo_finale"] = float(current)
        enriched["prezzo_iniziale"] = (
            float(old) if old is not None and old > current else None
        )
        enriched["prezzo_verificato"] = True
        enriched["price_verified_at"] = verified_at
        enriched["_serp_price_confidence"] = "base_price_node"
        enriched["sconto_val"] = int(discount or 0)
        enriched["sconto"] = f"-{int(discount)}%" if discount else ""
        enriched["source"] = "amazon_detail_fast_verified"
    else:
        enriched.setdefault("prezzo_verificato", False)
        enriched["source"] = "amazon_detail_fast_unverified"

    http_client.LOGGER.info(
        "Vetrina detail asin=%s price=%s old=%s discount=%s prime=%s",
        asin,
        f"{current:.2f}" if current is not None else "n/a",
        f"{old:.2f}" if old is not None else "n/a",
        discount,
        enriched.get("prime_detail_verified", "n/a"),
    )
    return enriched


def _extract_storefront_cards(html_text: str, partner_tag: str) -> list[Product]:
    """Parse product cards from Amazon deals/bestseller/storefront pages."""
    soup = BeautifulSoup(html_text or "", "html.parser")
    products: list[Product] = []
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

        title = _text(
            node,
            (
                "h2 a span",
                "h2 span",
                ".a-size-base-plus.a-color-base.a-text-normal",
                ".p13n-sc-truncate-desktop-type2",
                ".p13n-sc-truncate",
                "a.a-link-normal span.a-text-normal",
            ),
        )
        image_node = node.select_one("img[src]")
        image_url = str(image_node.get("src") or "").strip() if image_node else ""
        if not title and image_node:
            title = " ".join(str(image_node.get("alt") or "").split())
        if len(title) < 4:
            continue

        final_price, old_price = price_parser.extract_card_prices(node)

        discount = ""
        if old_price is not None and final_price is not None:
            pct = int(round((old_price - final_price) / old_price * 100))
            if pct > 0:
                discount = f"-{pct}%"
        if not discount:
            discount_match = _DISCOUNT_RE.search(node.get_text(" ", strip=True))
            if discount_match:
                discount = f"-{int(discount_match.group(1))}%"

        products.append(
            {
                "asin": asin,
                "titolo": title,
                "immagine_url": image_url,
                "prezzo_finale": final_price,
                "prezzo_iniziale": old_price,
                "prezzo_verificato": False,
                "_serp_price_confidence": (
                    "base_price_node" if final_price is not None else "missing"
                ),
                "sconto": discount,
                "sconto_val": int(discount.strip("-%")) if discount else 0,
                "link_affiliato": link,
                "detail_page_url": link,
                "prime": bool(node.select_one(".a-icon-prime")),
                "source": "amazon_showcase_card",
            }
        )
        seen.add(asin)

    return list(product_dedup.unique(products))


def fetch_showcase_products_fast(
    page_index: int,
    partner_tag: str,
    item_count: int = 12,
) -> list[Product]:
    """Fetch Vetrina from one direct Amazon showcase page, with one Amazon fallback."""
    tag = str(partner_tag or "").strip()
    if not tag:
        return []
    target = max(1, min(int(item_count or 12), SHOWCASE_FAST_MAX_ITEMS))
    source_name, url = SHOWCASE_PAGES[int(page_index) % len(SHOWCASE_PAGES)]

    html_text = http_client.fetch_amazon_html(
        url,
        timeout=SHOWCASE_FAST_TIMEOUT,
        single_attempt=True,
    )
    products: list[Product] = []
    if html_text:
        products.extend(_extract_storefront_cards(html_text, tag))
        if len(products) < target:
            try:
                generic_products = http_client.extract_products_from_html(
                    html_text,
                    partner_tag=tag,
                    min_price=None,
                    max_price=None,
                    require_prime=False,
                )
                for product in generic_products:
                    copy: Product = dict(product)
                    if (
                        copy.get("prezzo_finale") is not None
                        and not copy.get("_serp_price_confidence")
                    ):
                        copy["_serp_price_confidence"] = "base_price_node"
                    products.append(copy)
            except Exception:
                pass
    unique_products = product_dedup.unique(products)
    priced_count = sum(
        1 for product in unique_products if product.get("prezzo_finale") is not None
    )
    http_client.LOGGER.info(
        "Vetrina direct Amazon source=%s products=%s priced=%s target=%s",
        source_name,
        len(unique_products),
        priced_count,
        target,
    )

    if len(unique_products) < app_constants.DISPLAY_BATCH_SIZE:
        haul_html = http_client.fetch_amazon_html(
            http_client.HAUL_STORE_URL,
            timeout=SHOWCASE_FAST_TIMEOUT,
            single_attempt=True,
        )
        if haul_html:
            try:
                fallback = http_client.extract_haul_products_from_html(
                    haul_html,
                    partner_tag=tag,
                )
                for product in fallback:
                    copy: Product = dict(product)
                    copy["source"] = "amazon_haul_showcase_fallback"
                    products.append(copy)
            except Exception:
                pass
        unique_products = product_dedup.unique(products)
        http_client.LOGGER.info(
            "Vetrina Amazon fallback=haul products_total=%s priced=%s",
            len(unique_products),
            sum(
                1
                for product in unique_products
                if product.get("prezzo_finale") is not None
            ),
        )

    result = product_dedup.unique(products)
    if not result:
        raise http_client.BudgetUnavailable("Vetrina Amazon temporaneamente non leggibile")
    return list(result[:target])


def fetch_search_products_fast(
    keyword: str,
    partner_tag: str,
    item_count: int = SHOWCASE_FAST_MAX_ITEMS,
) -> list[Product]:
    del keyword
    return fetch_showcase_products_fast(0, partner_tag, item_count)
