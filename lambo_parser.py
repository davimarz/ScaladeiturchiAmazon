"""Importatore per la pagina Offerte Lambo."""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, as_completed
from urllib.parse import parse_qsl, urlencode, urlparse, urlunparse

import http_client
from product_models import Product

DEFAULT_LAMBO_URL = "https://www.amazon.it/deals?ref_=nav_cs_gb&bubble-id=deals-collection-lightning-deals"
LAMBO_POOL_PAGES = 4
LAMBO_PAGE_TIMEOUT = 6.0


def normalize_url(url: str) -> str:
    """Accetta solo pagine HTTPS di amazon.it."""
    value = str(url or "").strip()
    parsed = urlparse(value)
    host = (parsed.hostname or "").lower()
    if parsed.scheme != "https" or host not in {"amazon.it", "www.amazon.it"}:
        raise ValueError("Inserisci un link HTTPS valido di Amazon.it.")
    return urlunparse(parsed._replace(fragment=""))


def _lambo_urls(source_url: str) -> list[str]:
    base = normalize_url(source_url)
    parsed = urlparse(base)
    query = dict(parse_qsl(parsed.query, keep_blank_values=True))
    urls = [base]
    for page in range(2, LAMBO_POOL_PAGES + 1):
        page_query = dict(query)
        page_query["page"] = str(page)
        urls.append(urlunparse(parsed._replace(query=urlencode(page_query))))
    return urls


def _fetch_one(url: str, partner_tag: str) -> list[Product]:
    html_text = http_client.fetch_amazon_html(
        url,
        timeout=LAMBO_PAGE_TIMEOUT,
        single_attempt=True,
    )
    if not html_text:
        return []
    return list(
        http_client.extract_products_from_html(
            html_text,
            partner_tag=partner_tag,
        )
        or []
    )


def fetch_products(source_url: str, partner_tag: str) -> list[Product]:
    """Scansiona il link Offerte Lambo e deduplica i prodotti per ASIN."""
    products: list[Product] = []
    urls = _lambo_urls(source_url)

    with ThreadPoolExecutor(max_workers=len(urls)) as executor:
        futures = {
            executor.submit(_fetch_one, url, partner_tag): url
            for url in urls
        }
        for future in as_completed(futures):
            try:
                products.extend(future.result() or [])
            except Exception:
                continue

    unique: list[Product] = []
    seen: set[str] = set()
    for product in products:
        asin = str(product.get("asin") or "").strip().upper()
        if not asin or asin in seen:
            continue
        seen.add(asin)
        unique.append(product)

    if not unique:
        raise http_client.BudgetUnavailable("Pagina Offerte Lambo temporaneamente non leggibile")
    return unique
