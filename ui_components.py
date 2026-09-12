from __future__ import annotations

import html
import math
import urllib.parse
from datetime import datetime
from zoneinfo import ZoneInfo
from urllib.parse import urlparse

import streamlit as st

import catalog_service

ROME = ZoneInfo("Europe/Rome")
PRICE_DISCLAIMER = (
    "I prezzi e la disponibilità sono accurati alla data/ora indicata e possono cambiare. "
    "Il prezzo e la disponibilità mostrati su Amazon.it al momento dell’acquisto sono quelli applicabili."
)

CSS = """
<style>
#MainMenu, header, footer {visibility:hidden!important;height:0!important}
*{box-sizing:border-box}
html{scroll-behavior:smooth}
.stApp{background:#f4f8fc;color:#0f172a;font-family:system-ui,-apple-system,"Segoe UI",sans-serif}
.block-container{max-width:880px;margin:0 auto;padding:.35rem .55rem 4.5rem}

/* Header */
.brand{background:#fff;border:1px solid #d7e5f4;border-radius:12px;padding:11px 14px 10px;margin-bottom:7px;box-shadow:0 2px 8px rgba(15,23,42,.04)}
.brand h1{margin:0!important;font-size:clamp(1.45rem,4vw,1.8rem)!important;line-height:1.08!important;color:#075985;font-weight:850!important;letter-spacing:-.02em}
.brand p{margin:5px 0 0!important;color:#526173;font-size:.82rem!important;line-height:1.35!important}
.nav-note{font-size:.78rem;color:#64748b;margin:3px 0 8px}

/* Navigation and Streamlit controls */
div[data-testid="stHorizontalBlock"]{gap:.55rem!important}
button[data-testid="stBaseButton-primary"]{background:#0877b2!important;border:1px solid #0877b2!important;color:#fff!important;box-shadow:none!important;font-weight:750!important}
button[data-testid="stBaseButton-primary"]:hover{background:#06679b!important;border-color:#06679b!important}
button[data-testid="stBaseButton-secondary"]{background:#fff!important;border:1px solid #cbd5e1!important;color:#334155!important;box-shadow:none!important;font-weight:650!important}
button[data-testid="stBaseButton-secondary"]:hover{border-color:#7aaed0!important;background:#f8fbfe!important;color:#075985!important}
.stButton>button,.stLinkButton>a{min-height:42px!important;border-radius:9px!important;font-size:.86rem!important}
.stTextInput input{min-height:44px!important;font-size:16px!important;border-radius:9px!important}

/* Intro boxes */
.promo{background:#fff;border:1px solid #f8c58e;border-left:4px solid #f97316;border-radius:10px;padding:9px 11px;margin:6px 0 8px;font-size:.84rem;line-height:1.45;color:#334155}
.promo strong{color:#9a3412}
.compliance{font-size:.70rem!important;line-height:1.4!important;color:#64748b;background:#f8fafc;border:1px solid #e2e8f0;border-radius:8px;padding:7px 9px;margin:7px 0 8px}

/* Product cards */
.product-card{background:#fff;border:1px solid #d8e6f4;border-radius:12px;padding:10px;margin:0 0 9px;box-shadow:0 2px 9px rgba(15,23,42,.045)}
.product-grid{display:grid;grid-template-columns:minmax(132px,205px) minmax(0,1fr);gap:12px;align-items:start}
.product-image{display:block;width:100%;aspect-ratio:1/1;object-fit:contain;background:#fff;border-radius:9px}
h3.product-title,.product-title{font-size:.94rem!important;font-weight:780!important;line-height:1.28!important;color:#172033!important;margin:1px 0 6px!important;padding:0!important;letter-spacing:-.01em;display:-webkit-box;-webkit-line-clamp:3;-webkit-box-orient:vertical;overflow:hidden;max-height:3.84em}
.price-row{display:flex;align-items:baseline;gap:7px;flex-wrap:wrap;margin:3px 0 4px}
.price{font-size:1.30rem!important;line-height:1.1!important;font-weight:850!important;color:#047857}
.old{font-size:.80rem;color:#64748b;text-decoration:line-through}
.discount{font-size:.79rem;font-weight:750;color:#c2410c}
.meta{font-size:.75rem!important;color:#526173;line-height:1.35;margin:4px 0}
.trust{font-size:.68rem!important;line-height:1.35!important;color:#64748b;background:#f8fafc;border:1px solid #eef2f7;border-radius:7px;padding:5px 7px;margin-top:5px}
.buy{display:inline-flex;align-items:center;justify-content:center;min-height:43px;padding:8px 12px;background:#0877b2;color:white!important;text-decoration:none!important;border-radius:8px;font-size:.86rem!important;font-weight:800;width:100%;margin-top:7px}
.buy:hover{background:#06679b}
.buy:focus-visible,.share:focus-visible{outline:3px solid #f59e0b;outline-offset:2px}
.share-row{display:flex;gap:6px;flex-wrap:wrap;margin-top:6px}
.share{min-height:36px;display:inline-flex;align-items:center;padding:6px 10px;border:1px solid #cbd5e1;border-radius:7px;color:#075985!important;text-decoration:none!important;background:#fff;font-size:.76rem!important}
.share:hover{background:#f8fbfe;border-color:#93b8d1}

.site-footer{font-size:.76rem;color:#64748b;background:#fff;border:1px solid #e2e8f0;border-radius:10px;padding:9px 11px;margin-top:10px;line-height:1.45}

@media(max-width:640px){
  .block-container{padding:.3rem .4rem 4rem}
  .brand{padding:9px 11px}
  .brand h1{font-size:1.45rem!important}
  .brand p{font-size:.78rem!important}
  div[data-testid="stHorizontalBlock"]{gap:.35rem!important}
  .stButton>button,.stLinkButton>a{min-height:40px!important;font-size:.80rem!important;padding:.35rem .45rem!important}
  .promo{font-size:.79rem;padding:8px 9px}
  .compliance{font-size:.66rem!important;padding:6px 7px}
  .product-card{padding:8px;border-radius:10px}
  .product-grid{grid-template-columns:34% 66%;gap:8px}
  h3.product-title,.product-title{font-size:.86rem!important;line-height:1.25!important;-webkit-line-clamp:3;max-height:3.75em;margin:0 0 5px!important}
  .price{font-size:1.17rem!important}
  .old,.discount{font-size:.72rem!important}
  .meta{font-size:.69rem!important}
  .trust{font-size:.62rem!important;padding:4px 6px}
  .buy{min-height:40px;font-size:.80rem!important;padding:7px 8px}
  .share-row{gap:5px}
  .share{min-height:34px;font-size:.70rem!important;padding:5px 8px}
}

@media(max-width:420px){
  .product-grid{grid-template-columns:32% 68%;gap:7px}
  h3.product-title,.product-title{font-size:.82rem!important}
  .price{font-size:1.10rem!important}
  .share{padding:5px 7px}
}
</style>
"""


def inject_css() -> None:
    st.markdown(CSS, unsafe_allow_html=True)


def _amazon_url(url: str) -> str:
    raw = str(url or "").strip()
    try:
        parsed = urlparse(raw)
    except Exception:
        return ""
    host = (parsed.hostname or "").lower()
    if parsed.scheme != "https" or not (host == "amazon.it" or host.endswith(".amazon.it")):
        return ""
    return raw


def _image_url(url: str) -> str:
    raw = str(url or "").strip()
    try:
        parsed = urlparse(raw)
    except Exception:
        return ""
    if parsed.scheme != "https":
        return ""
    return raw


def _format_eur(value: float) -> str:
    return f"{value:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")


def _share_urls(title: str, link: str, price: float | None) -> dict[str, str]:
    message = title.strip()
    if price is not None:
        message += f"\nPrezzo indicato: €{_format_eur(price)}"
    message += f"\n{link}"
    return {
        "wa": "https://wa.me/?text=" + urllib.parse.quote(message),
        "tg": "https://t.me/share/url?" + urllib.parse.urlencode({"url": link, "text": message}),
        "mail": "mailto:?" + urllib.parse.urlencode({"subject": "Offerta Amazon", "body": message}),
    }


def render_brand() -> None:
    st.markdown(
        "<div class='brand'><h1>Scala dei Turchi</h1><p>Offerte Amazon selezionate e ricerca prodotti</p></div>",
        unsafe_allow_html=True,
    )


def render_price_notice() -> None:
    st.markdown(
        "<div class='compliance'><strong>Nota prezzi:</strong> "
        + html.escape(PRICE_DISCLAIMER)
        + " Alcuni contenuti di prodotto provengono da Amazon.</div>",
        unsafe_allow_html=True,
    )


def render_product_card(product: dict, eager_image: bool = False) -> None:
    title = str(product.get("titolo") or "Prodotto Amazon").strip()
    link = _amazon_url(str(product.get("link_affiliato") or product.get("detail_page_url") or ""))
    image = _image_url(str(product.get("immagine_url") or ""))
    if not link:
        return

    final_price: float | None = None
    old_price: float | None = None
    if catalog_service.price_is_displayable(product):
        try:
            candidate = float(product.get("prezzo_finale"))
            if math.isfinite(candidate) and candidate > 0:
                final_price = candidate
        except (TypeError, ValueError):
            final_price = None
        try:
            candidate_old = float(product.get("prezzo_iniziale"))
            if math.isfinite(candidate_old) and candidate_old > 0:
                old_price = candidate_old
        except (TypeError, ValueError):
            old_price = None

    fetched_at = product.get("_fetched_at")
    try:
        dt = datetime.fromtimestamp(float(fetched_at), tz=ROME)
        updated_label = dt.strftime("%d/%m/%Y %H:%M CET/CEST")
    except Exception:
        updated_label = "ora non disponibile"

    price_html = "<div class='price-row'><span class='price' style='font-size:.88rem!important'>Prezzo da verificare su Amazon</span></div>"
    if final_price is not None:
        parts = [f"<span class='price'>€{_format_eur(final_price)}</span>"]
        if old_price is not None and old_price > final_price:
            parts.append(f"<span class='old'>€{_format_eur(old_price)}</span>")
            parts.append(f"<span class='discount'>Risparmi €{_format_eur(old_price-final_price)}</span>")
        discount = str(product.get("sconto") or "").strip()
        if discount:
            parts.append(f"<span class='discount'>{html.escape(discount)}</span>")
        price_html = "<div class='price-row'>" + "".join(parts) + "</div>"

    optional_meta: list[str] = []
    size = str(product.get("size") or "").strip()
    color = str(product.get("color") or "").strip()
    if size:
        optional_meta.append("Taglia: " + size)
    if color:
        optional_meta.append("Colore: " + color)
    sold = str(product.get("sold_qty_label") or "").strip()
    if sold:
        optional_meta.append(sold)
    elif product.get("sales_rank"):
        optional_meta.append("Indicatore di popolarità Amazon disponibile")

    share = _share_urls(title, link, final_price)
    if image:
        loading = "eager" if eager_image else "lazy"
        priority = "high" if eager_image else "auto"
        image_html = (
            f"<img class='product-image' src='{html.escape(image, quote=True)}' loading='{loading}' "
            f"fetchpriority='{priority}' decoding='async' alt='{html.escape(title, quote=True)}'>"
        )
    else:
        image_html = "<div class='product-image' role='img' aria-label='Immagine non disponibile'></div>"

    meta_html = ""
    if optional_meta:
        meta_html = "<div class='meta'>" + html.escape(" · ".join(optional_meta)) + "</div>"

    card = (
        "<article class='product-card'>"
        "<div class='product-grid'><div>" + image_html + "</div><div>"
        f"<h3 class='product-title'>{html.escape(title)}</h3>"
        + price_html + meta_html
        + f"<div class='trust'>Aggiornato: {html.escape(updated_label)}. Il prezzo può cambiare su Amazon.</div>"
        + f"<a class='buy' href='{html.escape(link, quote=True)}' target='_blank' rel='noopener noreferrer sponsored'>Vedi offerta su Amazon</a>"
        + "<div class='share-row'>"
        + f"<a class='share' href='{html.escape(share['wa'], quote=True)}' target='_blank' rel='noopener noreferrer'>WhatsApp</a>"
        + f"<a class='share' href='{html.escape(share['tg'], quote=True)}' target='_blank' rel='noopener noreferrer'>Telegram</a>"
        + f"<a class='share' href='{html.escape(share['mail'], quote=True)}'>Email</a>"
        + "</div></div></div></article>"
    )
    st.markdown(card, unsafe_allow_html=True)


def render_footer() -> None:
    st.markdown(
        """
        <div class="site-footer">
          In qualità di Affiliato Amazon ricevo un guadagno dagli acquisti idonei.<br>
          <a href="?privacy=1" target="_self">Informativa privacy</a> ·
          <a href="https://github.com/davimarz" target="_blank" rel="noopener noreferrer">Contatto del titolare</a>
        </div>
        """,
        unsafe_allow_html=True,
    )
