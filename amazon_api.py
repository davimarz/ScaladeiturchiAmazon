from __future__ import annotations

import hashlib
import logging
import math
import random
import re
import threading
import time
from typing import Any, Optional
from urllib.parse import parse_qsl, urlencode, urlparse, urlunparse

import requests
import streamlit as st
from bs4 import BeautifulSoup

try:
    from curl_cffi import requests as c_requests
    HAS_CURL_CFFI = True
except ImportError:
    c_requests = None
    HAS_CURL_CFFI = False


MARKETPLACE = "www.amazon.it"
CREATORS_API_BASE = "https://creatorsapi.amazon/catalog/v1"
DEFAULT_EU_TOKEN_URL = "https://api.amazon.co.uk/auth/o2/token"
TOKEN_SCOPE = "creatorsapi::default"

MAX_RESULTS = 50
MAX_SEARCH_PAGES = 10
SEARCH_CACHE_TTL = 10 * 60
PRICE_CACHE_TTL = 2 * 60
HTTP_TIMEOUT = 8
HTML_TIMEOUT = 10
HTML_CACHE_TTL = 180

RE_ASIN = re.compile(
    r"(?:/dp/|/gp/product/|/d/|^)([A-Z0-9]{10})(?:[/?&#]|$)",
    re.IGNORECASE,
)
RE_PRICE = re.compile(r"(\d{1,3}(?:\.\d{3})*|\d+)[,.](\d{2})")
RE_DIGITS = re.compile(r"[^\d]")

# Soglia di acquisti recenti mostrata da Amazon, quando presente:
# es. "100+ acquistati nel mese scorso".
RE_MONTHLY_BOUGHT = re.compile(
    r"(?P<qty>\d{1,3}(?:[.\s]\d{3})*|\d+(?:[.,]\d+)?\s*[kKmM]?)"
    r"\s*\+\s*"
    r"(?:acquistat[ioe]|comprat[ioe]|bought)\b"
    r".{0,60}?"
    r"(?:mese\s+scorso|ultimo\s+mese|past\s+month)",
    re.IGNORECASE,
)


_HTML_CACHE: dict[str, tuple[float, str]] = {}

USER_AGENTS = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36",
    "Mozilla/5.0 (X11; Linux x86_64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36",
)

# In UI restano solo le due opzioni richieste.
# "Quantità vendite" usa il WebsiteSalesRank/Best Sellers Rank di Amazon:
# NON rappresenta il numero esatto di unità vendute.
SORT_MAPPINGS = {
    "Prezzo minimo": "Price:LowToHigh",
    "Quantità vendite": "Featured",
}

_TOKEN_CACHE: dict[str, Any] = {
    "access_token": None,
    "expires_at": 0.0,
}
_TOKEN_LOCK = threading.Lock()

LOGGER = logging.getLogger("amazon_affiliate")
if not LOGGER.handlers:
    handler = logging.StreamHandler()
    handler.setFormatter(
        logging.Formatter("%(asctime)s %(levelname)s amazon_affiliate: %(message)s")
    )
    LOGGER.addHandler(handler)
LOGGER.setLevel(logging.INFO)
LOGGER.propagate = False

_LAST_API_STATUS: dict[str, Any] = {
    "operation": "",
    "status_code": None,
    "message": "",
}


def _set_api_status(operation: str, status_code: Optional[int], message: str = "") -> None:
    _LAST_API_STATUS["operation"] = str(operation or "")
    _LAST_API_STATUS["status_code"] = status_code
    _LAST_API_STATUS["message"] = str(message or "")[:240]


def get_last_api_status() -> dict[str, Any]:
    """Stato tecnico dell'ultima chiamata, senza token o credenziali."""
    return dict(_LAST_API_STATUS)


def is_associate_not_eligible(status: Optional[dict[str, Any]] = None) -> bool:
    current = status or get_last_api_status()
    code = current.get("status_code")
    message = str(current.get("message") or "").strip().lower()
    return code == 403 and "associatenoteligible" in message.replace(" ", "")


def build_amazon_search_link(
    keyword: str,
    partner_tag: Optional[str] = None,
) -> str:
    """Crea una ricerca Amazon.it con il Partner Tag configurato."""
    tag = str(partner_tag or get_partner_tag()).strip()
    clean_keyword = " ".join(str(keyword or "").strip().split()) or "offerte"
    query = {"k": clean_keyword}
    if tag:
        query["tag"] = tag
    return f"https://www.amazon.it/s?{urlencode(query)}"


def _amazon_secrets() -> dict[str, Any]:
    try:
        return dict(st.secrets.get("amazon_api", {}))
    except Exception:
        return {}


def get_partner_tag() -> str:
    """Restituisce il Partner Tag configurato nei Secrets."""
    return str(_amazon_secrets().get("partner_tag", "")).strip()


def _creators_credentials() -> tuple[str, str, str]:
    cfg = _amazon_secrets()
    client_id = str(cfg.get("client_id") or cfg.get("credential_id") or "").strip()
    client_secret = str(
        cfg.get("client_secret") or cfg.get("credential_secret") or ""
    ).strip()
    token_url = str(cfg.get("token_url") or DEFAULT_EU_TOKEN_URL).strip()
    return client_id, client_secret, token_url


def _retry_delay(response: requests.Response, attempt: int) -> float:
    retry_after = response.headers.get("Retry-After")
    if retry_after:
        try:
            return min(max(float(retry_after), 0.25), 5.0)
        except ValueError:
            pass
    return min(0.5 * (2**attempt), 3.0)


def get_creators_access_token(force_refresh: bool = False) -> Optional[str]:
    now = time.time()

    if (
        not force_refresh
        and _TOKEN_CACHE.get("access_token")
        and now < float(_TOKEN_CACHE.get("expires_at", 0.0)) - 90
    ):
        return str(_TOKEN_CACHE["access_token"])

    with _TOKEN_LOCK:
        now = time.time()

        if (
            not force_refresh
            and _TOKEN_CACHE.get("access_token")
            and now < float(_TOKEN_CACHE.get("expires_at", 0.0)) - 90
        ):
            return str(_TOKEN_CACHE["access_token"])

        client_id, client_secret, token_url = _creators_credentials()
        if not client_id or not client_secret:
            LOGGER.error("Credenziali Creators API mancanti nei Secrets.")
            return None

        payload = {
            "grant_type": "client_credentials",
            "client_id": client_id,
            "client_secret": client_secret,
            "scope": TOKEN_SCOPE,
        }

        for attempt in range(3):
            try:
                response = requests.post(
                    token_url,
                    json=payload,
                    headers={"Content-Type": "application/json"},
                    timeout=HTTP_TIMEOUT,
                )
            except requests.RequestException as exc:
                if attempt < 2:
                    time.sleep(0.5 * (2**attempt))
                    continue
                LOGGER.error("Errore rete token Creators API: %s", type(exc).__name__)
                return None

            if response.status_code == 200:
                try:
                    data = response.json()
                except ValueError:
                    LOGGER.error("Risposta token Creators API non JSON.")
                    return None

                token = data.get("access_token")
                if not token:
                    LOGGER.error("access_token assente nella risposta Amazon.")
                    return None

                expires_in = max(300, int(data.get("expires_in", 3600)))
                _TOKEN_CACHE["access_token"] = str(token)
                _TOKEN_CACHE["expires_at"] = now + expires_in
                return str(token)

            if response.status_code in {429, 500, 502, 503, 504} and attempt < 2:
                time.sleep(_retry_delay(response, attempt))
                continue

            LOGGER.error("Token Creators API: HTTP %s", response.status_code)
            return None

    return None


def _api_post(operation: str, payload: dict[str, Any]) -> Optional[dict[str, Any]]:
    endpoint = f"{CREATORS_API_BASE}/{operation}"
    force_refresh = False

    for attempt in range(3):
        token = get_creators_access_token(force_refresh=force_refresh)
        force_refresh = False
        if not token:
            return None

        headers = {
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
            "x-marketplace": MARKETPLACE,
        }

        try:
            response = requests.post(
                endpoint,
                json=payload,
                headers=headers,
                timeout=HTTP_TIMEOUT,
            )
        except requests.RequestException as exc:
            if attempt < 2:
                time.sleep(0.5 * (2**attempt))
                continue
            LOGGER.error(
                "Creators API %s: errore rete %s",
                operation,
                type(exc).__name__,
            )
            return None

        if response.status_code == 200:
            try:
                data = response.json()
                _set_api_status(operation, 200, "OK")
                return data
            except ValueError:
                _set_api_status(operation, 200, "Risposta non JSON")
                LOGGER.error("Creators API %s: risposta non JSON.", operation)
                return None

        if response.status_code == 401 and attempt < 2:
            _TOKEN_CACHE["access_token"] = None
            _TOKEN_CACHE["expires_at"] = 0.0
            force_refresh = True
            continue

        if response.status_code in {429, 500, 502, 503, 504} and attempt < 2:
            time.sleep(_retry_delay(response, attempt))
            continue

        reason = ""
        try:
            error_data = response.json()
            reason = str(
                error_data.get("reason")
                or error_data.get("message")
                or error_data.get("error")
                or ""
            )
        except ValueError:
            pass

        _set_api_status(operation, response.status_code, reason or "Errore API")
        LOGGER.error(
            "Creators API %s: HTTP %s%s",
            operation,
            response.status_code,
            f" - {reason[:200]}" if reason else "",
        )
        return None

    return None


def _affiliate_detail_url(detail_url: str, asin: str, partner_tag: str) -> str:
    """Preserva i parametri Amazon e forza il Partner Tag."""
    fallback = f"https://www.amazon.it/dp/{asin}"

    try:
        parsed = urlparse(detail_url or fallback)
        host = (parsed.hostname or "").lower()

        if host not in {"amazon.it", "www.amazon.it"}:
            parsed = urlparse(fallback)

        query_pairs = [
            (key, value)
            for key, value in parse_qsl(parsed.query, keep_blank_values=True)
            if key.lower() != "tag"
        ]
        query_pairs.insert(0, ("tag", partner_tag))

        return urlunparse(parsed._replace(query=urlencode(query_pairs)))
    except Exception:
        return f"{fallback}?tag={partner_tag}"


def _money_amount(data: Any) -> Optional[float]:
    if not isinstance(data, dict):
        return None

    try:
        value = data.get("amount")
        return float(value) if value is not None else None
    except (TypeError, ValueError):
        return None


def _safe_int(value: Any) -> Optional[int]:
    try:
        if value is None:
            return None
        parsed = int(value)
        return parsed if parsed > 0 else None
    except (TypeError, ValueError):
        return None


def _select_featured_listing(item: dict[str, Any]) -> Optional[dict[str, Any]]:
    listings = ((item.get("offersV2") or {}).get("listings") or [])
    candidates: list[dict[str, Any]] = []

    for listing in listings:
        if not isinstance(listing, dict):
            continue

        condition = str(((listing.get("condition") or {}).get("value") or "")).lower()
        if condition and condition != "new":
            continue

        if listing.get("violatesMAP") is True:
            continue

        availability_type = str(
            ((listing.get("availability") or {}).get("type") or "")
        ).upper()
        if availability_type in {"OUT_OF_STOCK", "UNAVAILABLE"}:
            continue

        candidates.append(listing)

    if not candidates:
        return None

    winners = [
        listing
        for listing in candidates
        if listing.get("isBuyBoxWinner") is True
    ]
    if not winners:
        return None

    regular = [
        listing
        for listing in winners
        if str(listing.get("type") or "").upper() != "SUBSCRIBEAND_SAVE"
        and str(
            ((listing.get("dealDetails") or {}).get("accessType") or "")
        ).upper() != "PRIME_EXCLUSIVE"
    ]

    return regular[0] if regular else winners[0]


def _item_to_product(
    item: dict[str, Any],
    partner_tag: str,
    prime_filter_applied: bool = False,
) -> Optional[dict[str, Any]]:
    asin = str(item.get("asin") or "").strip().upper()
    if len(asin) != 10:
        return None

    title = str(
        (((item.get("itemInfo") or {}).get("title") or {}).get("displayValue"))
        or "Prodotto Amazon"
    )

    image_url = str(
        (((item.get("images") or {}).get("primary") or {}).get("large") or {}).get(
            "url"
        )
        or (((item.get("images") or {}).get("primary") or {}).get("medium") or {}).get(
            "url"
        )
        or ""
    )

    detail_url = str(item.get("detailPageURL") or "")
    listing = _select_featured_listing(item)

    final_price: Optional[float] = None
    old_price: Optional[float] = None
    discount_value = 0
    saving_basis_label = ""
    is_prime_exclusive = False
    offer_type = ""

    if listing:
        price_block = listing.get("price") or {}
        final_price = _money_amount(price_block.get("money") or {})

        saving_basis = price_block.get("savingBasis") or {}
        candidate_old = _money_amount(saving_basis.get("money") or {})

        if (
            candidate_old is not None
            and final_price is not None
            and candidate_old > final_price
        ):
            old_price = candidate_old
            saving_basis_label = str(
                saving_basis.get("savingBasisTypeLabel")
                or saving_basis.get("savingBasisType")
                or ""
            )

        savings = price_block.get("savings") or {}
        try:
            discount_value = int(round(float(savings.get("percentage") or 0)))
        except (TypeError, ValueError):
            discount_value = 0

        if (
            discount_value <= 0
            and old_price is not None
            and final_price is not None
            and old_price > final_price > 0
        ):
            discount_value = int(
                round(((old_price - final_price) / old_price) * 100)
            )

        access_type = str(
            ((listing.get("dealDetails") or {}).get("accessType") or "")
        ).upper()
        is_prime_exclusive = access_type == "PRIME_EXCLUSIVE"
        offer_type = str(listing.get("type") or "")

    website_rank = (
        ((item.get("browseNodeInfo") or {}).get("websiteSalesRank") or {})
    )
    sales_rank = _safe_int(website_rank.get("salesRank"))
    sales_rank_category = str(
        website_rank.get("contextFreeName")
        or website_rank.get("displayName")
        or ""
    )

    verified = final_price is not None and final_price > 0

    return {
        "asin": asin,
        "titolo": title,
        "immagine_url": image_url,
        "prezzo_iniziale": old_price,
        "prezzo_finale": final_price,
        "prezzo_verificato": verified,
        "sconto": f"-{discount_value}%" if verified and discount_value > 0 else "",
        "sconto_val": discount_value if verified else 0,
        "saving_basis_label": saving_basis_label,
        "is_prime_exclusive": is_prime_exclusive,
        "prime_filter_match": bool(prime_filter_applied),
        "tipo_offerta": offer_type,
        "sold_qty_month": None,
        "sold_qty_label": "",
        "sales_rank": sales_rank,
        "sales_rank_category": sales_rank_category,
        "link_affiliato": _affiliate_detail_url(detail_url, asin, partner_tag),
        "source": "creators_api_getitems",
    }



def _search_item_to_product(
    item: dict[str, Any],
    partner_tag: str,
) -> Optional[dict[str, Any]]:
    """Scheda di fallback basata su SearchItems, senza inventare il prezzo."""
    asin = str(item.get("asin") or "").strip().upper()
    if len(asin) != 10:
        return None

    title = str(
        (((item.get("itemInfo") or {}).get("title") or {}).get("displayValue"))
        or "Prodotto Amazon"
    )

    image_url = str(
        (((item.get("images") or {}).get("primary") or {}).get("medium") or {}).get("url")
        or ""
    )

    detail_url = str(item.get("detailPageURL") or "")

    return {
        "asin": asin,
        "titolo": title,
        "immagine_url": image_url,
        "prezzo_iniziale": None,
        "prezzo_finale": None,
        "prezzo_verificato": False,
        "sconto": "",
        "sconto_val": 0,
        "saving_basis_label": "",
        "is_prime_exclusive": False,
        "prime_filter_match": False,
        "tipo_offerta": "",
        "sold_qty_month": None,
        "sold_qty_label": "",
        "sales_rank": None,
        "sales_rank_category": "",
        "link_affiliato": _affiliate_detail_url(detail_url, asin, partner_tag),
        "source": "creators_api_searchitems_fallback",
    }


def _parse_html_price(text: Any) -> float:
    if text is None:
        return 0.0

    cleaned = (
        str(text)
        .replace("\xa0", " ")
        .replace("&nbsp;", " ")
        .strip()
    )

    match = RE_PRICE.search(cleaned)
    if match:
        whole = match.group(1).replace(".", "")
        fraction = match.group(2)
        try:
            value = float(f"{whole}.{fraction}")
            return value if value > 0 else 0.0
        except ValueError:
            return 0.0

    integer_match = (
        re.search(r"(\d{1,3}(?:\.\d{3})*|\d+)\s*€", cleaned)
        or re.search(r"€\s*(\d{1,3}(?:\.\d{3})*|\d+)", cleaned)
    )
    if integer_match:
        try:
            value = float(integer_match.group(1).replace(".", ""))
            return value if value > 0 else 0.0
        except ValueError:
            return 0.0

    return 0.0


def _html_response_is_usable(status_code: int, text: str) -> bool:
    if status_code != 200 or not text or len(text) < 1500:
        return False

    lowered = text.lower()
    blocked_markers = (
        "robot check",
        "enter the characters you see below",
        "sorry! something went wrong!",
        "automated access",
    )
    return not any(marker in lowered for marker in blocked_markers)


def _fetch_amazon_html(url: str) -> Optional[str]:
    """Scarica HTML Amazon. curl_cffi è il primo tentativo, requests il secondo."""
    headers = {
        "Accept-Language": "it-IT,it;q=0.9,en-US;q=0.7,en;q=0.6",
        "Accept": (
            "text/html,application/xhtml+xml,application/xml;q=0.9,"
            "image/avif,image/webp,*/*;q=0.8"
        ),
        "Cache-Control": "no-cache",
        "Pragma": "no-cache",
    }
    cookies = {
        "lc-acbit": "it_IT",
        "i18n-prefs": "EUR",
    }

    if HAS_CURL_CFFI and c_requests is not None:
        # Le versioni supportate dipendono dalla release di curl_cffi.
        # Ogni tentativo è isolato: un impersonate non supportato non blocca gli altri.
        for impersonate in ("chrome", "chrome124", "chrome120", "safari17_0"):
            try:
                response = c_requests.get(
                    url,
                    impersonate=impersonate,
                    timeout=HTML_TIMEOUT,
                    headers=headers,
                    cookies=cookies,
                    allow_redirects=True,
                )
                if _html_response_is_usable(response.status_code, response.text):
                    return response.text
            except Exception:
                continue

    try:
        session = requests.Session()
        request_headers = dict(headers)
        request_headers["User-Agent"] = random.choice(USER_AGENTS)

        response = session.get(
            url,
            headers=request_headers,
            cookies=cookies,
            timeout=HTML_TIMEOUT,
            allow_redirects=True,
        )
        if _html_response_is_usable(response.status_code, response.text):
            return response.text
    except requests.RequestException:
        pass

    return None


def _get_amazon_html_cached(url: str) -> Optional[str]:
    now = time.time()

    cached = _HTML_CACHE.get(url)
    if cached:
        cached_at, html_text = cached
        if now - cached_at < HTML_CACHE_TTL and html_text:
            return html_text

    html_text = _fetch_amazon_html(url)
    if html_text:
        _HTML_CACHE[url] = (now, html_text)

        # Limite semplice per evitare crescita indefinita su Streamlit.
        if len(_HTML_CACHE) > 80:
            oldest = sorted(
                _HTML_CACHE.items(),
                key=lambda pair: pair[1][0],
            )[:20]
            for key, _ in oldest:
                _HTML_CACHE.pop(key, None)

    return html_text



def _parse_compact_quantity(raw: str) -> Optional[int]:
    text = str(raw or "").strip().lower().replace(" ", "")
    if not text:
        return None

    multiplier = 1
    if text.endswith("k"):
        multiplier = 1_000
        text = text[:-1]
    elif text.endswith("m"):
        multiplier = 1_000_000
        text = text[:-1]

    try:
        if multiplier > 1:
            result = int(float(text.replace(",", ".")) * multiplier)
        else:
            result = int(text.replace(".", "").replace(",", ""))
    except ValueError:
        return None

    return result if result > 0 else None


def _extract_monthly_bought(item: Any) -> tuple[Optional[int], str]:
    text = item.get_text(" ", strip=True)
    if not text:
        return None, ""

    match = RE_MONTHLY_BOUGHT.search(text)
    if not match:
        return None, ""

    qty = _parse_compact_quantity(match.group("qty"))
    if qty is None:
        return None, ""

    shown = f"{qty:,}".replace(",", ".")
    return qty, f"{shown}+ acquistati nel mese scorso"

def _extract_html_review_count(item: Any) -> Optional[int]:
    review_element = (
        item.select_one("span.a-size-base.s-underline-text")
        or item.select_one("a[href*='customerReviews'] span")
        or item.select_one("a[href*='#customerReviews'] span")
    )
    if not review_element:
        return None

    digits = RE_DIGITS.sub("", review_element.get_text(" ", strip=True))
    if not digits:
        return None

    try:
        value = int(digits)
        return value if value >= 0 else None
    except ValueError:
        return None


def _extract_html_prime(item: Any) -> bool:
    prime_selector = (
        "i.a-icon-prime, span.a-icon-prime, "
        "[aria-label='Amazon Prime'], "
        "img[alt*='Prime'], img[alt*='prime']"
    )
    if item.select_one(prime_selector):
        return True

    return "prime" in item.get_text(" ", strip=True).lower()


def _extract_products_from_html(
    html_text: str,
    partner_tag: str,
    min_price: Optional[float] = None,
    max_price: Optional[float] = None,
    require_prime: bool = False,
) -> list[dict[str, Any]]:
    if not html_text:
        return []

    soup = BeautifulSoup(html_text, "html.parser")

    items = soup.select("div[data-component-type='s-search-result']")
    if not items:
        items = [
            node
            for node in soup.select("div[data-asin]")
            if len(str(node.get("data-asin") or "").strip()) == 10
        ]
    if not items:
        items = soup.select("div.s-result-item, li.s-result-item")

    products: list[dict[str, Any]] = []
    seen_asins: set[str] = set()

    for item in items:
        asin = str(item.get("data-asin") or "").strip().upper()

        if len(asin) != 10:
            link_with_asin = item.select_one(
                "a[href*='/dp/'], a[href*='/gp/product/']"
            )
            if link_with_asin:
                match = RE_ASIN.search(
                    str(link_with_asin.get("href") or "")
                )
                if match:
                    asin = match.group(1).upper()

        if len(asin) != 10 or asin in seen_asins:
            continue

        title = ""
        title_element = (
            item.select_one("h2 a span")
            or item.select_one("h2 span")
            or item.select_one("h2")
            or item.select_one(".a-size-medium.a-color-base.a-text-normal")
            or item.select_one(".a-size-base-plus.a-color-base.a-text-normal")
        )
        if title_element:
            title = title_element.get_text(" ", strip=True)

        if not title or len(title) < 3:
            continue

        image_url = ""
        image = item.select_one("img.s-image, img[data-src], img")
        if image:
            image_url = str(
                image.get("src")
                or image.get("data-src")
                or ""
            ).strip()
            if "transparent-pixel" in image_url or "pixel" in image_url.lower():
                image_url = ""

        price = 0.0
        price_element = (
            item.select_one(
                "span.a-price:not([data-a-strike='true']) .a-offscreen"
            )
            or item.select_one(
                ".a-price-range span.a-price:not([data-a-strike='true']) .a-offscreen"
            )
            or item.select_one("span.a-price .a-offscreen")
            or item.select_one(".a-color-price")
        )
        if price_element:
            price = _parse_html_price(
                price_element.get_text(" ", strip=True)
            )

        if price <= 0:
            whole = item.select_one(".a-price-whole")
            fraction = item.select_one(".a-price-fraction")
            if whole:
                whole_text = (
                    whole.get_text("", strip=True)
                    .replace(".", "")
                    .replace(",", "")
                )
                fraction_text = (
                    fraction.get_text("", strip=True)
                    if fraction
                    else "00"
                )
                try:
                    price = float(f"{whole_text}.{fraction_text}")
                except ValueError:
                    price = 0.0

        old_price = price if price > 0 else None
        old_price_element = (
            item.select_one("span.a-price[data-a-strike='true'] .a-offscreen")
            or item.select_one("span.a-text-price .a-offscreen")
            or item.select_one("span[data-a-strike='true']")
        )
        if old_price_element:
            candidate = _parse_html_price(
                old_price_element.get_text(" ", strip=True)
            )
            if candidate > price > 0:
                old_price = candidate

        discount_value = 0
        if (
            old_price is not None
            and old_price > price > 0
        ):
            discount_value = int(
                round(((old_price - price) / old_price) * 100)
            )

        is_prime = _extract_html_prime(item)
        if require_prime and not is_prime:
            continue

        if min_price is not None:
            if price <= 0 or price < float(min_price):
                continue
        if max_price is not None:
            if price <= 0 or price > float(max_price):
                continue

        reviews = _extract_html_review_count(item)
        sold_qty_month, sold_qty_label = _extract_monthly_bought(item)

        product = {
            "asin": asin,
            "titolo": title,
            "immagine_url": image_url,
            "prezzo_iniziale": old_price,
            "prezzo_finale": price if price > 0 else None,
            "prezzo_verificato": bool(price > 0),
            "sconto": (
                f"-{discount_value}%"
                if discount_value > 0
                else ""
            ),
            "sconto_val": discount_value,
            "saving_basis_label": "",
            "is_prime_exclusive": False,
            "is_prime": is_prime,
            "prime_filter_match": is_prime,
            "tipo_offerta": "",
            # Il conteggio recensioni viene usato soltanto come tie-break
            # interno quando l'utente sceglie "Quantità vendite".
            # Non viene mostrato come vendite reali.
            "_html_reviews": reviews,
            "sold_qty_month": sold_qty_month,
            "sold_qty_label": sold_qty_label,
            "sales_rank": None,
            "sales_rank_category": "",
            "link_affiliato": _affiliate_detail_url(
                f"https://www.amazon.it/dp/{asin}",
                asin,
                partner_tag,
            ),
            "source": "amazon_html",
        }

        seen_asins.add(asin)
        products.append(product)

    return products


@st.cache_data(ttl=HTML_CACHE_TTL, show_spinner=False, max_entries=128)
def _search_html_fallback(
    keyword: str,
    sort_type: str,
    partner_tag: str,
    require_prime: bool,
    min_price: Optional[float],
    max_price: Optional[float],
    item_count: int,
    cache_buster: str = "",
) -> tuple[dict[str, Any], ...]:
    # cache_buster consente alla Vetrina di ottenere un set nuovo quando richiesto.
    del cache_buster

    clean_keyword = " ".join(str(keyword or "").strip().split())
    if not clean_keyword:
        clean_keyword = "offerte del giorno"

    target = max(1, min(int(item_count or 10), MAX_RESULTS))

    collected: list[dict[str, Any]] = []
    seen: set[str] = set()

    # Una pagina Amazon contiene in genere più di 10 risultati.
    # Si limita il numero di fetch per non sovraccaricare né Amazon né Streamlit.
    max_pages = min(
        6,
        max(2, math.ceil(target / 12) + 2),
    )

    for page in range(1, max_pages + 1):
        query = {
            "k": clean_keyword,
            "page": page,
        }

        # IMPORTANTE:
        # usiamo sempre la ricerca HTML standard, identica a quella della
        # Vetrina. L'ordinamento viene applicato localmente dopo il parsing.
        # Alcune varianti Amazon con parametro `s` possono restituire markup
        # diverso o pagine non utilizzabili dai server Streamlit.
        url = f"https://www.amazon.it/s?{urlencode(query)}"
        html_text = _get_amazon_html_cached(url)

        page_products: list[dict[str, Any]] = []

        if html_text:
            page_products = _extract_products_from_html(
                html_text,
                partner_tag=partner_tag,
                min_price=min_price,
                max_price=max_price,
                require_prime=require_prime,
            )

        # Se la pagina esiste ma il markup non ha prodotto schede,
        # proviamo il secondo URL. Prima lo facevamo solo quando il download
        # falliva completamente.
        if not page_products:
            alt_query = urlencode(
                {
                    "url": "search-alias=aps",
                    "field-keywords": clean_keyword,
                    "page": page,
                }
            )
            alt_url = f"https://www.amazon.it/s/ref=nb_sb_noss?{alt_query}"
            alt_html = _get_amazon_html_cached(alt_url)

            if alt_html:
                page_products = _extract_products_from_html(
                    alt_html,
                    partner_tag=partner_tag,
                    min_price=min_price,
                    max_price=max_price,
                    require_prime=require_prime,
                )

        LOGGER.info(
            "HTML fallback query=%r page=%s prodotti=%s",
            clean_keyword,
            page,
            len(page_products),
        )

        for product in page_products:
            asin = str(product.get("asin") or "").strip().upper()
            if len(asin) != 10 or asin in seen:
                continue

            seen.add(asin)
            product.setdefault("_amazon_position", len(collected))
            collected.append(product)

        if len(collected) >= target:
            break

    if sort_type == "Prezzo minimo":
        collected.sort(
            key=lambda product: (
                product.get("prezzo_finale") is None,
                float(product.get("prezzo_finale") or float("inf")),
            )
        )
    elif sort_type == "Quantità vendite":
        collected.sort(
            key=lambda product: (
                product.get("sold_qty_month") is None,
                -int(product.get("sold_qty_month") or 0),
                int(product.get("_amazon_position") or 0),
            )
        )

    return tuple(collected[:target])

def _passes_local_filters(
    product: dict[str, Any],
    min_price: Optional[float],
    max_price: Optional[float],
) -> bool:
    price = product.get("prezzo_finale")

    if min_price is not None:
        if price is None or float(price) < float(min_price):
            return False

    if max_price is not None:
        if price is None or float(price) > float(max_price):
            return False

    return True


@st.cache_data(ttl=SEARCH_CACHE_TTL, show_spinner=False, max_entries=512)
def _search_page_cached(
    keyword: str,
    sort_value: str,
    prime_only: bool,
    page: int,
    partner_tag: str,
    min_price: Optional[float],
    max_price: Optional[float],
    cache_buster: str,
) -> tuple[dict[str, Any], ...]:
    # cache_buster serve unicamente a forzare il refresh della Vetrina.
    del cache_buster

    payload: dict[str, Any] = {
        "partnerTag": partner_tag,
        "marketplace": MARKETPLACE,
        "keywords": keyword,
        "searchIndex": "All",
        "itemCount": 10,
        "itemPage": page,
        "sortBy": sort_value,
        # Metadati minimi: consentono di mostrare comunque la scheda
        # se GetItems fallisce per un singolo ASIN.
        "resources": [
            "images.primary.medium",
            "itemInfo.title",
        ],
    }

    if prime_only:
        payload["deliveryFlags"] = ["Prime"]

    if min_price is not None:
        payload["minPrice"] = max(1, int(round(float(min_price) * 100)))

    if max_price is not None:
        payload["maxPrice"] = max(1, int(round(float(max_price) * 100)))

    data = _api_post("searchItems", payload)
    items = (((data or {}).get("searchResult") or {}).get("items") or [])

    clean_items: list[dict[str, Any]] = []
    seen: set[str] = set()

    for item in items:
        if not isinstance(item, dict):
            continue

        asin = str(item.get("asin") or "").strip().upper()
        if len(asin) != 10 or asin in seen:
            continue

        seen.add(asin)
        clean_items.append(item)

    return tuple(clean_items)


GET_ITEMS_RESOURCES = [
    "browseNodeInfo.websiteSalesRank",
    "images.primary.large",
    "images.primary.medium",
    "itemInfo.title",
    "offersV2.listings.availability",
    "offersV2.listings.condition",
    "offersV2.listings.dealDetails",
    "offersV2.listings.isBuyBoxWinner",
    "offersV2.listings.merchantInfo",
    "offersV2.listings.price",
    "offersV2.listings.type",
]


@st.cache_data(ttl=PRICE_CACHE_TTL, show_spinner=False, max_entries=512)
def _get_items_cached(
    asins: tuple[str, ...],
    partner_tag: str,
) -> tuple[dict[str, Any], ...]:
    if not asins:
        return tuple()

    payload = {
        "partnerTag": partner_tag,
        "marketplace": MARKETPLACE,
        "itemIds": list(asins[:10]),
        "itemIdType": "ASIN",
        "resources": GET_ITEMS_RESOURCES,
    }

    data = _api_post("getItems", payload)
    response_data = data or {}

    # Creators API attuale usa "itemResults".
    # "itemsResult" è mantenuto solo come compatibilità difensiva.
    container = (
        response_data.get("itemResults")
        or response_data.get("itemsResult")
        or {}
    )
    items = (container.get("items") or [])

    return tuple(item for item in items if isinstance(item, dict))


def ottieni_offerte_avanzate(
    keyword: str = "",
    sort_type: str = "Prezzo minimo",
    solo_spedizione_gratuita: bool = False,
    min_price: Optional[float] = None,
    max_price: Optional[float] = None,
    item_count: int = 10,
    categoria: str = "",
    sottocategoria: str = "",
    _partner_tag_override: Optional[str] = None,
    _cache_buster: Optional[str] = None,
) -> list[dict[str, Any]]:
    del categoria, sottocategoria

    partner_tag = get_partner_tag() or str(_partner_tag_override or "").strip()
    if not partner_tag:
        LOGGER.error("partner_tag Amazon non configurato.")
        return []

    target = max(1, min(int(item_count or 10), MAX_RESULTS))
    query = " ".join(str(keyword or "").strip().split()) or "offerte del giorno"
    sort_value = SORT_MAPPINGS.get(sort_type, "Price:LowToHigh")
    cache_buster = str(_cache_buster or "normal-search")

    products: list[dict[str, Any]] = []
    seen_asins: set[str] = set()

    # -----------------------------------------------------------------
    # 1) CREATORS API: prima scelta.
    # -----------------------------------------------------------------
    if sort_type == "Quantità vendite":
        api_candidate_target = min(MAX_RESULTS, target + 20)
    else:
        api_candidate_target = target

    api_pages = min(
        MAX_SEARCH_PAGES,
        max(1, math.ceil(api_candidate_target / 10) + 2),
    )

    for page in range(1, api_pages + 1):
        search_items = _search_page_cached(
            query,
            sort_value,
            bool(solo_spedizione_gratuita),
            page,
            partner_tag,
            min_price,
            max_price,
            cache_buster,
        )

        if not search_items:
            # Se SearchItems è bloccato (es. AssociateNotEligible)
            # usciamo subito e passiamo al fallback HTML.
            break

        asins = tuple(
            str(item.get("asin") or "").strip().upper()
            for item in search_items
            if len(str(item.get("asin") or "").strip()) == 10
        )

        exact_items = _get_items_cached(asins, partner_tag)
        by_asin = {
            str(item.get("asin") or "").strip().upper(): item
            for item in exact_items
        }

        for search_item in search_items:
            asin = str(search_item.get("asin") or "").strip().upper()
            if len(asin) != 10 or asin in seen_asins:
                continue

            exact_item = by_asin.get(asin)

            if exact_item:
                product = _item_to_product(
                    exact_item,
                    partner_tag,
                    prime_filter_applied=bool(solo_spedizione_gratuita),
                )
            else:
                product = _search_item_to_product(
                    search_item,
                    partner_tag,
                )

            if not product:
                continue

            if not _passes_local_filters(
                product,
                min_price,
                max_price,
            ):
                continue

            seen_asins.add(asin)
            product.setdefault("_amazon_position", len(products))
            products.append(product)

            if sort_type != "Quantità vendite" and len(products) >= target:
                break

            if (
                sort_type == "Quantità vendite"
                and len(products) >= api_candidate_target
            ):
                break

        if sort_type != "Quantità vendite" and len(products) >= target:
            break

        if (
            sort_type == "Quantità vendite"
            and len(products) >= api_candidate_target
        ):
            break

    # Se l'API ha già dato abbastanza prodotti, non tocchiamo l'HTML.
    if len(products) >= target:
        if sort_type == "Prezzo minimo":
            products.sort(
                key=lambda product: (
                    product.get("prezzo_finale") is None,
                    float(product.get("prezzo_finale") or float("inf")),
                )
            )
        elif sort_type == "Quantità vendite":
            products.sort(
                key=lambda product: (
                    product.get("sales_rank") is None,
                    int(product.get("sales_rank") or 10**12),
                    float(product.get("prezzo_finale") or float("inf")),
                )
            )

        return products[:target]

    # -----------------------------------------------------------------
    # 2) FALLBACK HTML SILENZIOSO.
    # Se API restituisce zero o pochi risultati, integriamo fino al target.
    # -----------------------------------------------------------------
    missing = target - len(products)

    html_products = _search_html_fallback(
        keyword=query,
        sort_type=sort_type,
        partner_tag=partner_tag,
        require_prime=bool(solo_spedizione_gratuita),
        min_price=min_price,
        max_price=max_price,
        # Chiediamo un po' più del necessario per assorbire duplicati API/HTML.
        item_count=min(MAX_RESULTS, max(target, missing + 10)),
        cache_buster=cache_buster,
    )

    for product in html_products:
        asin = str(product.get("asin") or "").strip().upper()
        if len(asin) != 10 or asin in seen_asins:
            continue

        seen_asins.add(asin)
        product.setdefault("_amazon_position", len(products))
        products.append(product)

        if len(products) >= target:
            break

    # L'ordinamento finale deve essere coerente anche quando le fonti sono miste.
    if sort_type == "Prezzo minimo":
        products.sort(
            key=lambda product: (
                product.get("prezzo_finale") is None,
                float(product.get("prezzo_finale") or float("inf")),
            )
        )
    elif sort_type == "Quantità vendite":
        def final_sales_key(product: dict) -> tuple:
            sold_qty = product.get("sold_qty_month")
            sales_rank = product.get("sales_rank")
            amazon_position = int(product.get("_amazon_position") or 0)

            try:
                if sold_qty is not None:
                    return (0, -int(sold_qty), amazon_position)
            except (TypeError, ValueError):
                pass

            try:
                if sales_rank is not None:
                    return (1, int(sales_rank), amazon_position)
            except (TypeError, ValueError):
                pass

            return (2, amazon_position, amazon_position)

        products.sort(key=final_sales_key)

    return products[:target]


@st.cache_data(ttl=10 * 60, show_spinner=False, max_entries=64)
def ottieni_vetrina_casuale(
    partner_tag: Optional[str] = None,
    item_count: int = 10,
    refresh_token: Optional[str] = None,
) -> list[dict[str, Any]]:
    configured_tag = get_partner_tag() or str(partner_tag or "").strip()
    if not configured_tag:
        return []

    keywords = (
        "offerte tecnologia",
        "offerte casa cucina",
        "offerte cuffie bluetooth",
        "offerte smartwatch",
        "offerte sport fitness",
        "offerte cura persona",
        "offerte accessori smartphone",
        "offerte elettrodomestici",
        "offerte scarpe",
        "offerte zaini accessori",
    )

    selector = str(refresh_token or int(time.time() // (10 * 60)))
    digest = hashlib.sha256(selector.encode("utf-8")).digest()
    keyword = keywords[int.from_bytes(digest[:4], "big") % len(keywords)]

    return ottieni_offerte_avanzate(
        keyword=keyword,
        sort_type="Quantità vendite",
        item_count=max(1, min(int(item_count or 10), 10)),
        _partner_tag_override=configured_tag,
        _cache_buster=f"vetrina:{selector}",
    )
