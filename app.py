from __future__ import annotations

import html
import logging
import re
import smtplib
import time
import urllib.parse
from email.message import EmailMessage

import streamlit as st

import amazon_api


st.set_page_config(
    page_title="Scaladeiturchi | Offerte Amazon AI",
    page_icon="🛍️",
    layout="wide",
    initial_sidebar_state="collapsed",
)

LOGGER = logging.getLogger("amazon_affiliate_app")
MAX_RESULTS = amazon_api.MAX_RESULTS
SORT_MAPPINGS = amazon_api.SORT_MAPPINGS

st.session_state.setdefault("current_tab", "vetrina")
st.session_state.setdefault("has_searched", False)
st.session_state.setdefault("item_count", 10)
st.session_state.setdefault("current_page", 1)
st.session_state.setdefault("offerte", [])
st.session_state.setdefault("search_notice", "")
st.session_state.setdefault(
    "last_search",
    {"keyword": "", "sort": "Prezzo minimo", "prime_only": False},
)
st.session_state.setdefault("contact_sent_session", False)
st.session_state.setdefault("offerte_vetrina", [])
st.session_state.setdefault("vetrina_refresh_token", str(time.time_ns()))
st.session_state.setdefault("vetrina_loaded_token", None)
st.session_state.setdefault("search_sort", "Prezzo minimo")
st.session_state.setdefault("search_keyword_input", "")
st.session_state.setdefault("search_prime_only", False)

# La scheda Contatti resta nel codice ma non è visibile/raggiungibile
# dalla navigazione pubblica.
if st.session_state.get("current_tab") == "contatti":
    st.session_state["current_tab"] = "vetrina"

try:
    if str(st.query_params.get("privacy", "")) == "1":
        st.session_state["current_tab"] = "privacy"
except Exception:
    pass


CSS = """
<style>
#MainMenu, header, footer {
    visibility: hidden !important;
    height: 0 !important;
}

*, *:before, *:after {
    box-sizing: border-box !important;
}

html {
    scroll-behavior: smooth !important;
}

.stApp {
    background: linear-gradient(
        135deg,
        #f0f9ff 0%,
        #e0f2fe 50%,
        #f0fdf4 100%
    ) !important;
    background-attachment: fixed !important;
    color: #0f172a !important;
    font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif !important;
}

.block-container {
    padding: 0.20rem 0.35rem 80px 0.35rem !important;
    max-width: 860px !important;
    margin: 0 auto !important;
}

/* HEADER: stile ripreso dal codice precedente */
.brand-header-box {
    text-align: center;
    padding: 5px 7px;
    margin: 0 auto 6px auto;
    width: 100%;
    background: rgba(255, 255, 255, 0.88);
    border: 1px solid rgba(2, 132, 199, 0.25);
    border-radius: 10px;
    box-shadow: 0 2px 8px rgba(2, 132, 199, 0.09);
}

.brand-title-single {
    font-size: clamp(1.30rem, 6vw, 1.95rem) !important;
    font-weight: 900 !important;
    background: linear-gradient(
        90deg,
        #0369a1 0%,
        #0284c7 60%,
        #0ea5e9 100%
    );
    -webkit-background-clip: text;
    -webkit-text-fill-color: transparent;
    margin: 0 !important;
    white-space: nowrap !important;
    overflow: hidden;
    text-overflow: ellipsis;
    line-height: 1.2 !important;
    letter-spacing: -0.3px;
}

.brand-subtitle-single {
    display: flex !important;
    align-items: center !important;
    justify-content: center !important;
    gap: 6px !important;
    white-space: nowrap !important;
    margin-top: 2px !important;
}

.badge-ai-pill {
    background: #0284c7;
    color: #ffffff;
    font-size: 0.65rem;
    font-weight: 900;
    padding: 3px 7px;
    border-radius: 4px;
    letter-spacing: 0.5px;
    line-height: 1;
    box-shadow: 0 1px 4px rgba(2, 132, 199, 0.25);
}

.brand-author {
    font-size: 0.72rem;
    color: #334155;
    font-weight: 600;
}

.brand-author strong {
    color: #0369a1;
}

/* NAV VETRINA / CERCA */
.nav-wrap {
    background: rgba(255, 255, 255, 0.95);
    border: 1.5px solid #bae6fd;
    border-radius: 10px;
    padding: 3px;
    margin-bottom: 8px;
    box-shadow: 0 2px 8px rgba(2, 132, 199, 0.08);
}

button[data-testid="stBaseButton-primary"] {
    background: linear-gradient(
        135deg,
        #0284c7 0%,
        #0369a1 100%
    ) !important;
    border: 1px solid #0284c7 !important;
    color: #ffffff !important;
    box-shadow: 0 2px 6px rgba(2, 132, 199, 0.30) !important;
    font-weight: 800 !important;
}

button[data-testid="stBaseButton-secondary"] {
    background-color: #ffffff !important;
    color: #0369a1 !important;
    border: 1.5px solid #cbd5e1 !important;
    font-weight: 700 !important;
}

button[data-testid="stBaseButton-secondary"]:hover {
    background: #f0f9ff !important;
    border-color: #0284c7 !important;
}

/* Il submit del form Cerca non deve ereditare il rosso del tema Streamlit. */
div[data-testid="stFormSubmitButton"] button,
.stFormSubmitButton button {
    background: linear-gradient(135deg, #38bdf8 0%, #0284c7 55%, #0369a1 100%) !important;
    border: 1px solid #0284c7 !important;
    color: #ffffff !important;
    font-weight: 900 !important;
    box-shadow: 0 2px 7px rgba(2, 132, 199, 0.30) !important;
}

div[data-testid="stFormSubmitButton"] button:hover,
.stFormSubmitButton button:hover {
    background: linear-gradient(135deg, #22c55e 0%, #059669 100%) !important;
    border-color: #059669 !important;
    color: #ffffff !important;
}

/* RICERCA */
div[data-testid="stTextInput"] input {
    border-radius: 9px !important;
    border: 1.5px solid #0284c7 !important;
    font-size: 0.84rem !important;
    font-weight: 600 !important;
    min-height: 38px !important;
    background-color: #ffffff !important;
    box-shadow: 0 1px 4px rgba(2, 132, 199, 0.12) !important;
}

div[data-testid="stRadio"] label[data-testid="stWidgetLabel"] p {
    color: #0369a1 !important;
    font-size: 0.74rem !important;
    font-weight: 800 !important;
}

div[data-testid="stRadio"] div[role="radiogroup"] {
    display: flex !important;
    flex-direction: row !important;
    flex-wrap: wrap !important;
    gap: 6px !important;
    width: 100% !important;
}

div[data-testid="stRadio"] div[role="radiogroup"] label {
    background: #ffffff !important;
    padding: 5px 14px !important;
    border-radius: 9999px !important;
    border: 1.5px solid #93c5fd !important;
    margin: 0 !important;
    flex: 1 1 auto !important;
    min-width: 0 !important;
    text-align: center !important;
    justify-content: center !important;
    cursor: pointer !important;
}

div[data-testid="stRadio"] div[role="radiogroup"] label:has(input:checked) {
    background: #0284c7 !important;
    border-color: #0284c7 !important;
}

div[data-testid="stRadio"] div[role="radiogroup"] label:has(input:checked) p,
div[data-testid="stRadio"] div[role="radiogroup"] label:has(input:checked) span {
    color: #ffffff !important;
    font-weight: 800 !important;
}

div[data-testid="stCheckbox"] {
    background: #ffffff !important;
    border: 1.5px solid #bae6fd !important;
    border-radius: 8px !important;
    padding: 4px 10px !important;
}

/* PANNELLO */
.tab-content-panel {
    background: rgba(255, 255, 255, 0.64);
    backdrop-filter: blur(10px);
    -webkit-backdrop-filter: blur(10px);
    border: 1.5px solid rgba(255, 255, 255, 0.90);
    border-radius: 12px;
    padding: 6px;
    box-shadow: 0 4px 18px rgba(2, 132, 199, 0.10);
}

/* SCHEDA PRODOTTO: palette più ricca come il vecchio sito */
.product-card-modern {
    background:
        linear-gradient(
            150deg,
            #ffffff 0%,
            #f0fdf4 52%,
            #ecfeff 100%
        );
    border: 1.5px solid #86efac;
    border-radius: 11px;
    padding: 8px;
    margin-bottom: 8px;
    box-shadow: 0 3px 12px rgba(5, 150, 105, 0.13);
}

.pcm-top {
    display: flex;
    align-items: center;
    gap: 11px;
}

.pcm-img-box {
    width: 160px;
    height: 160px;
    min-width: 160px;
    background: #ffffff;
    border: 1px solid #bfdbfe;
    border-radius: 9px;
    padding: 5px;
    display: flex;
    align-items: center;
    justify-content: center;
    overflow: hidden;
}

.pcm-img-box img {
    max-width: 100%;
    max-height: 100%;
    object-fit: contain;
}

.pcm-details {
    min-width: 0;
    flex: 1;
}

.pcm-title {
    font-size: 0.87rem;
    font-weight: 800;
    line-height: 1.28;
    color: #064e3b;
    display: -webkit-box;
    -webkit-line-clamp: 3;
    -webkit-box-orient: vertical;
    overflow: hidden;
    margin-bottom: 7px;
}

.pcm-prices {
    display: flex;
    align-items: baseline;
    gap: 6px;
    flex-wrap: wrap;
}

.pcm-discount-badge {
    background: #ef4444;
    color: #ffffff;
    font-size: 0.90rem;
    font-weight: 900;
    padding: 3px 7px;
    border-radius: 5px;
}

.pcm-price-final {
    font-size: 1.85rem;
    font-weight: 900;
    color: #059669;
    line-height: 1;
}

.pcm-price-old {
    font-size: 1.03rem;
    color: #64748b;
    text-decoration: line-through;
}

.pcm-note {
    color: #64748b;
    font-size: 0.65rem;
    line-height: 1.35;
    margin-top: 6px;
}

.pcm-badges-row {
    display: flex;
    flex-wrap: wrap;
    gap: 5px;
    margin-top: 6px;
}

.sales-rank-pill {
    background: #fff7ed;
    border: 1px solid #fdba74;
    color: #c2410c;
    padding: 3px 7px;
    border-radius: 6px;
    font-size: 0.66rem;
    font-weight: 800;
}

.prime-pill {
    background: linear-gradient(135deg, #00a8e8 0%, #007eb9 100%);
    color: #ffffff;
    padding: 3px 7px;
    border-radius: 6px;
    font-size: 0.66rem;
    font-weight: 900;
}

.pcm-bottom-bar {
    display: flex;
    align-items: center;
    justify-content: space-between;
    gap: 8px;
    flex-wrap: wrap;
    padding-top: 7px;
    margin-top: 8px;
    border-top: 1px solid #d1fae5;
}

.pcm-buy-btn-compact {
    display: inline-flex;
    align-items: center;
    justify-content: center;
    min-height: 34px;
    padding: 6px 18px;
    border-radius: 7px;
    background: linear-gradient(135deg, #fbbf24 0%, #f59e0b 100%);
    color: #0f172a !important;
    border: 1px solid #f59e0b;
    font-size: 0.80rem;
    font-weight: 900;
    text-decoration: none !important;
    box-shadow: 0 2px 5px rgba(245, 158, 11, 0.24);
}

.pcm-buy-btn-compact:hover {
    transform: translateY(-1px);
    background: linear-gradient(135deg, #f59e0b 0%, #d97706 100%);
}

.pcm-social-row {
    display: flex;
    gap: 5px;
    flex-wrap: wrap;
}

.soc-chip {
    display: inline-flex;
    align-items: center;
    justify-content: center;
    height: 28px;
    padding: 0 8px;
    border-radius: 6px;
    color: #ffffff !important;
    text-decoration: none !important;
    font-size: 0.62rem;
    font-weight: 800;
}

.soc-wa { background: #25D366; }
.soc-fb { background: #1877F2; }
.soc-tg { background: #229ED9; }
.soc-mail { background: #EA4335; }


.api-fallback-box {
    background: linear-gradient(135deg, rgba(255,255,255,.96) 0%, rgba(240,249,255,.96) 55%, rgba(240,253,244,.96) 100%);
    border: 1.5px solid #7dd3fc;
    border-radius: 11px;
    padding: 11px;
    margin: 7px 0 10px 0;
    box-shadow: 0 3px 12px rgba(2, 132, 199, 0.10);
}
.api-fallback-title {font-size:.86rem;font-weight:900;color:#0369a1;margin-bottom:4px;}
.api-fallback-text {font-size:.72rem;line-height:1.42;color:#475569;}
.amazon-search-direct {
    display:flex;align-items:center;justify-content:center;width:100%;min-height:39px;
    margin:6px 0;padding:8px 12px;border-radius:8px;
    background:linear-gradient(135deg,#38bdf8 0%,#0284c7 100%);
    border:1px solid #0284c7;color:#fff !important;text-decoration:none !important;
    font-size:.78rem;font-weight:900;box-shadow:0 2px 7px rgba(2,132,199,.24);
}
.amazon-search-direct:hover {background:linear-gradient(135deg,#34d399 0%,#059669 100%);border-color:#059669;transform:translateY(-1px);}
.fallback-category-grid {display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:7px;margin-top:8px;}
.fallback-category-link {
    display:flex;align-items:center;justify-content:center;min-height:42px;padding:7px 8px;
    border-radius:8px;background:#fff;border:1.5px solid #93c5fd;color:#0369a1 !important;
    text-decoration:none !important;font-size:.70rem;font-weight:850;text-align:center;
}
.fallback-category-link:hover {background:#eff6ff;border-color:#0284c7;}
@media (max-width:520px) {.fallback-category-grid {grid-template-columns:1fr;}}

.site-footer-box {
    background: rgba(255, 255, 255, 0.92);
    border: 1px solid rgba(2, 132, 199, 0.25);
    border-radius: 8px;
    padding: 8px 10px;
    margin: 15px 0 10px 0;
    text-align: center;
    color: #475569;
    font-size: 11px;
    line-height: 1.45;
}

.site-footer-box a {
    color: #0369a1;
    font-weight: 800;
}

@media (max-width: 580px) {
    .block-container {
        padding-left: 0.32rem !important;
        padding-right: 0.32rem !important;
    }

    .pcm-img-box {
        width: 126px;
        height: 126px;
        min-width: 126px;
    }

    .pcm-top {
        gap: 8px;
    }

    .pcm-price-final {
        font-size: 1.42rem;
    }

    .pcm-title {
        font-size: 0.79rem;
        -webkit-line-clamp: 3;
    }

    .pcm-bottom-bar {
        align-items: stretch;
    }

    .pcm-buy-btn-compact {
        width: 100%;
    }
}
</style>
"""

st.markdown(CSS, unsafe_allow_html=True)


def _clear_query_params() -> None:
    try:
        st.query_params.clear()
    except Exception:
        pass


def set_tab(tab_name: str) -> None:
    st.session_state["current_tab"] = tab_name
    _clear_query_params()


def open_vetrina() -> None:
    """Apre la vetrina e forza una nuova SearchItems."""
    st.session_state["current_tab"] = "vetrina"
    st.session_state["vetrina_refresh_token"] = str(time.time_ns())
    st.session_state["vetrina_loaded_token"] = None
    _clear_query_params()



def _sort_loaded_products(
    products: list[dict],
    sort_type: str,
) -> list[dict]:
    """Riordina localmente TUTTI i prodotti già caricati.

    Non effettua nuove chiamate Amazon. Il campo `_amazon_position`
    conserva l'ordine originale del fallback HTML anche dopo un precedente
    ordinamento per prezzo.
    """
    ordered = list(products or [])

    # Ordine di sicurezza per elementi che non hanno metadati di ranking.
    for index, product in enumerate(ordered):
        product.setdefault("_loaded_position", index)

    if sort_type == "Prezzo minimo":
        ordered.sort(
            key=lambda product: (
                product.get("prezzo_finale") is None,
                float(product.get("prezzo_finale") or float("inf")),
                int(product.get("_loaded_position") or 0),
            )
        )
        return ordered

    if sort_type == "Quantità vendite":
        def sales_key(product: dict) -> tuple:
            sales_rank = product.get("sales_rank")
            amazon_position = product.get("_amazon_position")
            loaded_position = int(product.get("_loaded_position") or 0)

            try:
                if sales_rank is not None:
                    return (0, int(sales_rank), loaded_position)
            except (TypeError, ValueError):
                pass

            try:
                if amazon_position is not None:
                    return (1, int(amazon_position), loaded_position)
            except (TypeError, ValueError):
                pass

            return (2, loaded_position, loaded_position)

        ordered.sort(key=sales_key)
        return ordered

    return ordered


def _on_search_sort_change() -> None:
    """Callback immediato quando l'utente cambia l'ordinamento."""
    selected_sort = str(
        st.session_state.get("search_sort") or "Prezzo minimo"
    )

    last_search = dict(st.session_state.get("last_search", {}))
    last_search["sort"] = selected_sort
    st.session_state["last_search"] = last_search

    loaded_products = list(st.session_state.get("offerte", []))
    if loaded_products:
        st.session_state["offerte"] = _sort_loaded_products(
            loaded_products,
            selected_sort,
        )
        # Dopo un cambio ordinamento mostriamo subito i migliori risultati.
        st.session_state["current_page"] = 1


def _perform_search(target_count: int) -> None:
    cfg = st.session_state["last_search"]
    target_count = max(10, min(int(target_count), MAX_RESULTS))

    with st.spinner("Ricerca prodotti su Amazon..."):
        results = amazon_api.ottieni_offerte_avanzate(
            keyword=cfg["keyword"],
            sort_type=cfg["sort"],
            solo_spedizione_gratuita=cfg["prime_only"],
            item_count=target_count,
        )

    normalized_results = list(results or [])

    for index, product in enumerate(normalized_results):
        product.setdefault("_loaded_position", index)

    st.session_state["offerte"] = _sort_loaded_products(
        normalized_results,
        str(cfg.get("sort") or "Prezzo minimo"),
    )
    st.session_state["item_count"] = target_count
    st.session_state["has_searched"] = True

    if not results:
        # Non mostriamo all'utente differenze tra API e fallback HTML.
        st.session_state["search_notice"] = (
            "Nessun prodotto trovato. Prova con una parola chiave diversa."
        )
    elif len(results) < target_count:
        st.session_state["search_notice"] = (
            f"Sono disponibili {len(results)} prodotti per questa ricerca."
        )
    else:
        st.session_state["search_notice"] = ""

def _load_more() -> None:
    current_target = int(st.session_state.get("item_count", 10) or 10)

    if current_target >= MAX_RESULTS:
        st.session_state["search_notice"] = (
            f"Limite di {MAX_RESULTS} prodotti raggiunto."
        )
        return

    new_target = min(MAX_RESULTS, current_target + 10)
    previous_count = len(st.session_state.get("offerte", []))
    _perform_search(new_target)

    new_count = len(st.session_state.get("offerte", []))

    if new_count > previous_count:
        st.session_state["current_page"] = max(1, (new_count + 9) // 10)
    else:
        st.session_state["search_notice"] = (
            "Non risultano altri prodotti disponibili per questa ricerca."
        )


def _format_eur(value: float) -> str:
    return (
        f"{value:,.2f}"
        .replace(",", "X")
        .replace(".", ",")
        .replace("X", ".")
    )


def _share_urls(title: str, link: str, price: Optional[float]) -> dict[str, str]:
    message = title.strip()

    if price is not None and price > 0:
        message += f"\nPrezzo: €{_format_eur(price)}"

    message += f"\n{link}"

    return {
        "wa": f"https://wa.me/?text={urllib.parse.quote(message)}",
        "tg": (
            "https://t.me/share/url?"
            f"url={urllib.parse.quote(link)}&text={urllib.parse.quote(message)}"
        ),
        "fb": (
            "https://www.facebook.com/sharer/sharer.php?"
            f"u={urllib.parse.quote(link)}"
        ),
        "mail": (
            "mailto:?subject="
            f"{urllib.parse.quote('Offerta Amazon')}"
            "&body="
            f"{urllib.parse.quote(message)}"
        ),
    }


IMG_FALLBACK_SVG = (
    "data:image/svg+xml;utf8,"
    "<svg xmlns='http://www.w3.org/2000/svg' width='300' height='300' "
    "viewBox='0 0 24 24' fill='none' stroke='%230284c7' stroke-width='1.5'>"
    "<rect x='2' y='3' width='20' height='14' rx='2'></rect>"
    "<line x1='8' y1='21' x2='16' y2='21'></line>"
    "<line x1='12' y1='17' x2='12' y2='21'></line>"
    "</svg>"
)


def render_product_card(product: dict) -> None:
    title = str(product.get("titolo") or "Prodotto Amazon")
    link = str(product.get("link_affiliato") or "")
    image_url = str(product.get("immagine_url") or IMG_FALLBACK_SVG)

    safe_title = html.escape(title)
    safe_title_attr = html.escape(title, quote=True)
    safe_link = html.escape(link, quote=True)
    safe_image = html.escape(image_url, quote=True)
    safe_fallback = html.escape(IMG_FALLBACK_SVG, quote=True)

    verified = product.get("prezzo_verificato") is True

    final_price = None
    old_price = None

    try:
        if product.get("prezzo_finale") is not None:
            final_price = float(product["prezzo_finale"])
    except (TypeError, ValueError):
        final_price = None

    try:
        if product.get("prezzo_iniziale") is not None:
            old_price = float(product["prezzo_iniziale"])
    except (TypeError, ValueError):
        old_price = None

    if verified and final_price is not None and final_price > 0:
        discount = html.escape(str(product.get("sconto") or ""))

        discount_html = (
            f"<span class='pcm-discount-badge'>{discount}</span>"
            if discount
            else ""
        )

        old_html = ""
        if old_price is not None and old_price > final_price:
            old_html = (
                f"<span class='pcm-price-old'>€{_format_eur(old_price)}</span>"
            )

        price_html = (
            f"{discount_html}"
            f"<span class='pcm-price-final'>€{_format_eur(final_price)}</span>"
            f"{old_html}"
        )
    else:
        price_html = (
            "<span class='pcm-price-final' style='font-size:1.05rem;'>"
            "Verifica prezzo su Amazon"
            "</span>"
        )

    badge_parts = []

    sales_rank = product.get("sales_rank")
    if sales_rank:
        try:
            rank_int = int(sales_rank)
            rank_category = html.escape(
                str(product.get("sales_rank_category") or "Amazon")
            )
            badge_parts.append(
                f"<span class='sales-rank-pill'>"
                f"Vendite rank #{rank_int:,} · {rank_category}"
                f"</span>"
            )
        except (TypeError, ValueError):
            pass

    if product.get("is_prime_exclusive") is True:
        badge_parts.append(
            "<span class='prime-pill'>✓ Prime esclusiva</span>"
        )

    badges_html = "".join(badge_parts)

    source = str(product.get("source") or "")
    if source == "amazon_html":
        note = "Prezzo rilevato dalla pagina Amazon; può variare."
    else:
        note = "Prezzo verificato tramite i dati Amazon disponibili."

    saving_basis_label = str(product.get("saving_basis_label") or "").strip()

    if (
        saving_basis_label
        and old_price is not None
        and final_price is not None
        and old_price > final_price
    ):
        note += f" Rif.: {html.escape(saving_basis_label)}."

    if sales_rank:
        note += " Il rank vendite non indica il numero esatto di unità vendute."

    share = _share_urls(
        title,
        link,
        final_price if verified else None,
    )

    card_html = (
        "<div class='product-card-modern'>"
        "<div class='pcm-top'>"
        "<div class='pcm-img-box'>"
        f"<img src='{safe_image}' loading='lazy' "
        f"alt='{safe_title_attr}' "
        f"onerror=\"this.onerror=null;this.src='{safe_fallback}';\">"
        "</div>"
        "<div class='pcm-details'>"
        f"<div class='pcm-title'>{safe_title}</div>"
        f"<div class='pcm-prices'>{price_html}</div>"
        f"<div class='pcm-badges-row'>{badges_html}</div>"
        f"<div class='pcm-note'>{html.escape(note)}</div>"
        "</div>"
        "</div>"
        "<div class='pcm-bottom-bar'>"
        f"<a class='pcm-buy-btn-compact' href='{safe_link}' "
        "target='_blank' rel='noopener noreferrer sponsored'>"
        "🛒 Acquista su Amazon"
        "</a>"
        "<div class='pcm-social-row'>"
        f"<a class='soc-chip soc-wa' href='{html.escape(share['wa'], quote=True)}' "
        "target='_blank' rel='noopener noreferrer'>WA</a>"
        f"<a class='soc-chip soc-fb' href='{html.escape(share['fb'], quote=True)}' "
        "target='_blank' rel='noopener noreferrer'>FB</a>"
        f"<a class='soc-chip soc-tg' href='{html.escape(share['tg'], quote=True)}' "
        "target='_blank' rel='noopener noreferrer'>TG</a>"
        f"<a class='soc-chip soc-mail' href='{html.escape(share['mail'], quote=True)}'>"
        "Mail</a>"
        "</div>"
        "</div>"
        "</div>"
    )

    st.markdown(card_html, unsafe_allow_html=True)


EMAIL_REGEX = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


def validate_contact(
    name: str,
    phone: str,
    email: str,
    message: str,
) -> tuple[bool, str]:
    name = name.strip()
    phone_digits = re.sub(r"\D", "", phone)
    email = email.strip()
    message = message.strip()

    if not name or not phone_digits or not email or not message:
        return False, "Compila tutti i campi obbligatori."

    if len(name) < 3:
        return False, "Inserisci un nome valido."

    if not 8 <= len(phone_digits) <= 15:
        return False, "Inserisci un numero di telefono valido."

    if not EMAIL_REGEX.fullmatch(email):
        return False, "Inserisci un indirizzo email valido."

    if len(message) < 10:
        return False, "Il messaggio deve contenere almeno 10 caratteri."

    return True, ""


def send_contact_email(
    name: str,
    phone: str,
    user_email: str,
    message: str,
) -> tuple[bool, str]:
    email_cfg = st.secrets.get("email", {})
    sender = str(email_cfg.get("sender", "")).strip()
    app_password = str(email_cfg.get("app_password", "")).replace(" ", "")
    recipient = str(email_cfg.get("recipient") or sender).strip()

    if not sender or not app_password or not recipient:
        LOGGER.error("Configurazione email incompleta nei Secrets.")
        return False, "Servizio email non configurato."

    mail = EmailMessage()
    mail["From"] = f"Scala dei Turchi <{sender}>"
    mail["To"] = recipient
    mail["Reply-To"] = user_email
    mail["Subject"] = f"[Scala dei Turchi] Messaggio da {name}"
    mail.set_content(
        "Nuovo messaggio dal sito:\n\n"
        f"Nome: {name}\n"
        f"Telefono: {phone}\n"
        f"Email: {user_email}\n\n"
        f"Messaggio:\n{message}\n"
    )

    try:
        with smtplib.SMTP_SSL("smtp.gmail.com", 465, timeout=8) as server:
            server.login(sender, app_password)
            server.send_message(mail)

        return True, ""
    except Exception as exc:
        LOGGER.error("Invio email fallito: %s", type(exc).__name__)
        return False, "Invio non riuscito. Riprova più tardi."


# HEADER
st.markdown(
    """
    <div id="top_page"></div>
    <div class="brand-header-box">
        <div class="brand-title-single">Scala dei Turchi</div>
        <div class="brand-subtitle-single">
            <span class="badge-ai-pill">AI DEALS</span>
            <span class="brand-author">by <strong>Davide Marziano</strong></span>
        </div>
    </div>
    """,
    unsafe_allow_html=True,
)

active_tab = st.session_state.get("current_tab", "vetrina")

# NAV PUBBLICA: Contatti volutamente nascosta.
st.markdown("<div class='nav-wrap'>", unsafe_allow_html=True)
nav1, nav2 = st.columns(2)

with nav1:
    st.button(
        "🔥 Vetrina",
        key="nav_btn_vetrina",
        type="primary" if active_tab == "vetrina" else "secondary",
        on_click=open_vetrina,
        use_container_width=True,
    )

with nav2:
    st.button(
        "🔍 Cerca",
        key="nav_btn_cerca",
        type="primary" if active_tab == "cerca" else "secondary",
        on_click=set_tab,
        args=("cerca",),
        use_container_width=True,
    )

st.markdown("</div>", unsafe_allow_html=True)

partner_tag = amazon_api.get_partner_tag()

if not partner_tag:
    st.error(
        "Configurazione Amazon incompleta: aggiungi partner_tag e credenziali "
        "Creators API nei Secrets di Streamlit."
    )

active_tab = st.session_state.get("current_tab", "vetrina")
st.markdown("<div class='tab-content-panel'>", unsafe_allow_html=True)

if active_tab == "vetrina":
    st.markdown(
        """
        <h2 style='font-size:.94rem;font-weight:900;color:#0369a1;
        margin:2px 0 2px 2px;'>🔥 Offerte in Vetrina</h2>
        <p style='font-size:.70rem;color:#64748b;margin:0 0 7px 2px;'>
        La Vetrina viene aggiornata quando ricarichi la pagina o premi Vetrina.
        </p>
        """,
        unsafe_allow_html=True,
    )

    current_token = str(st.session_state["vetrina_refresh_token"])

    if (
        st.session_state.get("vetrina_loaded_token") != current_token
        and partner_tag
    ):
        with st.spinner("Aggiornamento offerte Amazon..."):
            showcase = amazon_api.ottieni_vetrina_casuale(
                item_count=10,
                refresh_token=current_token,
            )

        st.session_state["offerte_vetrina"] = list(showcase or [])
        st.session_state["vetrina_loaded_token"] = current_token

    showcase = st.session_state.get("offerte_vetrina", [])

    if showcase:
        for product in showcase:
            render_product_card(product)
    else:
        st.info(
            "Nessun prodotto disponibile in vetrina al momento. "
            "Ricarica la pagina tra poco."
        )

elif active_tab == "cerca":
    st.markdown(
        """
        <h2 style='font-size:.94rem;font-weight:900;color:#0369a1;
        margin:2px 0 5px 2px;'>🔍 Cerca su Amazon</h2>
        """,
        unsafe_allow_html=True,
    )

    previous = st.session_state.get("last_search", {})
    sort_keys = list(SORT_MAPPINGS.keys())

    previous_sort = str(previous.get("sort") or "Prezzo minimo")
    if previous_sort not in sort_keys:
        previous_sort = "Prezzo minimo"

    if st.session_state.get("search_sort") not in sort_keys:
        st.session_state["search_sort"] = previous_sort

    # Inizializza i controlli dalla ricerca precedente solo quando vuoti.
    if (
        not st.session_state.get("search_keyword_input")
        and previous.get("keyword")
    ):
        st.session_state["search_keyword_input"] = str(previous.get("keyword") or "")

    search_col, button_col = st.columns([5, 1])

    with search_col:
        st.text_input(
            "Prodotto",
            placeholder="Cosa cerchi su Amazon? Es. iPhone, scarpe, cuffie...",
            label_visibility="collapsed",
            key="search_keyword_input",
        )

    with button_col:
        submitted = st.button(
            "🔍 Cerca",
            key="search_submit_button",
            type="primary",
            use_container_width=True,
        )

    st.radio(
        "Ordinamento:",
        sort_keys,
        horizontal=True,
        key="search_sort",
        on_change=_on_search_sort_change,
    )

    if st.session_state.get("search_sort") == "Quantità vendite":
        st.caption(
            "Il cambio è immediato su tutte le schede già caricate. "
            "Viene usato il ranking Amazon disponibile; non viene inventato "
            "un numero di unità vendute."
        )

    st.checkbox(
        "🚚 Solo risultati compatibili con il filtro Prime di Amazon",
        key="search_prime_only",
    )

    if submitted:
        st.session_state["last_search"] = {
            "keyword": str(
                st.session_state.get("search_keyword_input") or ""
            ).strip(),
            "sort": str(
                st.session_state.get("search_sort") or "Prezzo minimo"
            ),
            "prime_only": bool(
                st.session_state.get("search_prime_only", False)
            ),
        }
        st.session_state["current_page"] = 1
        st.session_state["item_count"] = 10
        _perform_search(10)

    if st.session_state.get("search_notice"):
        st.info(st.session_state["search_notice"])

    results = st.session_state.get("offerte", [])

    if results:
        total = len(results)
        pages = max(1, (total + 9) // 10)
        current_page = min(
            max(1, int(st.session_state.get("current_page", 1))),
            pages,
        )
        st.session_state["current_page"] = current_page

        if pages > 1:
            page_cols = st.columns(pages)

            for page_number, col in enumerate(page_cols, start=1):
                with col:
                    if st.button(
                        f"P.{page_number}",
                        type=(
                            "primary"
                            if page_number == current_page
                            else "secondary"
                        ),
                        key=f"page_{page_number}",
                        use_container_width=True,
                    ):
                        st.session_state["current_page"] = page_number
                        st.rerun()

        start = (current_page - 1) * 10
        end = min(start + 10, total)

        st.markdown(
            f"<p style='font-size:.74rem;font-weight:800;color:#0284c7;"
            f"margin:5px 0;'>Prodotti {start + 1}-{end} di {total}</p>",
            unsafe_allow_html=True,
        )

        for product in results[start:end]:
            render_product_card(product)

        st.button(
            "➕ Carica altri 10 prodotti ⬇️",
            on_click=_load_more,
            use_container_width=True,
            disabled=int(st.session_state.get("item_count", 10)) >= MAX_RESULTS,
        )

    elif (
        st.session_state.get("has_searched")
        and not st.session_state.get("search_notice")
    ):
        st.warning(
            "Nessun prodotto trovato. Prova con una parola chiave diversa."
        )

elif active_tab == "privacy":
    st.markdown(
        "<h2 style='font-size:.94rem;color:#0369a1;'>Informativa privacy</h2>",
        unsafe_allow_html=True,
    )

    st.markdown(
        """
        I dati inseriti nel modulo contatti vengono utilizzati esclusivamente
        per rispondere alla richiesta inviata. Il sito può contenere collegamenti
        esterni ad Amazon.it.

        Le credenziali tecniche del sito sono conservate nei Secrets di
        Streamlit e non devono essere pubblicate nel repository GitHub.
        """
    )

    st.button(
        "← Torna alla vetrina",
        on_click=open_vetrina,
    )

# Il ramo resta deliberatamente nel codice, ma non esiste alcun pulsante pubblico
# che imposti current_tab="contatti".
elif active_tab == "contatti":
    st.subheader("Contatti")

    if st.session_state.get("contact_sent_session"):
        st.success("Messaggio già inviato in questa sessione.")

    with st.form("contact_form", clear_on_submit=True):
        name = st.text_input("Nome e cognome*")
        phone = st.text_input("Telefono*")
        user_email = st.text_input("Email*")
        message = st.text_area("Messaggio*", height=120)
        privacy_ack = st.checkbox("Ho letto l'informativa privacy.*")

        send = st.form_submit_button(
            "✉️ Invia messaggio",
            use_container_width=True,
            disabled=bool(st.session_state.get("contact_sent_session")),
        )

    if send:
        valid, validation_message = validate_contact(
            name,
            phone,
            user_email,
            message,
        )

        if not valid:
            st.error(validation_message)
        elif not privacy_ack:
            st.error("Conferma di aver letto l'informativa privacy.")
        else:
            with st.spinner("Invio in corso..."):
                ok, error_message = send_contact_email(
                    name.strip(),
                    phone.strip(),
                    user_email.strip(),
                    message.strip(),
                )

            if ok:
                st.session_state["contact_sent_session"] = True
                st.success("Messaggio inviato correttamente.")
            else:
                st.error(error_message)

st.markdown("</div>", unsafe_allow_html=True)

st.markdown(
    """
    <div class="site-footer-box">
        Prezzi e disponibilità possono variare su Amazon.<br>
        <a href="?privacy=1" target="_self">Informativa privacy</a>
    </div>
    """,
    unsafe_allow_html=True,
)
