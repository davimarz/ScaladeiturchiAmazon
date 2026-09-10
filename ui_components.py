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
.stApp{background:#f8fafc;color:#0f172a;font-family:system-ui,-apple-system,"Segoe UI",sans-serif}
.block-container{max-width:900px;margin:0 auto;padding:.45rem .65rem 5rem}
.brand{background:#fff;border:1px solid #dbeafe;border-radius:14px;padding:10px 14px;margin-bottom:9px;box-shadow:0 2px 10px rgba(15,23,42,.05)}
.brand h1{margin:0;font-size:clamp(1.45rem,5vw,2rem);line-height:1.1;color:#075985}
.brand p{margin:4px 0 0;color:#475569;font-size:.9rem}
.nav-note{font-size:.83rem;color:#475569;margin:4px 0 10px}
.promo{background:#fff;border:1px solid #fed7aa;border-left:5px solid #f97316;border-radius:12px;padding:10px 12px;margin:4px 0 10px}
.promo strong{color:#9a3412}
.product-card{background:#fff;border:1px solid #dbeafe;border-radius:14px;padding:11px;margin:0 0 10px;box-shadow:0 2px 12px rgba(15,23,42,.05)}
.product-grid{display:grid;grid-template-columns:minmax(150px,240px) minmax(0,1fr);gap:14px;align-items:start}
.product-image{width:100%;aspect-ratio:1/1;object-fit:contain;background:#fff;border-radius:10px}
.product-title{font-size:1.04rem;font-weight:800;line-height:1.35;color:#0f172a;margin:0 0 8px;display:-webkit-box;-webkit-line-clamp:3;-webkit-box-orient:vertical;overflow:hidden}
.price-row{display:flex;align-items:baseline;gap:8px;flex-wrap:wrap;margin:5px 0}
.price{font-size:1.6rem;font-weight:900;color:#047857}.old{font-size:.92rem;color:#64748b;text-decoration:line-through}.discount{font-weight:800;color:#c2410c}
.meta{font-size:.82rem;color:#475569;line-height:1.45;margin:5px 0}.trust{font-size:.78rem;color:#475569;background:#f8fafc;border-radius:8px;padding:7px 8px;margin-top:7px}
.buy{display:inline-flex;align-items:center;justify-content:center;min-height:48px;padding:10px 15px;background:#0369a1;color:white!important;text-decoration:none!important;border-radius:9px;font-weight:800;width:100%;margin-top:9px}
.buy:focus-visible,.share:focus-visible{outline:3px solid #f59e0b;outline-offset:2px}.share-row{display:flex;gap:8px;flex-wrap:wrap;margin-top:8px}.share{min-height:44px;display:inline-flex;align-items:center;padding:8px 11px;border:1px solid #cbd5e1;border-radius:8px;color:#075985!important;text-decoration:none!important;background:#fff}
.compliance{font-size:.76rem;color:#475569;background:#f8fafc;border:1px solid #e2e8f0;border-radius:9px;padding:8px 9px;margin:8px 0}
.site-footer{font-size:.82rem;color:#475569;background:#fff;border:1px solid #e2e8f0;border-radius:12px;padding:10px 12px;margin-top:12px;line-height:1.5}
.stButton>button,.stLinkButton>a{min-height:44px!important}.stTextInput input{min-height:46px!important;font-size:16px!important}
@media(max-width:640px){.block-container{padding:.35rem .45rem 4.5rem}.product-grid{grid-template-columns:38% 62%;gap:9px}.product-card{padding:9px}.product-title{font-size:1rem;-webkit-line-clamp:4}.price{font-size:1.45rem}.meta,.trust{font-size:.82rem}.promo{padding:9px}.brand p{font-size:.84rem}}
@media(max-width:410px){.product-grid{grid-template-columns:36% 64%}.product-title{font-size:.96rem}}
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

    price_html = "<div class='price-row'><span class='price' style='font-size:1rem'>Prezzo da verificare su Amazon</span></div>"
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
    image_html = ""
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
        + f"<div class='trust'>Aggiornato: {html.escape(updated_label)}. Il prezzo può essere aumentato o modificato dall’ultimo aggiornamento.</div>"
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
