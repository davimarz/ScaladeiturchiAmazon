from __future__ import annotations

import base64
import hashlib
import html as html_lib
import json
import logging
import math
import random
import re
import threading
import time
import xml.etree.ElementTree as ET
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Any, Optional
from urllib.parse import (
    parse_qs,
    parse_qsl,
    unquote,
    urlencode,
    urljoin,
    urlparse,
    urlunparse,
)

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
HAUL_STORE_URL = "https://www.amazon.it/haul/store"
CREATORS_API_BASE = "https://creatorsapi.amazon/catalog/v1"
DEFAULT_EU_TOKEN_URL = "https://api.amazon.co.uk/auth/o2/token"
TOKEN_SCOPE = "creatorsapi::default"

MAX_RESULTS = 50
MAX_SEARCH_PAGES = 10
SEARCH_CACHE_TTL = 10 * 60
PRICE_CACHE_TTL = 2 * 60
HTTP_TIMEOUT = 8
HTML_TIMEOUT = 12
HTML_CACHE_TTL = 180
DETAIL_SNAPSHOT_TTL = 180
DETAIL_PARTIAL_TTL = 30
DETAIL_HTML_TIMEOUT = 8
DETAIL_PRICE_WORKERS = 3
EXTERNAL_DISCOVERY_TIMEOUT = 6
EXTERNAL_DISCOVERY_MAX_PAGES = 2
HTML_SEARCH_COOLDOWN = 10 * 60
HTML_SEARCH_FAILURE_THRESHOLD = 2
CREATORS_403_COOLDOWN = 60 * 60
SEARCH_HTML_CACHE_MAX = 24
DETAIL_SNAPSHOT_CACHE_MAX = 256

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
_DETAIL_SNAPSHOT_CACHE: dict[
    str,
    tuple[
        float,
        tuple[
            Optional[float],
            Optional[float],
            int,
            Optional[int],
            str,
            str,
            str,
        ],
    ],
] = {}
_CACHE_LOCK = threading.RLock()
_HTTP_LOCAL = threading.local()
_CREATORS_BLOCK_LOCK = threading.Lock()
_CREATORS_BLOCKED_UNTIL = 0.0
_HTML_SEARCH_BLOCK_LOCK = threading.Lock()
_HTML_SEARCH_BLOCKED_UNTIL = 0.0
_HTML_SEARCH_CONSECUTIVE_FAILURES = 0
_SEARCH_DIAGNOSTICS_LOCK = threading.Lock()
_LAST_SEARCH_DIAGNOSTICS: dict[str, Any] = {
    "keyword": "",
    "reason": "",
    "pages_attempted": 0,
    "html_variants_received": 0,
    "html_variants_with_product_signals": 0,
    "products_parsed": 0,
    "external_sources_ok": 0,
    "external_products": 0,
}

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




def _is_amazon_search_url(url: str) -> bool:
    try:
        parsed = urlparse(str(url or ""))
        path = parsed.path or ""
        return path == "/s" or path.startswith("/gp/aw/s")
    except Exception:
        return False


def html_search_circuit_open() -> bool:
    """Evita richieste SERP ripetute quando Amazon blocca l'IP Streamlit."""
    with _HTML_SEARCH_BLOCK_LOCK:
        return time.time() < _HTML_SEARCH_BLOCKED_UNTIL


def _record_html_search_failure() -> None:
    global _HTML_SEARCH_CONSECUTIVE_FAILURES, _HTML_SEARCH_BLOCKED_UNTIL
    with _HTML_SEARCH_BLOCK_LOCK:
        _HTML_SEARCH_CONSECUTIVE_FAILURES += 1
        if _HTML_SEARCH_CONSECUTIVE_FAILURES >= HTML_SEARCH_FAILURE_THRESHOLD:
            _HTML_SEARCH_BLOCKED_UNTIL = max(
                _HTML_SEARCH_BLOCKED_UNTIL,
                time.time() + HTML_SEARCH_COOLDOWN,
            )


def _record_html_search_success() -> None:
    global _HTML_SEARCH_CONSECUTIVE_FAILURES, _HTML_SEARCH_BLOCKED_UNTIL
    with _HTML_SEARCH_BLOCK_LOCK:
        _HTML_SEARCH_CONSECUTIVE_FAILURES = 0
        _HTML_SEARCH_BLOCKED_UNTIL = 0.0

def creators_circuit_open() -> bool:
    """Indica se il circuit breaker Creators API è attualmente aperto."""
    return _creators_temporarily_blocked()


def _set_search_diagnostics(**values: Any) -> None:
    with _SEARCH_DIAGNOSTICS_LOCK:
        for key, value in values.items():
            if key in _LAST_SEARCH_DIAGNOSTICS:
                _LAST_SEARCH_DIAGNOSTICS[key] = value


def get_search_diagnostics() -> dict[str, Any]:
    """Diagnostica sintetica e priva di credenziali dell'ultima ricerca HTML."""
    with _SEARCH_DIAGNOSTICS_LOCK:
        result = dict(_LAST_SEARCH_DIAGNOSTICS)

    result["creators_circuit_open"] = creators_circuit_open()
    return result

def _creators_temporarily_blocked() -> bool:
    with _CREATORS_BLOCK_LOCK:
        return time.time() < _CREATORS_BLOCKED_UNTIL


def _block_creators_temporarily() -> None:
    global _CREATORS_BLOCKED_UNTIL
    with _CREATORS_BLOCK_LOCK:
        _CREATORS_BLOCKED_UNTIL = max(
            _CREATORS_BLOCKED_UNTIL,
            time.time() + CREATORS_403_COOLDOWN,
        )


def _clear_creators_block() -> None:
    global _CREATORS_BLOCKED_UNTIL
    with _CREATORS_BLOCK_LOCK:
        _CREATORS_BLOCKED_UNTIL = 0.0


def _get_http_session() -> requests.Session:
    session = getattr(_HTTP_LOCAL, "requests_session", None)
    if session is None:
        session = requests.Session()
        session.headers.update({
            "User-Agent": random.choice(USER_AGENTS),
            "Accept-Language": "it-IT,it;q=0.9,en-US;q=0.7,en;q=0.6",
        })
        _HTTP_LOCAL.requests_session = session
    return session


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



def build_amazon_haul_link(
    partner_tag: Optional[str] = None,
) -> str:
    """Link alla vetrina Amazon Haul con Partner Tag configurato."""
    tag = str(partner_tag or get_partner_tag()).strip()
    if not tag:
        return HAUL_STORE_URL
    return f"{HAUL_STORE_URL}?{urlencode({'tag': tag})}"

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


def _token_url_for_credential_version(version: str) -> str:
    """Endpoint OAuth Amazon in base alla versione della credenziale."""
    clean = str(version or "").strip()

    if clean.startswith("3.1"):
        return "https://api.amazon.com/auth/o2/token"
    if clean.startswith("3.3"):
        return "https://api.amazon.co.jp/auth/o2/token"

    # 3.2 = Europa (IT inclusa). È anche il fallback sicuro del progetto.
    return DEFAULT_EU_TOKEN_URL


def _creators_credentials() -> tuple[str, str, str]:
    cfg = _amazon_secrets()

    # Nomi consigliati: corrispondono direttamente al CSV Creators API.
    client_id = str(
        cfg.get("credential_id")
        or cfg.get("client_id")
        or ""
    ).strip()

    client_secret = str(
        cfg.get("credential_secret")
        or cfg.get("client_secret")
        or ""
    ).strip()

    credential_version = str(
        cfg.get("credential_version")
        or cfg.get("version")
        or ""
    ).strip()

    configured_token_url = str(cfg.get("token_url") or "").strip()
    token_url = (
        configured_token_url
        or _token_url_for_credential_version(credential_version)
    )

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
    # Dopo AssociateNotEligible evitiamo di ripetere una richiesta che Amazon
    # rifiuterebbe comunque. Ogni 60 minuti il backend riprova automaticamente.
    if _creators_temporarily_blocked():
        return None

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
                endpoint, json=payload, headers=headers, timeout=HTTP_TIMEOUT
            )
        except requests.RequestException as exc:
            if attempt < 2:
                time.sleep(0.5 * (2**attempt))
                continue
            LOGGER.error(
                "Creators API %s: errore rete %s", operation, type(exc).__name__
            )
            return None

        if response.status_code == 200:
            try:
                data = response.json()
                _clear_creators_block()
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

        if (
            response.status_code == 403
            and "associatenoteligible" in reason.replace(" ", "").lower()
        ):
            _block_creators_temporarily()
            LOGGER.warning(
                "Creators API temporaneamente non idonea: fallback HTML per %s minuti.",
                CREATORS_403_COOLDOWN // 60,
            )
            return None

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
        (((item.get("images") or {}).get("primary") or {}).get("large") or {}).get("url")
        or (((item.get("images") or {}).get("primary") or {}).get("medium") or {}).get("url")
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



def _normalize_product_detail_url(href: str, asin: str) -> str:
    """Costruisce l'URL dettaglio preservando i parametri utili alla variante."""
    asin_clean = str(asin or "").strip().upper()
    fallback = f"https://www.amazon.it/dp/{asin_clean}?th=1"

    raw = str(href or "").strip()
    if not raw:
        return fallback

    absolute = urljoin("https://www.amazon.it", raw)

    try:
        parsed = urlparse(absolute)
        host = (parsed.hostname or "").lower()
        if host not in {"amazon.it", "www.amazon.it"}:
            return fallback

        keep = {}
        for key, value in parse_qsl(parsed.query, keep_blank_values=True):
            if key.lower() in {"th", "psc"}:
                keep[key] = value

        if "th" not in keep:
            keep["th"] = "1"

        return urlunparse(
            parsed._replace(
                scheme="https",
                netloc="www.amazon.it",
                query=urlencode(keep),
                fragment="",
            )
        )
    except Exception:
        return fallback


def _first_valid_price(elements: list[Any]) -> float:
    for element in elements:
        if element is None:
            continue
        value = _parse_html_price(element.get_text(" ", strip=True))
        if value > 0:
            return value
    return 0.0


def _price_from_visible_parts(price_node: Any) -> float:
    """Legge whole/fraction dal prezzo visibile (aria-hidden=true).

    È utile quando Amazon ha più .a-offscreen nello stesso widget.
    """
    if price_node is None:
        return 0.0

    visible = price_node.select_one("[aria-hidden='true']")
    scope = visible or price_node

    whole = scope.select_one(".a-price-whole")
    fraction = scope.select_one(".a-price-fraction")

    if not whole:
        return 0.0

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
        value = float(f"{whole_text}.{fraction_text}")
        return value if value > 0 else 0.0
    except ValueError:
        return 0.0


def _extract_price_from_primary_core(
    soup: BeautifulSoup,
) -> tuple[float, Optional[Any], str]:
    """Ritorna il prezzo principale e il nodo che lo contiene.

    Ordine di confidenza:
    1. apexPriceToPay / priceToPay con data-a-color=base
    2. qualsiasi a-price data-a-color=base nel corePrice desktop
    3. stesso criterio nel corePrice generico/mobile
    4. fallback legacy.
    """
    high_confidence_selectors = (
        # Struttura mostrata negli screenshot dell'utente.
        "#apex_offerDisplay_desktop #corePrice_feature_div "
        "span.a-price.apexPriceToPay[data-a-color='base']",
        "#apex_offerDisplay_desktop #corePrice_feature_div "
        "span.a-price[class*='priceToPay'][data-a-color='base']",
        "#apex_offerDisplay_desktop #corePrice_feature_div "
        "span.a-price[data-a-color='base']:not(.a-text-price)",

        "#corePrice_feature_div "
        "span.a-price.apexPriceToPay[data-a-color='base']",
        "#corePrice_feature_div "
        "span.a-price[class*='priceToPay'][data-a-color='base']",
        "#corePrice_feature_div "
        "span.a-price[data-a-color='base']:not(.a-text-price)",

        "#corePriceDisplay_desktop_feature_div "
        "span.a-price[data-a-color='base']:not(.a-text-price)",
        "#apex_offerDisplay_mobile "
        "span.a-price[data-a-color='base']:not(.a-text-price)",
        "[data-feature-name='corePrice'] "
        "span.a-price[data-a-color='base']:not(.a-text-price)",
    )

    for selector in high_confidence_selectors:
        for price_node in soup.select(selector):
            # Prima usa whole/fraction VISIBILI, esattamente come nello screenshot.
            value = _price_from_visible_parts(price_node)
            if value > 0:
                return value, price_node, selector

            offscreen = price_node.select_one(":scope > .a-offscreen")
            if offscreen is None:
                offscreen = price_node.select_one(".a-offscreen")
            if offscreen is not None:
                value = _parse_html_price(
                    offscreen.get_text(" ", strip=True)
                )
                if value > 0:
                    return value, price_node, selector

    # Fallback più debole, solo se il prezzo principale "base" non esiste.
    fallback_selectors = (
        "#corePrice_feature_div .priceToPay .a-offscreen",
        "#corePrice_feature_div #price_inside_buybox",
        "#price_inside_buybox",
        "#priceblock_ourprice",
        "#priceblock_dealprice",
        "#priceblock_saleprice",
    )

    for selector in fallback_selectors:
        element = soup.select_one(selector)
        if element is None:
            continue

        value = _parse_html_price(element.get_text(" ", strip=True))
        if value > 0:
            return value, element, selector

    return 0.0, None, ""


def _extract_old_price_from_same_core(
    soup: BeautifulSoup,
    current_price: float,
    current_node: Optional[Any],
) -> Optional[float]:
    """Trova il prezzo di riferimento nello stesso widget del prezzo corrente.

    Non cerca indiscriminatamente in tutta la pagina: così prezzi di accessori,
    rate, Subscribe & Save o altre offerte non entrano nella scheda.
    """
    if current_price <= 0:
        return None

    scopes: list[Any] = []

    # Risali prima al corePrice che contiene esattamente il prezzo selezionato.
    if current_node is not None:
        parent = current_node
        for _ in range(8):
            if parent is None:
                break
            parent_id = str(parent.get("id") or "")
            feature_name = str(parent.get("data-feature-name") or "")

            if (
                parent_id in {
                    "corePrice_feature_div",
                    "corePriceDisplay_desktop_feature_div",
                }
                or feature_name == "corePrice"
            ):
                scopes.append(parent)
                break
            parent = parent.parent

    # Fallback a blocchi corePrice noti, senza uscire verso altri widget.
    for selector in (
        "#apex_offerDisplay_desktop #corePrice_feature_div",
        "#corePrice_feature_div",
        "#corePriceDisplay_desktop_feature_div",
        "[data-feature-name='corePrice']",
    ):
        node = soup.select_one(selector)
        if node is not None and node not in scopes:
            scopes.append(node)

    old_selectors = (
        "span.a-price.a-text-price span.a-offscreen",
        "span.a-price[data-a-strike='true'] span.a-offscreen",
        ".basisPrice span.a-offscreen",
        "span[data-a-strike='true'] span.a-offscreen",
    )

    candidates: list[float] = []

    for scope in scopes:
        for selector in old_selectors:
            for element in scope.select(selector):
                candidate = _parse_html_price(
                    element.get_text(" ", strip=True)
                )
                if candidate > current_price:
                    candidates.append(candidate)

        # Amazon talvolta usa un'etichetta testuale "Prezzo consigliato".
        for text_node in scope.find_all(
            string=re.compile(
                r"prezzo\s+(?:consigliato|precedente|di\s+listino)"
                r"|list\s+price|was\s+price",
                re.IGNORECASE,
            )
        ):
            parent = text_node.parent
            container = parent.parent if parent is not None else None
            if container is None:
                continue

            for element in container.select(".a-price .a-offscreen"):
                candidate = _parse_html_price(
                    element.get_text(" ", strip=True)
                )
                if candidate > current_price:
                    candidates.append(candidate)

    if not candidates:
        return None

    # Il riferimento più vicino sopra il prezzo corrente è normalmente
    # quello della stessa offerta (es. 43,00 sopra 38,78), evitando valori
    # di altri widget molto più alti.
    return min(candidates)


def _extract_detail_prices_from_soup(
    soup: BeautifulSoup,
) -> tuple[Optional[float], Optional[float], int]:
    current_price, current_node, selector_used = _extract_price_from_primary_core(soup)
    if current_price <= 0:
        return None, None, 0

    old_price = _extract_old_price_from_same_core(soup, current_price, current_node)
    discount_value = 0
    if old_price is not None and old_price > current_price:
        discount_value = int(round(((old_price - current_price) / old_price) * 100))

    LOGGER.info(
        "Detail price verified selector=%s current=%.2f old=%s",
        selector_used, current_price,
        f"{old_price:.2f}" if old_price is not None else "n/a",
    )
    return float(current_price), old_price, discount_value


def _extract_detail_page_prices(
    html_text: str,
) -> tuple[Optional[float], Optional[float], int]:
    if not html_text:
        return None, None, 0
    soup = BeautifulSoup(html_text, "html.parser")
    return _extract_detail_prices_from_soup(soup)




def _asin_image_fallbacks(asin: str) -> tuple[str, ...]:
    """URL immagini Amazon da usare soltanto come fallback visuale."""
    clean = str(asin or "").strip().upper()
    if len(clean) != 10:
        return ()

    return (
        f"https://images-na.ssl-images-amazon.com/images/P/{clean}.01.LZZZZZZZ.jpg",
        f"https://images-na.ssl-images-amazon.com/images/P/{clean}.09.LZZZZZZZ.jpg",
        f"https://images-na.ssl-images-amazon.com/images/P/{clean}.jpg",
    )


def _ensure_product_image_fallbacks(
    product: dict[str, Any],
) -> dict[str, Any]:
    enriched = dict(product)

    asin = str(enriched.get("asin") or "").strip().upper()
    fallbacks = list(_asin_image_fallbacks(asin))
    current = str(enriched.get("immagine_url") or "").strip()

    if not current and fallbacks:
        current = fallbacks.pop(0)
        enriched["immagine_url"] = current

    existing = enriched.get("immagine_fallback_urls") or []
    if isinstance(existing, str):
        existing = [existing]

    merged: list[str] = []
    for url in [*existing, *fallbacks]:
        clean_url = str(url or "").strip()
        if clean_url and clean_url != current and clean_url not in merged:
            merged.append(clean_url)

    enriched["immagine_fallback_urls"] = merged
    return enriched

def _extract_detail_identity_from_soup(
    soup: BeautifulSoup,
) -> tuple[str, str]:
    """Titolo e immagine principale dalla pagina prodotto."""
    title = ""

    product_title = soup.select_one("#productTitle")
    if product_title is not None:
        title = " ".join(product_title.get_text(" ", strip=True).split())

    if not title:
        meta_title = soup.select_one("meta[property='og:title']")
        if meta_title is not None:
            title = " ".join(str(meta_title.get("content") or "").split())

    image_url = ""

    image = (
        soup.select_one("#landingImage")
        or soup.select_one("#imgBlkFront")
        or soup.select_one("#ebooksImgBlkFront")
        or soup.select_one("img[data-a-dynamic-image]")
    )

    if image is not None:
        old_hires = str(image.get("data-old-hires") or "").strip()
        if old_hires:
            image_url = old_hires
        else:
            image_url = _best_serp_image_url(image)

    if not image_url:
        meta_image = soup.select_one("meta[property='og:image']")
        if meta_image is not None:
            image_url = str(meta_image.get("content") or "").strip()

    return title, image_url

def _extract_detail_snapshot(
    html_text: str,
) -> tuple[
    Optional[float],
    Optional[float],
    int,
    Optional[int],
    str,
    str,
    str,
]:
    if not html_text:
        return None, None, 0, None, "", "", ""

    soup = BeautifulSoup(html_text, "html.parser")
    final_price, old_price, discount_value = _extract_detail_prices_from_soup(soup)
    sold_qty, sold_label = _extract_monthly_bought(soup)
    detail_title, detail_image = _extract_detail_identity_from_soup(soup)

    return (
        final_price,
        old_price,
        discount_value,
        sold_qty,
        sold_label,
        detail_title,
        detail_image,
    )



def _detail_snapshot_has_any_data(
    snapshot: tuple[
        Optional[float],
        Optional[float],
        int,
        Optional[int],
        str,
        str,
        str,
    ],
) -> bool:
    (
        final_price,
        old_price,
        discount_value,
        sold_qty,
        sold_label,
        detail_title,
        detail_image,
    ) = snapshot

    return bool(
        (final_price is not None and final_price > 0)
        or (old_price is not None and old_price > 0)
        or discount_value
        or sold_qty
        or sold_label
        or detail_title
        or detail_image
    )


def _detail_snapshot_is_complete(
    snapshot: tuple[
        Optional[float],
        Optional[float],
        int,
        Optional[int],
        str,
        str,
        str,
    ],
) -> bool:
    final_price, _, _, _, _, detail_title, detail_image = snapshot
    return bool(
        final_price is not None
        and final_price > 0
        and detail_title
        and detail_image
    )


def _merge_detail_snapshots(
    primary: tuple[
        Optional[float],
        Optional[float],
        int,
        Optional[int],
        str,
        str,
        str,
    ],
    secondary: tuple[
        Optional[float],
        Optional[float],
        int,
        Optional[int],
        str,
        str,
        str,
    ],
) -> tuple[
    Optional[float],
    Optional[float],
    int,
    Optional[int],
    str,
    str,
    str,
]:
    p_final, p_old, p_discount, p_sold, p_label, p_title, p_image = primary
    s_final, s_old, s_discount, s_sold, s_label, s_title, s_image = secondary

    final_price = p_final if p_final is not None and p_final > 0 else s_final

    if p_final is not None and p_final > 0:
        old_price = p_old
        discount = p_discount
    else:
        old_price = s_old
        discount = s_discount

    sold_qty = p_sold if p_sold is not None else s_sold
    sold_label = p_label or s_label
    detail_title = p_title or s_title
    detail_image = p_image or s_image

    return (
        final_price,
        old_price,
        int(discount or 0),
        sold_qty,
        sold_label,
        detail_title,
        detail_image,
    )


def _asin_from_detail_url(detail_url: str) -> str:
    match = RE_ASIN.search(str(detail_url or ""))
    return match.group(1).upper() if match else ""

def _get_detail_snapshot_cached(
    detail_url: str,
) -> tuple[
    Optional[float],
    Optional[float],
    int,
    Optional[int],
    str,
    str,
    str,
]:
    now = time.time()

    with _CACHE_LOCK:
        cached = _DETAIL_SNAPSHOT_CACHE.get(detail_url)
        if cached:
            cached_at, snapshot = cached
            ttl = (
                DETAIL_SNAPSHOT_TTL
                if _detail_snapshot_is_complete(snapshot)
                else DETAIL_PARTIAL_TTL
            )
            if now - cached_at < ttl:
                return snapshot
            _DETAIL_SNAPSHOT_CACHE.pop(detail_url, None)

    desktop_html = _fetch_amazon_html(
        detail_url,
        timeout=DETAIL_HTML_TIMEOUT,
    )
    desktop_snapshot = _extract_detail_snapshot(desktop_html or "")
    snapshot = desktop_snapshot

    asin = _asin_from_detail_url(detail_url)

    if asin and not _detail_snapshot_is_complete(snapshot):
        mobile_url = f"https://www.amazon.it/gp/aw/d/{asin}?psc=1"

        mobile_html = _fetch_amazon_html(
            mobile_url,
            timeout=DETAIL_HTML_TIMEOUT,
        )
        mobile_snapshot = _extract_detail_snapshot(mobile_html or "")
        snapshot = _merge_detail_snapshots(
            desktop_snapshot,
            mobile_snapshot,
        )

        LOGGER.info(
            "Detail recovery asin=%s desktop_any=%s mobile_any=%s complete=%s",
            asin,
            _detail_snapshot_has_any_data(desktop_snapshot),
            _detail_snapshot_has_any_data(mobile_snapshot),
            _detail_snapshot_is_complete(snapshot),
        )

    # Un fallimento totale non va in cache: la ricerca successiva deve poter
    # riprovare subito, invece di restare vuota per diversi minuti.
    if _detail_snapshot_has_any_data(snapshot):
        with _CACHE_LOCK:
            _DETAIL_SNAPSHOT_CACHE[detail_url] = (now, snapshot)

            if len(_DETAIL_SNAPSHOT_CACHE) > DETAIL_SNAPSHOT_CACHE_MAX:
                oldest = sorted(
                    _DETAIL_SNAPSHOT_CACHE.items(),
                    key=lambda pair: pair[1][0],
                )
                excess = len(_DETAIL_SNAPSHOT_CACHE) - DETAIL_SNAPSHOT_CACHE_MAX
                for key, _ in oldest[:excess]:
                    _DETAIL_SNAPSHOT_CACHE.pop(key, None)

    return snapshot


def _verify_product_detail_price(
    product: dict[str, Any],
) -> dict[str, Any]:
    """Verifica il prezzo sulla pagina prodotto con cache compatta."""
    verified = _ensure_product_image_fallbacks(product)

    asin = str(verified.get("asin") or "").strip().upper()
    if len(asin) != 10:
        return verified

    detail_url = str(verified.get("detail_page_url") or "").strip()
    if not detail_url:
        detail_url = f"https://www.amazon.it/dp/{asin}?th=1"

    (
        final_price,
        old_price,
        discount_value,
        sold_qty,
        sold_label,
        detail_title,
        detail_image,
    ) = _get_detail_snapshot_cached(detail_url)

    if detail_title:
        verified["titolo"] = detail_title
    if detail_image:
        previous_image = str(verified.get("immagine_url") or "").strip()
        fallback_urls = list(verified.get("immagine_fallback_urls") or [])

        if previous_image and previous_image != detail_image:
            fallback_urls.insert(0, previous_image)

        verified["immagine_url"] = detail_image
        verified["immagine_fallback_urls"] = list(dict.fromkeys(
            url for url in fallback_urls
            if url and url != detail_image
        ))

    if final_price is None or final_price <= 0:
        verified["_search_prezzo_finale"] = verified.get("prezzo_finale")
        verified["_search_prezzo_iniziale"] = verified.get("prezzo_iniziale")
        verified["prezzo_finale"] = None
        verified["prezzo_iniziale"] = None
        verified["prezzo_verificato"] = False
        verified["sconto"] = ""
        verified["sconto_val"] = 0
        verified["source"] = "amazon_html_detail_unverified"
        return verified

    verified["prezzo_finale"] = float(final_price)
    verified["prezzo_iniziale"] = (
        float(old_price) if old_price is not None and old_price > final_price
        else float(final_price)
    )
    verified["prezzo_verificato"] = True
    verified["sconto_val"] = int(discount_value)
    verified["sconto"] = f"-{discount_value}%" if discount_value > 0 else ""
    verified["source"] = "amazon_html_detail_verified"

    if sold_qty is not None:
        verified["sold_qty_month"] = sold_qty
        verified["sold_qty_label"] = sold_label

    return verified


def _verify_products_detail_prices(
    products: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Verifica più schede in parallelo conservando l'ordine originale."""
    if not products:
        return []

    results: list[Optional[dict[str, Any]]] = [None] * len(products)

    workers = max(1, min(DETAIL_PRICE_WORKERS, len(products)))

    with ThreadPoolExecutor(max_workers=workers) as executor:
        future_map = {
            executor.submit(_verify_product_detail_price, product): index
            for index, product in enumerate(products)
        }

        for future in as_completed(future_map):
            index = future_map[future]
            try:
                results[index] = future.result()
            except Exception:
                results[index] = dict(products[index])

    return [
        result if result is not None else dict(products[index])
        for index, result in enumerate(results)
    ]

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


def _html_response_classification(
    status_code: int,
    text: str,
) -> str:
    """Classifica una risposta HTML Amazon senza esporre dati sensibili."""
    if status_code != 200:
        return f"http_{status_code}"

    if not text:
        return "empty"

    if len(text) < 1500:
        return "too_short"

    lowered = text.lower()

    blocked_markers = (
        # Inglese
        "robot check",
        "enter the characters you see below",
        "sorry! something went wrong!",
        "automated access",
        "automated access to",
        "captcha",
        # Italiano
        "verifica che sei una persona reale",
        "verifica che tu sia una persona reale",
        "inserisci i caratteri",
        "inserisci i caratteri che vedi",
        "digita i caratteri",
        "digita i caratteri che vedi",
        "non siamo riusciti a verificare",
        "accesso automatizzato",
    )

    if any(marker in lowered for marker in blocked_markers):
        return "blocked"

    return "ok"


def _html_response_is_usable(status_code: int, text: str) -> bool:
    return _html_response_classification(status_code, text) == "ok"


def _html_has_search_product_signals(text: str) -> bool:
    """Controllo rapido, compatibile anche con markup Amazon nuovi.

    Non richiede i vecchi s-search-result/data-asin: un link /dp/ASIN è
    sufficiente perché il parser V22 sappia ricostruire una scheda.
    """
    if not text:
        return False

    lowered = text.lower()

    return any(
        signal in lowered
        for signal in (
            "s-search-result",
            "data-asin",
            "/dp/",
            "/gp/product/",
        )
    )


def _fetch_amazon_html(url: str, timeout: Optional[int] = None) -> Optional[str]:
    """Scarica HTML Amazon con fallback adattivo e diagnostica essenziale."""
    request_timeout = max(3, int(timeout or HTML_TIMEOUT))

    headers = {
        "Accept-Language": "it-IT,it;q=0.9,en-US;q=0.7,en;q=0.6",
        "Accept": (
            "text/html,application/xhtml+xml,application/xml;q=0.9,"
            "image/avif,image/webp,*/*;q=0.8"
        ),
    }
    cookies = {"lc-acbit": "it_IT", "i18n-prefs": "EUR"}

    # Primo fingerprint: Chrome generico. Il nome generico evita di dipendere
    # da una specifica release supportata soltanto da alcune versioni curl_cffi.
    if HAS_CURL_CFFI and c_requests is not None:
        chrome_returned_response = False

        try:
            response = c_requests.get(
                url,
                impersonate="chrome",
                timeout=request_timeout,
                headers=headers,
                cookies=cookies,
                allow_redirects=True,
            )
            chrome_returned_response = True
            classification = _html_response_classification(
                response.status_code,
                response.text,
            )

            LOGGER.info(
                "HTML curl profile=chrome status=%s class=%s len=%s",
                response.status_code,
                classification,
                len(response.text or ""),
            )

            if classification == "ok":
                return response.text

            # Se il server ci ha risposto velocemente ma con una pagina bloccata
            # o inutilizzabile, un fingerprint Safari può ottenere una risposta
            # diversa. Non lo facciamo dopo un timeout per non sommare altri 10s.
            if classification in {
                "blocked",
                "too_short",
                "http_403",
                "http_429",
                "http_503",
            }:
                try:
                    safari_response = c_requests.get(
                        url,
                        impersonate="safari",
                        timeout=request_timeout,
                        headers=headers,
                        cookies=cookies,
                        allow_redirects=True,
                    )
                    safari_classification = _html_response_classification(
                        safari_response.status_code,
                        safari_response.text,
                    )

                    LOGGER.info(
                        "HTML curl profile=safari status=%s class=%s len=%s",
                        safari_response.status_code,
                        safari_classification,
                        len(safari_response.text or ""),
                    )

                    if safari_classification == "ok":
                        return safari_response.text
                except Exception as exc:
                    LOGGER.info(
                        "HTML curl profile=safari error=%s",
                        type(exc).__name__,
                    )

        except Exception as exc:
            LOGGER.info(
                "HTML curl profile=chrome error=%s",
                type(exc).__name__,
            )

    # Fallback requests.Session con keep-alive/TLS riutilizzato per thread.
    try:
        session = _get_http_session()
        response = session.get(
            url,
            headers=headers,
            cookies=cookies,
            timeout=request_timeout,
            allow_redirects=True,
        )

        classification = _html_response_classification(
            response.status_code,
            response.text,
        )

        LOGGER.info(
            "HTML requests status=%s class=%s len=%s",
            response.status_code,
            classification,
            len(response.text or ""),
        )

        if classification == "ok":
            return response.text

    except requests.RequestException as exc:
        LOGGER.info(
            "HTML requests error=%s",
            type(exc).__name__,
        )

    return None


def _get_amazon_html_cached(url: str) -> Optional[str]:
    """Cache solo risposte Amazon realmente utili.

    Le SERP 200 ma prive di segnali prodotto non vengono cacheate: nei log
    dell'app corrispondono alle piccole pagine shell/challenge da 2-4 KB.
    """
    now = time.time()
    is_search = _is_amazon_search_url(url)

    if is_search and html_search_circuit_open():
        return None

    with _CACHE_LOCK:
        cached = _HTML_CACHE.get(url)
        if cached:
            cached_at, html_text = cached
            if now - cached_at < HTML_CACHE_TTL and html_text:
                if not is_search or _html_has_search_product_signals(html_text):
                    return html_text
            _HTML_CACHE.pop(url, None)

    html_text = _fetch_amazon_html(url)
    if not html_text:
        if is_search:
            _record_html_search_failure()
        return None

    if is_search and not _html_has_search_product_signals(html_text):
        LOGGER.info(
            "HTML search response rejected before cache len=%s url_path=%s",
            len(html_text or ""),
            urlparse(url).path,
        )
        _record_html_search_failure()
        return None

    if is_search:
        _record_html_search_success()

    with _CACHE_LOCK:
        _HTML_CACHE[url] = (now, html_text)
        if len(_HTML_CACHE) > SEARCH_HTML_CACHE_MAX:
            oldest = sorted(_HTML_CACHE.items(), key=lambda pair: pair[1][0])
            for key, _ in oldest[: len(_HTML_CACHE) - SEARCH_HTML_CACHE_MAX]:
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


def _extract_html_prime(item: Any) -> bool:
    prime_selector = (
        "i.a-icon-prime, span.a-icon-prime, "
        "[aria-label='Amazon Prime'], "
        "img[alt*='Prime'], img[alt*='prime']"
    )
    if item.select_one(prime_selector):
        return True

    return "prime" in item.get_text(" ", strip=True).lower()



def _extract_serp_prices(
    item: Any,
) -> tuple[Optional[float], Optional[float], int]:
    """Estrae prezzo attuale e prezzo barrato da una scheda risultati Amazon.

    Regole:
    - il prezzo attuale non può provenire da `.a-text-price`;
    - `data-a-color="base"` ha priorità;
    - il prezzo barrato viene cercato solo nei nodi dedicati;
    - se non esiste un prezzo barrato valido, old_price resta None.
    """
    current_price = 0.0

    current_selectors = (
        "span.a-price[data-a-color='base']:not(.a-text-price) .a-offscreen",
        (
            ".a-price-range "
            "span.a-price[data-a-color='base']:not(.a-text-price) .a-offscreen"
        ),
        (
            "span.a-price:not(.a-text-price)"
            ":not([data-a-strike='true']) .a-offscreen"
        ),
        (
            ".a-price-range "
            "span.a-price:not(.a-text-price)"
            ":not([data-a-strike='true']) .a-offscreen"
        ),
        "span.a-price:not(.a-text-price) .a-offscreen",
        ".a-color-price",
    )

    for selector in current_selectors:
        element = item.select_one(selector)
        if element is None:
            continue

        value = _parse_html_price(element.get_text(" ", strip=True))
        if value > 0:
            current_price = value
            break

    # Fallback whole/fraction, ma sempre limitato al nodo prezzo NON barrato.
    if current_price <= 0:
        base_price = (
            item.select_one(
                "span.a-price[data-a-color='base']:not(.a-text-price)"
                ":not([data-a-strike='true'])"
            )
            or item.select_one(
                "span.a-price:not(.a-text-price)"
                ":not([data-a-strike='true'])"
            )
        )

        if base_price is not None:
            whole = base_price.select_one(".a-price-whole")
            fraction = base_price.select_one(".a-price-fraction")

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
                    candidate = float(f"{whole_text}.{fraction_text}")
                except ValueError:
                    candidate = 0.0

                if candidate > 0:
                    current_price = candidate

    if current_price <= 0:
        return None, None, 0

    old_price: Optional[float] = None

    old_selectors = (
        "span.a-price.a-text-price .a-offscreen",
        "span.a-price[data-a-strike='true'] .a-offscreen",
    )

    for selector in old_selectors:
        element = item.select_one(selector)
        if element is None:
            continue

        candidate = _parse_html_price(element.get_text(" ", strip=True))
        if candidate > current_price:
            old_price = candidate
            break

    discount_value = 0
    if old_price is not None and old_price > current_price:
        discount_value = int(
            round(((old_price - current_price) / old_price) * 100)
        )

    return float(current_price), old_price, discount_value


def _best_serp_image_url(image: Any) -> str:
    """Sceglie l'immagine Amazon con la risoluzione più alta disponibile."""
    if image is None:
        return ""

    candidates: list[tuple[int, str]] = []

    dynamic_raw = str(image.get("data-a-dynamic-image") or "").strip()
    if dynamic_raw:
        try:
            dynamic = json.loads(dynamic_raw)
            if isinstance(dynamic, dict):
                for url, size in dynamic.items():
                    if not isinstance(url, str) or not url:
                        continue
                    score = 0
                    if isinstance(size, (list, tuple)) and len(size) >= 2:
                        try:
                            score = int(size[0]) * int(size[1])
                        except (TypeError, ValueError):
                            score = 0
                    candidates.append((score, url))
        except (ValueError, TypeError):
            pass

    srcset = str(image.get("srcset") or "").strip()
    if srcset:
        for part in srcset.split(","):
            chunk = part.strip()
            if not chunk:
                continue
            bits = chunk.rsplit(" ", 1)
            url = bits[0].strip()
            score = 0
            if len(bits) == 2:
                descriptor = bits[1].strip().lower()
                try:
                    if descriptor.endswith("w"):
                        score = int(float(descriptor[:-1]))
                    elif descriptor.endswith("x"):
                        score = int(float(descriptor[:-1]) * 1000)
                except ValueError:
                    score = 0
            if url:
                candidates.append((score, url))

    for attr in ("data-src", "src"):
        url = str(image.get(attr) or "").strip()
        if url:
            candidates.append((1, url))

    usable = [
        (score, url)
        for score, url in candidates
        if "transparent-pixel" not in url.lower()
        and "pixel" not in url.lower()
    ]
    if not usable:
        return ""

    usable.sort(key=lambda pair: pair[0], reverse=True)
    return usable[0][1]


def _nearest_search_product_container(link: Any) -> Any:
    """Trova una card prodotto anche se Amazon cambia i wrapper SERP."""
    if link is None:
        return None

    # Prima prova i wrapper noti.
    known = link.find_parent(
        attrs={"data-component-type": "s-search-result"}
    )
    if known is not None:
        return known

    known = link.find_parent(attrs={"data-asin": True})
    if known is not None:
        asin = str(known.get("data-asin") or "").strip()
        if len(asin) == 10:
            return known

    # Fallback robusto: risali pochi livelli e scegli il primo contenitore
    # abbastanza piccolo che abbia immagine + testo/prezzo.
    current = link.parent
    best = None

    for _ in range(8):
        if current is None:
            break

        try:
            text = current.get_text(" ", strip=True)
            has_image = current.select_one("img") is not None
            has_price = (
                current.select_one(".a-price")
                or current.select_one(".a-price-whole")
                or current.select_one(".a-color-price")
            ) is not None

            if has_image and len(text) >= 5:
                best = current
                # Una card con prezzo è preferibile: fermati subito.
                if has_price and len(text) < 7000:
                    return current

            # Evita di risalire fino all'intera pagina.
            if len(text) > 15000:
                break
        except Exception:
            pass

        current = current.parent

    return best or link.parent


def _title_from_search_node(
    node: Any,
    product_link: Any = None,
) -> str:
    """Titolo robusto: heading -> aria-label -> link -> alt immagine."""
    if node is None:
        return ""

    selectors = (
        "h2 a span",
        "h2 span",
        "h2",
        "h3 a span",
        "h3 span",
        "h3",
        "[data-cy='title-recipe']",
        ".a-size-medium.a-color-base.a-text-normal",
        ".a-size-base-plus.a-color-base.a-text-normal",
        ".a-size-base.a-color-base.a-text-normal",
    )

    for selector in selectors:
        element = node.select_one(selector)
        if element is not None:
            title = " ".join(element.get_text(" ", strip=True).split())
            if len(title) >= 3:
                return title

    link = product_link
    if link is None:
        link = (
            node.select_one("a[href*='/dp/']")
            or node.select_one("a[href*='/gp/product/']")
        )

    if link is not None:
        for attr in ("aria-label", "title"):
            title = " ".join(str(link.get(attr) or "").split())
            if len(title) >= 3:
                return title

        title = " ".join(link.get_text(" ", strip=True).split())
        if len(title) >= 3:
            return title

    image = node.select_one("img")
    if image is not None:
        title = " ".join(str(image.get("alt") or "").split())
        if len(title) >= 3:
            return title

    return ""


def _build_search_product_from_node(
    node: Any,
    partner_tag: str,
    min_price: Optional[float],
    max_price: Optional[float],
    require_prime: bool,
    asin_hint: str = "",
    href_hint: str = "",
    link_hint: Any = None,
) -> Optional[dict[str, Any]]:
    """Costruisce una scheda da qualunque card/link Amazon riconoscibile."""
    if node is None:
        return None

    asin = str(asin_hint or node.get("data-asin") or "").strip().upper()

    product_link = link_hint
    if product_link is None:
        product_link = (
            node.select_one("h2 a[href*='/dp/']")
            or node.select_one("h3 a[href*='/dp/']")
            or node.select_one("a.a-link-normal.s-no-outline[href*='/dp/']")
            or node.select_one("a[href*='/dp/']")
            or node.select_one("a[href*='/gp/product/']")
        )

    raw_href = str(href_hint or "").strip()
    if not raw_href and product_link is not None:
        raw_href = str(product_link.get("href") or "").strip()

    if len(asin) != 10 and raw_href:
        match = RE_ASIN.search(raw_href)
        if match:
            asin = match.group(1).upper()

    if len(asin) != 10:
        return None

    title = _title_from_search_node(node, product_link)
    if len(title) < 3:
        return None

    detail_page_url = _normalize_product_detail_url(raw_href, asin)

    image = node.select_one(
        "img.s-image, img[data-a-dynamic-image], img[srcset], img[data-src], img"
    )
    image_url = _best_serp_image_url(image)

    price, old_price, discount_value = _extract_serp_prices(node)
    price = float(price or 0.0)

    is_prime = _extract_html_prime(node)
    if require_prime and not is_prime:
        return None

    if min_price is not None:
        if price <= 0 or price < float(min_price):
            return None

    if max_price is not None:
        if price <= 0 or price > float(max_price):
            return None

    sold_qty_month, sold_qty_label = _extract_monthly_bought(node)

    return {
        "asin": asin,
        "titolo": title,
        "immagine_url": image_url,
        "prezzo_iniziale": old_price,
        "prezzo_finale": price if price > 0 else None,
        "prezzo_verificato": False,
        "_serp_price_confidence": (
            "base_price_node" if price > 0 else "missing"
        ),
        "sconto": f"-{discount_value}%" if discount_value > 0 else "",
        "sconto_val": discount_value,
        "saving_basis_label": "",
        "is_prime_exclusive": False,
        "is_prime": is_prime,
        "prime_filter_match": is_prime,
        "tipo_offerta": "",
        "sold_qty_month": sold_qty_month,
        "sold_qty_label": sold_qty_label,
        "sales_rank": None,
        "sales_rank_category": "",
        "detail_page_url": detail_page_url,
        "link_affiliato": _affiliate_detail_url(
            detail_page_url,
            asin,
            partner_tag,
        ),
        "source": "amazon_html_search",
    }


def _amazon_search_urls(keyword: str, page: int) -> tuple[str, ...]:
    """Più forme equivalenti della ricerca Amazon.

    Amazon può servire markup differente a seconda dell'URL/referrer.
    """
    clean = " ".join(str(keyword or "").strip().split())
    page_num = max(1, int(page or 1))

    variants = [
        f"https://www.amazon.it/s?{urlencode({'k': clean, 'page': page_num})}",
        f"https://www.amazon.it/s?{urlencode({'i': 'aps', 'k': clean, 'page': page_num})}",
        (
            "https://www.amazon.it/s?"
            + urlencode({
                "url": "search-alias=aps",
                "field-keywords": clean,
                "page": page_num,
            })
        ),
    ]

    # Mantieni ordine eliminando eventuali duplicati.
    return tuple(dict.fromkeys(variants))



def _amazon_mobile_search_urls(
    keyword: str,
    page: int,
) -> tuple[str, ...]:
    """Endpoint Amazon mobile/lightweight, diverso dalla SERP desktop."""
    clean = " ".join(str(keyword or "").strip().split())
    page_num = max(1, int(page or 1))

    variants = [
        "https://www.amazon.it/gp/aw/s?"
        + urlencode({"k": clean, "page": page_num}),
        "https://www.amazon.it/gp/aw/s?"
        + urlencode({"i": "aps", "k": clean, "page": page_num}),
    ]

    return tuple(dict.fromkeys(variants))

def _fetch_search_html_urls(
    urls: tuple[str, ...],
    keyword: str,
    page: int,
    stage: str,
) -> list[str]:
    """Scarica un piccolo gruppo di URL equivalenti in parallelo."""
    if not urls:
        return []

    workers = min(2, len(urls))
    ordered: dict[int, str] = {}

    with ThreadPoolExecutor(max_workers=workers) as executor:
        futures = {
            executor.submit(_get_amazon_html_cached, url): index
            for index, url in enumerate(urls)
        }

        for future in as_completed(futures):
            index = futures[future]
            try:
                html_text = future.result()
            except Exception:
                html_text = None

            if html_text:
                ordered[index] = html_text

    pages = [ordered[index] for index in sorted(ordered)]

    LOGGER.info(
        "HTML search stage=%s keyword=%r page=%s ok=%s/%s lengths=%s",
        stage,
        keyword,
        page,
        len(pages),
        len(urls),
        [len(text) for text in pages],
    )

    return pages



def _external_amazon_url(href: str) -> str:
    """Estrae un URL amazon.it diretto dai redirect di vari motori."""
    raw = html_lib.unescape(str(href or "").strip())
    if not raw:
        return ""

    # Link relativi Google (/url?q=...).
    if raw.startswith("/url?"):
        raw = "https://www.google.com" + raw

    try:
        parsed = urlparse(raw)
    except Exception:
        return ""

    host = (parsed.hostname or "").lower()

    if host in {"amazon.it", "www.amazon.it"}:
        return raw

    params = parse_qs(parsed.query)

    if "duckduckgo.com" in host:
        target = str((params.get("uddg") or [""])[0]).strip()
        if target:
            return _external_amazon_url(unquote(target))

    if "google." in host or host == "google.com" or host == "www.google.com":
        target = str((params.get("q") or params.get("url") or [""])[0]).strip()
        if target:
            return _external_amazon_url(unquote(target))

    if "bing.com" in host:
        # Alcuni link Bing sono diretti; altri usano u=a1<base64-url>.
        target = str((params.get("u") or [""])[0]).strip()
        if target.startswith("a1"):
            token = target[2:]
            try:
                padding = "=" * (-len(token) % 4)
                decoded = base64.urlsafe_b64decode(token + padding).decode(
                    "utf-8", errors="ignore"
                )
                return _external_amazon_url(decoded)
            except Exception:
                pass

    return ""


def _fetch_external_search_html(url: str) -> Optional[str]:
    try:
        session = _get_http_session()
        response = session.get(
            url,
            headers={
                "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
                "Accept-Language": "it-IT,it;q=0.9,en;q=0.6",
            },
            timeout=EXTERNAL_DISCOVERY_TIMEOUT,
            allow_redirects=True,
        )
        if response.status_code == 200 and len(response.text or "") >= 500:
            return response.text
        LOGGER.info(
            "External discovery http status=%s len=%s host=%s",
            response.status_code,
            len(response.text or ""),
            urlparse(url).hostname or "",
        )
    except requests.RequestException as exc:
        LOGGER.info(
            "External discovery error=%s host=%s",
            type(exc).__name__,
            urlparse(url).hostname or "",
        )
    return None


def _external_discovery_urls(keyword: str) -> dict[str, str]:
    clean = " ".join(str(keyword or "").strip().split())
    query = f'site:amazon.it/dp/ {clean}'
    return {
        "bing_rss": "https://www.bing.com/search?" + urlencode({
            "q": query,
            "format": "rss",
            "setlang": "it",
        }),
        "google": "https://www.google.com/search?" + urlencode({
            "q": query,
            "num": 20,
            "hl": "it",
        }),
        "duckduckgo": "https://html.duckduckgo.com/html/?" + urlencode({
            "q": query,
            "kl": "it-it",
        }),
    }


def _parse_external_engine_products(
    source: str,
    html_text: str,
    partner_tag: str,
    seen: set[str],
    target: int,
) -> list[dict[str, Any]]:
    found: list[dict[str, Any]] = []
    candidates: list[tuple[str, str]] = []

    if source == "bing_rss":
        try:
            root = ET.fromstring(html_text)
            for item in root.findall(".//item"):
                link = (item.findtext("link") or "").strip()
                title = " ".join((item.findtext("title") or "").split())
                candidates.append((link, title))
        except ET.ParseError:
            return []
    else:
        soup = BeautifulSoup(html_text, "html.parser")
        if source == "google":
            links = soup.select("a[href]")
        else:
            links = soup.select("a.result__a, a.result-link, .result a[href], a[href]")
        for link in links:
            href = str(link.get("href") or "").strip()
            title = " ".join(link.get_text(" ", strip=True).split())
            candidates.append((href, title))

    for href, title in candidates:
        amazon_url = _external_amazon_url(href)
        if not amazon_url:
            continue
        match = RE_ASIN.search(amazon_url)
        if not match:
            continue
        asin = match.group(1).upper()
        if asin in seen:
            continue
        seen.add(asin)
        detail_page_url = _normalize_product_detail_url(amazon_url, asin)
        if len(title) < 3:
            title = f"Prodotto Amazon {asin}"
        image_candidates = _asin_image_fallbacks(asin)
        primary_image = image_candidates[0] if image_candidates else ""

        found.append({
            "asin": asin,
            "titolo": title,
            "immagine_url": primary_image,
            "immagine_fallback_urls": list(image_candidates[1:]),
            "prezzo_iniziale": None,
            "prezzo_finale": None,
            "prezzo_verificato": False,
            "sconto": "",
            "sconto_val": 0,
            "saving_basis_label": "",
            "is_prime_exclusive": False,
            "is_prime": False,
            "prime_filter_match": False,
            "tipo_offerta": "",
            "sold_qty_month": None,
            "sold_qty_label": "",
            "sales_rank": None,
            "sales_rank_category": "",
            "detail_page_url": detail_page_url,
            "link_affiliato": _affiliate_detail_url(detail_page_url, asin, partner_tag),
            "source": f"external_discovery_{source}",
        })
        if len(found) >= target:
            break
    return found


def _discover_amazon_products_external(
    keyword: str,
    partner_tag: str,
    target: int,
    exclude_asins: set[str],
) -> list[dict[str, Any]]:
    """Interroga più indici in parallelo e usa solo URL amazon.it reali."""
    clean = " ".join(str(keyword or "").strip().split())
    if not clean or target <= 0:
        return []

    urls = _external_discovery_urls(clean)
    responses: dict[str, str] = {}

    with ThreadPoolExecutor(max_workers=len(urls)) as executor:
        future_map = {
            executor.submit(_fetch_external_search_html, url): source
            for source, url in urls.items()
        }
        for future in as_completed(future_map):
            source = future_map[future]
            try:
                text = future.result()
            except Exception:
                text = None
            if text:
                responses[source] = text

    seen = set(exclude_asins)
    found: list[dict[str, Any]] = []
    # Bing RSS è il formato più semplice; Google/DDG completano se necessario.
    for source in ("bing_rss", "google", "duckduckgo"):
        text = responses.get(source)
        if not text:
            continue
        remaining = target - len(found)
        if remaining <= 0:
            break
        products = _parse_external_engine_products(
            source, text, partner_tag, seen, remaining
        )
        found.extend(products)

    LOGGER.info(
        "External discovery multi keyword=%r sources_ok=%s products=%s target=%s",
        clean,
        len(responses),
        len(found),
        target,
    )
    _set_search_diagnostics(
        external_sources_ok=len(responses),
        external_products=len(found),
    )
    return found


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
    search_scope = (
        soup.select_one("#search")
        or soup.select_one("main")
        or soup
    )

    products: list[dict[str, Any]] = []
    seen_asins: set[str] = set()
    processed_nodes: set[int] = set()

    # Strategia 1: wrapper classici Amazon.
    items = list(
        search_scope.select("div[data-component-type='s-search-result']")
    )

    items.extend(
        node
        for node in search_scope.select("div[data-asin]")
        if len(str(node.get("data-asin") or "").strip()) == 10
    )

    items.extend(
        search_scope.select("div.s-result-item, li.s-result-item")
    )

    for item in items:
        node_id = id(item)
        if node_id in processed_nodes:
            continue
        processed_nodes.add(node_id)

        product = _build_search_product_from_node(
            item,
            partner_tag=partner_tag,
            min_price=min_price,
            max_price=max_price,
            require_prime=require_prime,
        )
        if not product:
            continue

        asin = str(product.get("asin") or "").strip().upper()
        if asin in seen_asins:
            continue

        seen_asins.add(asin)
        products.append(product)

    # Strategia 2: indipendente dal wrapper.
    # Se Amazon cambia il markup ma mantiene i link /dp/ASIN, il prodotto
    # continua a essere trovato.
    anchors = search_scope.select(
        "a[href*='/dp/'], a[href*='/gp/product/']"
    )

    for link in anchors:
        href = str(link.get("href") or "").strip()
        match = RE_ASIN.search(href)
        if not match:
            continue

        asin = match.group(1).upper()
        if asin in seen_asins:
            continue

        node = _nearest_search_product_container(link)
        if node is None:
            continue

        product = _build_search_product_from_node(
            node,
            partner_tag=partner_tag,
            min_price=min_price,
            max_price=max_price,
            require_prime=require_prime,
            asin_hint=asin,
            href_hint=href,
            link_hint=link,
        )
        if not product:
            continue

        seen_asins.add(asin)
        products.append(product)

    return products


def _search_html_fallback(
    keyword: str,
    sort_type: str,
    partner_tag: str,
    require_prime: bool,
    min_price: Optional[float],
    max_price: Optional[float],
    item_count: int,
    cache_buster: str = "",
    exclude_asins: tuple[str, ...] = (),
) -> tuple[dict[str, Any], ...]:
    # cache_buster serve alla Vetrina; la ricerca normale usa cache HTML
    # soltanto per risposte valide, mai per fallimenti.
    del cache_buster

    clean_keyword = " ".join(str(keyword or "").strip().split())
    if not clean_keyword:
        clean_keyword = "offerte del giorno"

    target = max(1, min(int(item_count or 10), MAX_RESULTS))

    _set_search_diagnostics(
        keyword=clean_keyword,
        reason="running",
        pages_attempted=0,
        html_variants_received=0,
        html_variants_with_product_signals=0,
        products_parsed=0,
        external_sources_ok=0,
        external_products=0,
    )

    diagnostic_pages_attempted = 0
    diagnostic_html_received = 0
    diagnostic_signal_pages = 0
    diagnostic_products_parsed = 0

    excluded = {
        str(asin).strip().upper()
        for asin in exclude_asins
        if str(asin).strip()
    }
    seen: set[str] = set(excluded)
    discovered: list[dict[str, Any]] = []

    # Per 10 nuovi prodotti bastano normalmente 1-2 pagine.
    # Consentiamo fino a 3 pagine per recuperare markup incompleto,
    # duplicati e prodotti esclusi, senza martellare Amazon.
    max_pages = min(
        5,
        max(3, math.ceil(target / 10) + 1),
    )

    def merge_html_page(
        html_text: str,
        page_number: int,
        page_seen: set[str],
    ) -> int:
        nonlocal diagnostic_signal_pages
        nonlocal diagnostic_products_parsed

        if not _html_has_search_product_signals(html_text):
            LOGGER.info(
                "HTML search skipped no-signals keyword=%r page=%s len=%s",
                clean_keyword,
                page_number,
                len(html_text or ""),
            )
            return 0

        diagnostic_signal_pages += 1

        parsed = _extract_products_from_html(
            html_text,
            partner_tag=partner_tag,
            min_price=min_price,
            max_price=max_price,
            require_prime=require_prime,
        )
        diagnostic_products_parsed += len(parsed)

        added = 0

        for page_index, product in enumerate(parsed):
            asin = str(product.get("asin") or "").strip().upper()

            if (
                len(asin) != 10
                or asin in seen
                or asin in page_seen
            ):
                continue

            page_seen.add(asin)
            seen.add(asin)

            product.setdefault(
                "_amazon_position",
                (page_number - 1) * 100 + page_index,
            )

            discovered.append(product)
            added += 1

            if len(discovered) >= target:
                break

        return added

    if html_search_circuit_open():
        LOGGER.info(
            "HTML search circuit open: skip Amazon SERP keyword=%r cooldown=%smin",
            clean_keyword,
            HTML_SEARCH_COOLDOWN // 60,
        )
        pages_to_scan = ()
    else:
        pages_to_scan = range(1, max_pages + 1)

    for page in pages_to_scan:
        if len(discovered) >= target:
            break

        diagnostic_pages_attempted += 1
        urls = _amazon_search_urls(clean_keyword, page)
        page_seen: set[str] = set()

        # ------------------------------------------------------------
        # FASE A: una sola URL principale.
        # Nel caso normale questa è l'unica richiesta SERP necessaria.
        # ------------------------------------------------------------
        primary_html = _get_amazon_html_cached(urls[0])

        if primary_html:
            diagnostic_html_received += 1
            merge_html_page(primary_html, page, page_seen)

        if len(discovered) >= target:
            break

        # ------------------------------------------------------------
        # FASE B: solo se servono ancora prodotti, prova le due forme
        # alternative in parallelo.
        # ------------------------------------------------------------
        alternate_pages = _fetch_search_html_urls(
            tuple(urls[1:]),
            keyword=clean_keyword,
            page=page,
            stage="alternates",
        )

        diagnostic_html_received += len(alternate_pages)

        for html_text in alternate_pages:
            merge_html_page(html_text, page, page_seen)
            if len(discovered) >= target:
                break

        if len(discovered) >= target:
            break

        # ------------------------------------------------------------
        # FASE C: Amazon mobile/lightweight.
        # Usa un percorso diverso da /s e può funzionare quando la SERP
        # desktop viene filtrata dai sistemi anti-bot.
        # ------------------------------------------------------------
        mobile_pages = _fetch_search_html_urls(
            _amazon_mobile_search_urls(clean_keyword, page),
            keyword=clean_keyword,
            page=page,
            stage="mobile",
        )

        diagnostic_html_received += len(mobile_pages)

        for html_text in mobile_pages:
            merge_html_page(html_text, page, page_seen)
            if len(discovered) >= target:
                break

        if len(discovered) >= target:
            break

        # ------------------------------------------------------------
        # FASE D: se la PRIMA pagina non ha prodotto alcun segnale utile,
        # un solo retry controllato dopo breve pausa.
        # Fallimenti non vengono cacheati, quindi questo è un fetch reale.
        # ------------------------------------------------------------
        if (
            page == 1
            and not discovered
            and diagnostic_signal_pages == 0
        ):
            time.sleep(0.8)

            retry_html = _get_amazon_html_cached(urls[0])
            if retry_html:
                diagnostic_html_received += 1
                merge_html_page(retry_html, page, page_seen)

            # Se anche primary + alternate + retry non contengono alcun
            # prodotto, cambiare pagina difficilmente supera un blocco IP.
            if not discovered and diagnostic_signal_pages == 0:
                LOGGER.info(
                    "HTML search stop early keyword=%r: no product signals after recovery",
                    clean_keyword,
                )
                break

        LOGGER.info(
            "HTML discovery keyword=%r page=%s total_discovered=%s target=%s",
            clean_keyword,
            page,
            len(discovered),
            target,
        )

    # -----------------------------------------------------------------
    # ULTIMA RISORSA: se Amazon Search desktop/mobile non ha prodotto
    # abbastanza ASIN, usa un indice web solo per trovare URL Amazon reali.
    # Poi la pagina prodotto Amazon resta la fonte di titolo/immagine/prezzo.
    # -----------------------------------------------------------------
    if len(discovered) < target:
        missing = target - len(discovered)

        external_products = _discover_amazon_products_external(
            keyword=clean_keyword,
            partner_tag=partner_tag,
            target=missing,
            exclude_asins=seen,
        )

        for product in external_products:
            asin = str(product.get("asin") or "").strip().upper()
            if len(asin) != 10 or asin in seen:
                continue

            seen.add(asin)
            product.setdefault(
                "_amazon_position",
                10_000 + len(discovered),
            )
            discovered.append(product)

            if len(discovered) >= target:
                break

    # -----------------------------------------------------------------
    # SECONDA FASE: la verifica prezzo non blocca più la discovery.
    # A questo punto abbiamo raccolto fino a 10 ASIN reali.
    # -----------------------------------------------------------------
    collected = list(discovered[:target])

    if collected:
        collected = _verify_products_detail_prices(collected)

    if collected:
        diagnostic_reason = "ok"
    elif diagnostic_html_received == 0:
        diagnostic_reason = "fetch_failed_or_blocked"
    elif diagnostic_signal_pages == 0:
        diagnostic_reason = "html_without_product_signals"
    elif diagnostic_products_parsed == 0:
        diagnostic_reason = "product_markup_not_parsed"
    else:
        diagnostic_reason = "no_matching_products"

    _set_search_diagnostics(
        keyword=clean_keyword,
        reason=diagnostic_reason,
        pages_attempted=diagnostic_pages_attempted,
        html_variants_received=diagnostic_html_received,
        html_variants_with_product_signals=diagnostic_signal_pages,
        products_parsed=diagnostic_products_parsed,
    )

    if sort_type == "Prezzo minimo":
        collected.sort(
            key=lambda product: (
                product.get("prezzo_finale") is None,
                float(product.get("prezzo_finale") or float("inf")),
                int(product.get("_amazon_position") or 0),
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
    exclude_asins: tuple[str, ...] = (),
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
    excluded_asins = {
        str(asin).strip().upper() for asin in exclude_asins if asin
    }
    seen_asins: set[str] = set(excluded_asins)

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
        item_count=max(1, missing),
        cache_buster=cache_buster,
        exclude_asins=tuple(sorted(seen_asins)),
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


@st.cache_data(ttl=5 * 60, show_spinner=False, max_entries=96)
def ottieni_vetrina_casuale(
    partner_tag: Optional[str] = None,
    item_count: int = 3,
    refresh_token: Optional[str] = None,
) -> list[dict[str, Any]]:
    """Vetrina veloce e resiliente.

    Prova più ricerche a rotazione e si ferma appena ottiene almeno
    un prodotto reale. Il target piccolo riduce il tempo di apertura.
    """
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
        "offerte amazon",
        "offerte del giorno",
    )

    target = max(1, min(int(item_count or 3), 3))
    selector = str(refresh_token or int(time.time() // (5 * 60)))
    digest = hashlib.sha256(selector.encode("utf-8")).digest()
    start_index = int.from_bytes(digest[:4], "big") % len(keywords)

    attempts = min(5, len(keywords))

    for offset in range(attempts):
        keyword = keywords[(start_index + offset) % len(keywords)]

        products = ottieni_offerte_avanzate(
            keyword=keyword,
            sort_type="Quantità vendite",
            item_count=target,
            _partner_tag_override=configured_tag,
            _cache_buster=f"vetrina:{selector}:{offset}",
        )

        if products:
            return list(products[:target])

    return []

def _haul_candidate_from_node(
    node: Any,
    partner_tag: str,
    asin_hint: str = "",
) -> Optional[dict[str, Any]]:
    """Converte un nodo HTML Haul in una scheda prodotto quando possibile."""
    if node is None:
        return None

    asin = str(asin_hint or node.get("data-asin") or "").strip().upper()

    link = (
        node.select_one("a[href*='/dp/']")
        or node.select_one("a[href*='/gp/product/']")
    )
    href = str(link.get("href") or "").strip() if link else ""

    if len(asin) != 10 and href:
        match = RE_ASIN.search(href)
        if match:
            asin = match.group(1).upper()

    if len(asin) != 10:
        return None

    detail_page_url = _normalize_product_detail_url(href, asin)

    image = node.select_one(
        "img.s-image, img[data-a-dynamic-image], img[srcset], img[data-src], img"
    )
    image_url = _best_serp_image_url(image)

    title = ""
    title_candidates = (
        node.select_one("h2 a span")
        or node.select_one("h2 span")
        or node.select_one("h3")
        or node.select_one("[data-cy='title-recipe']")
        or node.select_one(".a-size-base-plus")
        or node.select_one(".a-size-base.a-color-base")
    )

    if title_candidates is not None:
        title = title_candidates.get_text(" ", strip=True)

    if not title and link is not None:
        title = str(link.get("aria-label") or "").strip()
        if not title:
            title = link.get_text(" ", strip=True)

    if not title and image is not None:
        title = str(image.get("alt") or "").strip()

    title = " ".join(title.split())
    if len(title) < 3:
        return None

    price, old_price, discount_value = _extract_serp_prices(node)
    price = float(price or 0.0)

    sold_qty_month, sold_qty_label = _extract_monthly_bought(node)

    return {
        "asin": asin,
        "titolo": title,
        "immagine_url": image_url,
        "prezzo_iniziale": old_price,
        "prezzo_finale": price if price > 0 else None,
        # Sulla pagina HAUL il prezzo viene letto direttamente dalla card
        # ufficiale HAUL, quindi può essere mostrato come prezzo corrente
        # della pagina; resta comunque soggetto a variazioni Amazon.
        "prezzo_verificato": price > 0,
        "_serp_price_confidence": "haul_store_card" if price > 0 else "missing",
        "sconto": f"-{discount_value}%" if discount_value > 0 else "",
        "sconto_val": discount_value,
        "saving_basis_label": "",
        "is_prime_exclusive": False,
        "is_prime": False,
        "prime_filter_match": False,
        "tipo_offerta": "Amazon Haul",
        "sold_qty_month": sold_qty_month,
        "sold_qty_label": sold_qty_label,
        "sales_rank": None,
        "sales_rank_category": "",
        "detail_page_url": detail_page_url,
        "link_affiliato": _affiliate_detail_url(
            detail_page_url,
            asin,
            partner_tag,
        ),
        "source": "amazon_haul_store",
    }


def _extract_haul_products_from_html(
    html_text: str,
    partner_tag: str,
) -> list[dict[str, Any]]:
    """Estrae prodotti dalla pagina Amazon Haul con più strategie."""
    if not html_text:
        return []

    products: list[dict[str, Any]] = []
    seen: set[str] = set()

    # Prima strategia: parser Amazon già usato per SERP.
    for product in _extract_products_from_html(
        html_text,
        partner_tag=partner_tag,
    ):
        asin = str(product.get("asin") or "").strip().upper()
        if len(asin) != 10 or asin in seen:
            continue
        product["source"] = "amazon_haul_store"
        # Il prezzo arriva direttamente dalla pagina HAUL.
        if product.get("prezzo_finale") is not None:
            product["prezzo_verificato"] = True
        product["tipo_offerta"] = "Amazon Haul"
        seen.add(asin)
        products.append(product)

    soup = BeautifulSoup(html_text, "html.parser")

    # Seconda strategia: tutti i nodi con ASIN, anche se il markup HAUL
    # non usa s-search-result.
    for node in soup.select("[data-asin]"):
        asin = str(node.get("data-asin") or "").strip().upper()
        if len(asin) != 10 or asin in seen:
            continue

        product = _haul_candidate_from_node(
            node,
            partner_tag=partner_tag,
            asin_hint=asin,
        )
        if not product:
            continue

        seen.add(asin)
        products.append(product)

    # Terza strategia: anchor /dp/ non racchiuse in un data-asin.
    for link in soup.select("a[href*='/dp/'], a[href*='/gp/product/']"):
        href = str(link.get("href") or "").strip()
        match = RE_ASIN.search(href)
        if not match:
            continue

        asin = match.group(1).upper()
        if asin in seen:
            continue

        container = link
        best_node = None

        # Risali pochi livelli finché trovi un contenitore che abbia almeno
        # un'immagine o abbastanza testo da sembrare una card prodotto.
        for _ in range(6):
            if container is None:
                break
            text = container.get_text(" ", strip=True)
            if (
                container.select_one("img") is not None
                and len(text) >= 8
            ):
                best_node = container
            container = container.parent

        product = _haul_candidate_from_node(
            best_node or link,
            partner_tag=partner_tag,
            asin_hint=asin,
        )
        if not product:
            continue

        seen.add(asin)
        products.append(product)

    return products


@st.cache_data(ttl=3 * 60, show_spinner=False, max_entries=96)
def ottieni_haul_casuale(
    partner_tag: Optional[str] = None,
    item_count: int = 10,
    refresh_token: Optional[str] = None,
    exclude_asins: tuple[str, ...] = (),
) -> list[dict[str, Any]]:
    """Restituisce fino a 10 prodotti casuali reali dalla pagina Amazon Haul.

    Il refresh_token modifica il campionamento senza dover riscaricare
    necessariamente la stessa pagina HTML.
    """
    configured_tag = get_partner_tag() or str(partner_tag or "").strip()
    if not configured_tag:
        return []

    target = max(1, min(int(item_count or 10), 10))
    html_text = _get_amazon_html_cached(HAUL_STORE_URL)

    if not html_text:
        return []

    pool = _extract_haul_products_from_html(
        html_text,
        partner_tag=configured_tag,
    )

    if not pool:
        return []

    token = str(refresh_token or time.time_ns())
    digest = hashlib.sha256(token.encode("utf-8")).digest()
    seed = int.from_bytes(digest[:8], "big")
    rng = random.Random(seed)

    excluded = {
        str(asin).strip().upper()
        for asin in exclude_asins
        if str(asin).strip()
    }

    fresh = [
        product for product in pool
        if str(product.get("asin") or "").strip().upper() not in excluded
    ]
    previous = [
        product for product in pool
        if str(product.get("asin") or "").strip().upper() in excluded
    ]

    rng.shuffle(fresh)
    rng.shuffle(previous)

    selected = fresh[:target]

    # Se il pool non contiene 10 prodotti completamente nuovi, completa
    # con elementi del set precedente senza creare duplicati.
    if len(selected) < target:
        selected.extend(previous[: target - len(selected)])

    # Ultima rete di sicurezza se exclude_asins contiene ASIN non più presenti.
    if len(selected) < target:
        used = {
            str(product.get("asin") or "").strip().upper()
            for product in selected
        }
        remaining = [
            product for product in pool
            if str(product.get("asin") or "").strip().upper() not in used
        ]
        rng.shuffle(remaining)
        selected.extend(remaining[: target - len(selected)])

    return selected[:target]
