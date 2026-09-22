"""Boundary HAUL separato dal gateway generale."""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, as_completed
from urllib.parse import urlencode

import http_client
from product_models import Product

# Amazon HAUL carica il catalogo in blocchi. Interroghiamo piu viste della
# stessa vetrina e poi deduplichiamo per ASIN, mantenendo comunque un numero
# contenuto di richieste per non rallentare il rendering della pagina.
HAUL_POOL_PAGES = 4
HAUL_PAGE_TIMEOUT = 6.0


def _haul_urls() -> list[str]:
    base = http_client.HAUL_STORE_URL.rstrip("/")
    urls = [f"{base}?ref_=nav_cs_hul_disb"]
    for page in range(2, HAUL_POOL_PAGES + 1):
        query = urlencode({"ref_": "nav_cs_hul_disb", "page": page})
        urls.append(f"{base}?{query}")
    return urls


def _fetch_one(url: str, partner_tag: str) -> list[Product]:
    html_text = http_client.fetch_amazon_html(
        url,
        timeout=HAUL_PAGE_TIMEOUT,
        single_attempt=True,
    )
    if not html_text:
        return []
    return list(
        http_client.extract_haul_products_from_html(
            html_text,
            partner_tag=partner_tag,
        )
        or []
    )


def fetch_products(partner_tag: str) -> list[Product]:
    """Costruisce un pool HAUL ampio senza aumentare le card visibili.

    Le viste vengono richieste in parallelo, quindi il costo di rete resta
    vicino a quello della richiesta piu lenta. I risultati sono deduplicati
    per ASIN prima di arrivare al campionamento casuale del catalog service.
    """
    products: list[Product] = []
    urls = _haul_urls()

    with ThreadPoolExecutor(max_workers=len(urls)) as executor:
        futures = {
            executor.submit(_fetch_one, url, partner_tag): url
            for url in urls
        }
        for future in as_completed(futures):
            try:
                products.extend(future.result() or [])
            except Exception:
                # Una singola vista bloccata da Amazon non deve rendere
                # inutilizzabile l'intera sezione HAUL.
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
        raise http_client.BudgetUnavailable("Pagina HAUL temporaneamente non leggibile")
    return unique
