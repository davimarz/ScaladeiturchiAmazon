from __future__ import annotations

import html
import math
import urllib.parse
from datetime import datetime
from urllib.parse import urlparse
from zoneinfo import ZoneInfo

import streamlit as st

import catalog_service

ROME = ZoneInfo("Europe/Rome")
PRICE_DISCLAIMER = (
    "I prezzi e la disponibilità possono cambiare. "
    "Fanno fede il prezzo e la disponibilità mostrati su Amazon.it al momento dell’acquisto."
)

CSS = """
<style>
:root{
  --brand:#1f7fb7;--brand-dark:#075985;--brand-soft:#eaf5fb;
  --surface:#ffffff;--page:#f4f8fc;--text:#172033;--muted:#5f6f82;
  --border:#d8e6f4;--success:#047857;--warning:#c2410c;--haul:#f97316;
  --amazon-ink:#131921;--amazon-ink-hover:#232f3e;--amazon-orange:#ff9900;
  --r-control:8px;--r-card:10px;--r-shell:12px;
}
*{box-sizing:border-box}
html{scroll-behavior:smooth}
.stApp{background:var(--page);color:var(--text);font-family:system-ui,-apple-system,"Segoe UI",sans-serif}
.block-container{max-width:880px;margin:0 auto;padding:.35rem .55rem 4.5rem}
#top-anchor{position:absolute;top:0}
.brand{background:var(--surface);border:1px solid var(--border);border-radius:var(--r-shell);padding:11px 14px 10px;margin-bottom:7px;box-shadow:0 2px 8px rgba(15,23,42,.04)}
.brand h1{margin:0!important;font-size:clamp(1.42rem,4vw,1.78rem)!important;line-height:1.08!important;color:var(--brand-dark);font-weight:800!important;letter-spacing:-.02em}
.brand p{margin:5px 0 0!important;color:var(--muted);font-size:.82rem!important;line-height:1.35!important}
.section-kicker{font-size:.72rem;font-weight:800;text-transform:uppercase;letter-spacing:.08em;color:var(--brand-dark);margin:7px 0 5px}
.sr-only{position:absolute!important;width:1px!important;height:1px!important;padding:0!important;margin:-1px!important;overflow:hidden!important;clip:rect(0,0,0,0)!important;white-space:nowrap!important;border:0!important}
.st-key-main_nav{position:sticky;top:.25rem;z-index:100;background:rgba(244,248,252,.96);padding:3px 0 5px;backdrop-filter:blur(7px)}
.st-key-main_nav div[data-testid="stHorizontalBlock"]{display:flex!important;flex-wrap:nowrap!important;gap:.35rem!important;align-items:stretch!important}
.st-key-main_nav div[data-testid="column"]{flex:1 1 0!important;min-width:0!important;width:33.333%!important}
.st-key-main_nav .stButton{width:100%!important}
.st-key-main_nav .stButton>button{width:100%!important;white-space:nowrap!important;overflow:hidden!important;text-overflow:ellipsis!important}
.stButton>button,.stLinkButton>a{min-height:44px!important;border-radius:var(--r-control)!important;font-size:.86rem!important;font-weight:700!important}
.stTextInput input{min-height:44px!important;font-size:16px!important;border-radius:var(--r-control)!important}
button[kind="primary"]{background:var(--brand)!important;border-color:var(--brand)!important;color:#fff!important}
button[kind="secondary"]{background:#fff!important;border-color:#cbd5e1!important;color:#334155!important}

.promo{background:#fff;border:1px solid var(--border);border-left:4px solid var(--brand);border-radius:var(--r-card);padding:8px 10px;margin:6px 0 8px;font-size:.82rem;line-height:1.42;color:#334155}
.haul-badge{display:inline-block;background:#fff4e8;color:#a84b08;border:1px solid #fed7aa;border-radius:999px;padding:2px 7px;margin-right:5px;font-size:.70rem;font-weight:800;letter-spacing:.03em}
.compliance{font-size:.73rem!important;line-height:1.42!important;color:var(--muted);background:#f8fafc;border:1px solid #e2e8f0;border-radius:var(--r-control);padding:6px 8px;margin:6px 0 8px}
.compliance details{cursor:pointer}.compliance summary{font-weight:700;color:#475569}

.product-card{background:#fff;border:1px solid var(--border);border-radius:var(--r-card);padding:10px;margin:0 0 9px;box-shadow:0 2px 9px rgba(15,23,42,.04);transition:transform .14s ease,box-shadow .14s ease,border-color .14s ease}
.product-card:hover{transform:translateY(-1px);box-shadow:0 5px 16px rgba(15,23,42,.07);border-color:#bdd8ea}
.product-grid{display:grid;grid-template-columns:minmax(132px,198px) minmax(0,1fr);gap:12px;align-items:start}
.product-image-link{display:flex;align-items:center;justify-content:center;width:100%;aspect-ratio:1/1;border-radius:9px;background:#fff;overflow:hidden}
.product-image{display:block;max-width:100%;max-height:100%;width:100%;height:100%;background:#fff;border-radius:9px;object-fit:contain;object-position:center}
.product-placeholder{display:flex;align-items:center;justify-content:center;width:100%;aspect-ratio:1/1;border-radius:9px;background:#f8fafc;border:1px dashed #cbd5e1;color:#64748b;font-size:.72rem;text-align:center;padding:10px}
.product-title-link{text-decoration:none!important;color:inherit!important}
h3.product-title,.product-title{font-size:.90rem!important;font-weight:700!important;line-height:1.27!important;color:var(--text)!important;margin:1px 0 5px!important;padding:0!important;letter-spacing:-.01em;display:-webkit-box;-webkit-line-clamp:3;-webkit-box-orient:vertical;overflow:hidden;max-height:3.81em}
.product-title-link:hover .product-title{color:var(--brand-dark)!important;text-decoration:underline}
.price-row{display:flex;align-items:baseline;gap:7px;flex-wrap:wrap;margin:3px 0 4px}
.price{font-size:1.40rem!important;line-height:1.08!important;font-weight:800!important;color:var(--success)}
.price-unavailable{font-size:.87rem!important;line-height:1.25!important;font-weight:700!important;color:#526173}
.old{font-size:.80rem;color:#64748b;text-decoration:line-through}.discount{font-size:.79rem;font-weight:700;color:var(--warning)}
.meta{font-size:.75rem!important;color:#526173;line-height:1.35;margin:4px 0}.prime-verified{font-weight:700;color:#047857}.prime-card{font-weight:700;color:#526173}
.trust{font-size:.73rem!important;line-height:1.35!important;color:#64748b;background:#f8fafc;border:1px solid #eef2f7;border-radius:7px;padding:5px 7px;margin-top:5px}
.buy{display:inline-flex;align-items:center;justify-content:center;min-height:44px;padding:8px 12px;background:var(--amazon-ink);color:#fff!important;text-decoration:none!important;border:1px solid var(--amazon-ink);border-radius:var(--r-control);font-family:Arial,Helvetica,sans-serif;font-size:.87rem!important;font-weight:700;width:100%;margin-top:7px;box-shadow:inset 0 -3px 0 var(--amazon-orange)}
.buy:hover{background:var(--amazon-ink-hover)}.buy .amazon-label strong{color:var(--amazon-orange);font-weight:800}
.buy:focus-visible,.share:focus-visible,.back-top:focus-visible{outline:3px solid var(--amazon-orange);outline-offset:2px}
.share-details{margin-top:6px}.share-details summary{cursor:pointer;color:var(--brand-dark);font-size:.74rem;font-weight:700;list-style:none}.share-details summary::-webkit-details-marker{display:none}
.share-row{display:flex;gap:6px;flex-wrap:wrap;margin-top:6px}.share{min-height:44px;display:inline-flex;align-items:center;padding:6px 10px;border:1px solid #cbd5e1;border-radius:7px;color:var(--brand-dark)!important;text-decoration:none!important;background:#fff;font-size:.74rem!important}
.back-top{display:inline-flex;min-height:44px;align-items:center;padding:7px 10px;border:1px solid #cbd5e1;border-radius:8px;background:#fff;color:var(--brand-dark)!important;text-decoration:none!important;font-size:.76rem;font-weight:700;margin:2px 0 8px}
.site-footer{font-size:.76rem;color:#64748b;background:#fff;border:1px solid #e2e8f0;border-radius:var(--r-card);padding:9px 11px;margin-top:10px;line-height:1.45}

@keyframes card-loading-pulse{0%,100%{background-color:#fff}50%{background-color:#f8fbfe}}
.stSpinner{min-height:86px!important;border:1px solid var(--border)!important;border-radius:var(--r-card)!important;background:#fff!important;padding:12px 14px!important;margin:0 0 9px!important;display:flex!important;align-items:center!important;animation:card-loading-pulse 1.25s ease-in-out infinite}

@media (prefers-reduced-motion: reduce){html{scroll-behavior:auto}.product-card,.buy{transition:none}.product-card:hover,.buy:hover{transform:none}.stSpinner{animation:none}}
@media(max-width:640px){
 .block-container{padding:.3rem .4rem 4rem}.brand{padding:9px 11px}.brand h1{font-size:1.42rem!important}.brand p{font-size:.78rem!important}
 .stButton>button,.stLinkButton>a{min-height:44px!important;font-size:.80rem!important;padding:.35rem .45rem!important}
 .st-key-main_nav{padding:2px 0 4px}.st-key-main_nav div[data-testid="stHorizontalBlock"]{gap:.25rem!important}.st-key-main_nav .stButton>button{font-size:.78rem!important;padding:.3rem .25rem!important;min-height:42px!important}
 .promo{font-size:.79rem;padding:8px 9px}.compliance{font-size:.72rem!important;padding:6px 7px}.product-card{padding:8px;border-radius:10px;box-shadow:none}
 .product-card:hover{transform:none;box-shadow:none;border-color:var(--border)}
 .stSpinner{min-height:76px!important;box-shadow:none!important;padding:10px!important}
 .product-grid{grid-template-columns:34% 66%;gap:8px}h3.product-title,.product-title{font-size:.84rem!important;line-height:1.25!important;-webkit-line-clamp:3;max-height:3.75em;margin:0 0 5px!important}
 .price{font-size:1.22rem!important}.old,.discount{font-size:.74rem!important}.meta{font-size:.72rem!important}.trust{font-size:.72rem!important;padding:4px 6px}.buy{min-height:44px;font-size:.80rem!important;padding:7px 8px}.share{min-height:44px;font-size:.72rem!important}
}
@media(max-width:430px){
 .product-grid{grid-template-columns:32% 68%;gap:7px}h3.product-title,.product-title{font-size:.82rem!important}.price{font-size:1.18rem!important}
 .st-key-main_nav div[data-testid="stHorizontalBlock"]{flex-direction:row!important;flex-wrap:nowrap!important}.st-key-main_nav div[data-testid="column"]{flex:1 1 0!important;min-width:0!important;width:33.333%!important}.st-key-main_nav .stButton>button{font-size:.75rem!important;padding:.25rem .15rem!important}
 .st-key-search_controls div[data-testid="stHorizontalBlock"]{flex-wrap:wrap}.st-key-search_controls div[data-testid="column"]:first-child{flex-basis:100%!important;width:100%!important}.st-key-search_controls div[data-testid="column"]:not(:first-child){flex:1 1 calc(50% - .25rem)!important;width:auto!important}
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
    host = (parsed.hostname or "").lower()
    allowed = (
        host.endswith(".media-amazon.com")
        or host.endswith(".ssl-images-amazon.com")
        or host.endswith(".amazon.com")
        or host.endswith(".amazon.it")
    )
    if parsed.scheme != "https" or not allowed:
        return ""
    return raw


def _image_candidates(product: dict) -> list[str]:
    values = [product.get("immagine_url")]
    fallbacks = product.get("immagine_fallback_urls") or []
    if isinstance(fallbacks, str):
        fallbacks = [fallbacks]
    values.extend(fallbacks)
    result: list[str] = []
    for value in values:
        clean = _image_url(str(value or ""))
        if clean and clean not in result:
            result.append(clean)
    return result[:2]


def _image_markup(product: dict, link: str, title: str, eager_image: bool) -> str:
    candidates = _image_candidates(product)
    if not candidates:
        return "<div class='product-placeholder' role='img' aria-label='Immagine non disponibile'>Immagine non disponibile</div>"
    image = candidates[0]
    loading = "eager" if eager_image else "lazy"
    priority = "high" if eager_image else "auto"
    return (
        f"<a class='product-image-link' href='{html.escape(link, quote=True)}' target='_blank' rel='noopener noreferrer sponsored' aria-label='Apri {html.escape(title, quote=True)} su Amazon'>"
        f"<img class='product-image' src='{html.escape(image, quote=True)}' alt='{html.escape(title, quote=True)}' loading='{loading}' fetchpriority='{priority}' decoding='async' width='198' height='198'>"
        "</a>"
    )


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
    st.markdown("<div id='top-anchor'></div><div class='brand'><h1>Scala dei Turchi</h1><p>Offerte Amazon selezionate e ricerca prodotti</p></div>", unsafe_allow_html=True)


def render_nav_accessibility(active_tab: str) -> None:
    labels = {"haul": "HAUL", "vetrina": "Vetrina", "cerca": "Cerca", "privacy": "Privacy"}
    label = labels.get(active_tab, active_tab)
    st.markdown(f"<span class='sr-only' aria-current='page'>Sezione attiva: {html.escape(label)}</span>", unsafe_allow_html=True)


def render_section_label(text: str) -> None:
    st.markdown(f"<div class='section-kicker'>{html.escape(text)}</div>", unsafe_allow_html=True)


def render_price_notice() -> None:
    st.markdown("<div class='compliance'><details><summary>Informazioni su prezzi e disponibilità</summary><div style='margin-top:4px'>" + html.escape(PRICE_DISCLAIMER) + " Alcuni contenuti di prodotto provengono da Amazon.</div></details></div>", unsafe_allow_html=True)


def _format_timestamp(value: object) -> str:
    try:
        dt = datetime.fromtimestamp(float(value), tz=ROME)
        return dt.strftime("%d/%m/%Y %H:%M")
    except Exception:
        return ""


def render_product_card(product: dict, eager_image: bool = False) -> None:
    title = str(product.get("titolo") or "Prodotto Amazon").strip()
    link = _amazon_url(str(product.get("link_affiliato") or product.get("detail_page_url") or ""))
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
            pass
        try:
            candidate_old = float(product.get("prezzo_iniziale"))
            if math.isfinite(candidate_old) and candidate_old > 0:
                old_price = candidate_old
        except (TypeError, ValueError):
            pass

    fetched_label = _format_timestamp(product.get("_fetched_at"))
    price_label = _format_timestamp(product.get("price_verified_at"))

    price_html = "<div class='price-row'><span class='price-unavailable'>Prezzo su Amazon</span></div>"
    if final_price is not None:
        parts = [f"<span class='price'>€{_format_eur(final_price)}</span>"]
        if old_price is not None and old_price > final_price:
            parts.append(f"<span class='old'>€{_format_eur(old_price)}</span>")
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
        optional_meta.append("Popolarità Amazon disponibile")

    prime_html = ""
    if product.get("prime") or product.get("is_prime"):
        if product.get("prime_detail_verified"):
            prime_html = "<span class='prime-verified'>Prime verificato</span>"
        else:
            prime_html = "<span class='prime-card'>Prime rilevato</span>"

    share = _share_urls(title, link, final_price)
    image_html = _image_markup(product, link, title, eager_image)
    meta_parts = []
    if optional_meta:
        meta_parts.append(html.escape(" · ".join(optional_meta)))
    if prime_html:
        meta_parts.append(prime_html)
    meta_html = "<div class='meta'>" + " · ".join(meta_parts) + "</div>" if meta_parts else ""

    if final_price is not None:
        trust_text = f"Prezzo verificato {price_label} · può cambiare su Amazon." if price_label else "Prezzo rilevato da Amazon · può cambiare."
    else:
        trust_text = f"Dati prodotto recuperati {fetched_label} · verifica su Amazon." if fetched_label else "Controlla prezzo e disponibilità su Amazon."

    card = (
        "<article class='product-card'>"
        "<div class='product-grid'><div>" + image_html + "</div><div>"
        + f"<a class='product-title-link' href='{html.escape(link, quote=True)}' target='_blank' rel='noopener noreferrer sponsored' title='{html.escape(title, quote=True)}'><h3 class='product-title'>{html.escape(title)}</h3></a>"
        + price_html + meta_html
        + f"<div class='trust'>{html.escape(trust_text)}</div>"
        + f"<a class='buy' href='{html.escape(link, quote=True)}' target='_blank' rel='noopener noreferrer sponsored'><span class='amazon-label'>Vedi su <strong>Amazon.it</strong></span></a>"
        + "<details class='share-details'><summary>Condividi</summary><div class='share-row'>"
        + f"<a class='share' href='{html.escape(share['wa'], quote=True)}' target='_blank' rel='noopener noreferrer'>WhatsApp</a>"
        + f"<a class='share' href='{html.escape(share['tg'], quote=True)}' target='_blank' rel='noopener noreferrer'>Telegram</a>"
        + f"<a class='share' href='{html.escape(share['mail'], quote=True)}'>Email</a>"
        + "</div></details></div></div></article>"
    )
    st.markdown(card, unsafe_allow_html=True)


def render_back_to_top() -> None:
    st.markdown("<a class='back-top' href='#top-anchor'>Torna su</a>", unsafe_allow_html=True)


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
