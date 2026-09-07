from __future__ import annotations

import html
import logging
import re
import math
import time
import urllib.parse

import streamlit as st
import streamlit.components.v1 as components

import amazon_api
import visitor_limit
import product_dedup
from pathlib import Path


st.set_page_config(
    page_title="Scaladeiturchi | Offerte Amazon AI",
    page_icon="🛍️",
    layout="wide",
    initial_sidebar_state="collapsed",
)

LOGGER = logging.getLogger("amazon_affiliate_app")
MAX_RESULTS = amazon_api.MAX_RESULTS
SORT_MAPPINGS = amazon_api.SORT_MAPPINGS

st.session_state.setdefault("current_tab", "haul")
st.session_state.setdefault("has_searched", False)
st.session_state.setdefault("item_count", 10)
st.session_state.setdefault("current_page", 1)
st.session_state.setdefault("offerte", [])
st.session_state.setdefault("search_notice", "")
st.session_state.setdefault(
    "last_search",
    {"keyword": "", "sort": "Prezzo minimo", "prime_only": False},
)
st.session_state.setdefault("offerte_vetrina", [])
st.session_state.setdefault("vetrina_refresh_token", str(time.time_ns()))
st.session_state.setdefault("vetrina_loaded_token", None)
st.session_state.setdefault("search_sort", "Prezzo minimo")
st.session_state.setdefault("search_keyword_input", "")
st.session_state.setdefault("search_prime_only", False)
st.session_state.setdefault("scroll_to_current_results_page", False)
st.session_state.setdefault("offerte_haul", [])
st.session_state.setdefault("haul_refresh_token", str(time.time_ns()))
st.session_state.setdefault("haul_loaded_token", None)
st.session_state.setdefault("haul_previous_asins", [])
st.session_state.setdefault("no_more_results", False)

if st.session_state.get("current_tab") not in {"haul", "vetrina", "cerca", "privacy"}:
    st.session_state["current_tab"] = "haul"

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
    margin: 0;
    padding: 0;
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

/* NAV HAUL / VETRINA / CERCA */
div[data-testid="stHorizontalBlock"]:has(.st-key-nav_btn_haul) {
    display: flex !important;
    flex-direction: row !important;
    flex-wrap: nowrap !important;
    align-items: stretch !important;
    gap: 5px !important;
    width: 100% !important;
}

div[data-testid="stHorizontalBlock"]:has(.st-key-nav_btn_haul) > div,
div[data-testid="stHorizontalBlock"]:has(.st-key-nav_btn_haul) div[data-testid="column"],
div[data-testid="stHorizontalBlock"]:has(.st-key-nav_btn_haul) div[data-testid="stColumn"] {
    flex: 1 1 0 !important;
    width: 33.333% !important;
    min-width: 0 !important;
    max-width: 33.333% !important;
    padding: 0 !important;
}

div[data-testid="stHorizontalBlock"]:has(.st-key-nav_btn_haul) button {
    width: 100% !important;
    min-width: 0 !important;
    white-space: nowrap !important;
    padding-left: 4px !important;
    padding-right: 4px !important;
    font-size: .76rem !important;
}

@media (max-width: 580px) {
    div[data-testid="stHorizontalBlock"]:has(.st-key-nav_btn_haul) {
        gap: 3px !important;
        flex-wrap: nowrap !important;
    }

    div[data-testid="stHorizontalBlock"]:has(.st-key-nav_btn_haul) > div,
    div[data-testid="stHorizontalBlock"]:has(.st-key-nav_btn_haul) div[data-testid="column"],
    div[data-testid="stHorizontalBlock"]:has(.st-key-nav_btn_haul) div[data-testid="stColumn"] {
        flex: 1 1 0 !important;
        width: 33.333% !important;
        min-width: 0 !important;
        max-width: 33.333% !important;
    }

    div[data-testid="stHorizontalBlock"]:has(.st-key-nav_btn_haul) button {
        font-size: .66rem !important;
        padding: 3px 2px !important;
        min-height: 34px !important;
    }
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
#search-current-page-top {
    scroll-margin-top: 12px;
}

/* PAGINAZIONE: tutti i pulsanti sempre sulla stessa riga */
div[data-testid="stHorizontalBlock"]:has(.st-key-page_1) {
    display: flex !important;
    flex-direction: row !important;
    flex-wrap: nowrap !important;
    align-items: stretch !important;
    gap: 5px !important;
    width: 100% !important;
    overflow-x: auto !important;
    overflow-y: hidden !important;
    padding: 2px 0 5px 0 !important;
    scrollbar-width: thin;
}

div[data-testid="stHorizontalBlock"]:has(.st-key-page_1) > div,
div[data-testid="stHorizontalBlock"]:has(.st-key-page_1) div[data-testid="column"],
div[data-testid="stHorizontalBlock"]:has(.st-key-page_1) div[data-testid="stColumn"] {
    flex: 1 1 0 !important;
    width: auto !important;
    min-width: 82px !important;
    max-width: none !important;
    padding: 0 !important;
    margin: 0 !important;
}

div[data-testid="stHorizontalBlock"]:has(.st-key-page_1) button {
    width: 100% !important;
    min-width: 82px !important;
    height: 34px !important;
    min-height: 34px !important;
    padding: 4px 7px !important;
    border-radius: 8px !important;
    white-space: nowrap !important;
    font-size: .74rem !important;
    font-weight: 900 !important;
}

@media (max-width: 580px) {
    div[data-testid="stHorizontalBlock"]:has(.st-key-page_1) {
        gap: 4px !important;
        flex-wrap: nowrap !important;
    }

    div[data-testid="stHorizontalBlock"]:has(.st-key-page_1) > div,
    div[data-testid="stHorizontalBlock"]:has(.st-key-page_1) div[data-testid="column"],
    div[data-testid="stHorizontalBlock"]:has(.st-key-page_1) div[data-testid="stColumn"] {
        min-width: 76px !important;
        flex: 1 1 0 !important;
    }

    div[data-testid="stHorizontalBlock"]:has(.st-key-page_1) button {
        min-width: 76px !important;
        font-size: .70rem !important;
        padding: 3px 5px !important;
    }
}

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
    display: grid;
    grid-template-columns: minmax(0, 254px) minmax(0, 1fr);
    align-items: stretch;
    gap: 11px;
}

.pcm-img-box {
    width: 100%;
    height: 254px;
    min-width: 0;
    background: #ffffff;
    border: 1px solid #bfdbfe;
    border-radius: 9px;
    padding: 2px;
    display: flex;
    align-items: center;
    justify-content: center;
    overflow: hidden;
}

.pcm-img-box img {
    width: 100%;
    height: 100%;
    max-width: 100%;
    max-height: 100%;
    object-fit: contain;
}

.pcm-details {
    min-width: 0;
    display: flex;
    flex-direction: column;
    justify-content: center;
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

.sold-qty-pill {
    background: linear-gradient(135deg, #fff7ed 0%, #ffedd5 100%);
    border: 1px solid #fb923c;
    color: #c2410c;
    padding: 3px 7px;
    border-radius: 6px;
    font-size: 0.67rem;
    font-weight: 900;
    box-shadow: 0 1px 3px rgba(234, 88, 12, 0.10);
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
    min-height: 48px;
    padding: 10px 18px;
    border-radius: 7px;
    background: linear-gradient(135deg, #fbbf24 0%, #f59e0b 100%);
    color: #0f172a !important;
    border: 2px solid #92400e;
    font-size: 0.80rem;
    font-weight: 900;
    text-decoration: none !important;
    box-shadow: 0 2px 5px rgba(245, 158, 11, 0.24);
}

.pcm-buy-btn-compact:hover {
    transform: translateY(-1px);
    background: linear-gradient(135deg, #f59e0b 0%, #d97706 100%);
}

.pcm-share summary { cursor: pointer; padding: 12px 6px; color: #075985; }
.pcm-share[open] summary { margin-bottom: 4px; }
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
        width: 100%;
        height: 100%;
        min-height: 254px;
        min-width: 0;
        max-width: 100%;
        padding: 2px;
        position: relative;
    }

    .pcm-img-box img {
        position: absolute;
        inset: 2px;
        width: calc(100% - 4px);
        height: calc(100% - 4px);
        max-width: 100%;
        max-height: 100%;
        object-fit: contain;
    }

    .pcm-top {
        grid-template-columns: minmax(0, 42fr) minmax(0, 58fr);
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
        padding: 8px 5px;
        text-align: center;
    }
}

/* Mobile hierarchy: product, price, action, supporting information. */
.pcm-savings {flex-basis:100%; color:#047857; font-size:14px; font-weight:700;}
@media (max-width: 700px) {
    .brand-header-box {padding:10px 8px !important;}
    .brand-title-single {font-size:26px !important; line-height:1.15 !important;}
    .brand-subtitle-single, .brand-author, .badge-ai-pill {font-size:12px !important;}
    div[data-testid="stHorizontalBlock"]:has(.st-key-nav_btn_haul) button {
        min-height:46px !important; font-size:15px !important; padding:7px 3px !important;
    }
    div[data-testid="stHorizontalBlock"]:has(.st-key-nav_btn_haul) button p {font-size:15px !important;}
    .product-card-modern {padding:8px;}
    .pcm-top {grid-template-columns:minmax(0,38fr) minmax(0,62fr); gap:10px;}
    .pcm-details {justify-content:flex-start;}
    .pcm-title {font-size:16px; line-height:1.35; margin-bottom:6px;}
    .pcm-prices {gap:6px; margin-top:8px;}
    .pcm-price-final {font-size:26px; line-height:1.15; flex-basis:100%;}
    .pcm-price-old {font-size:14px;}
    .pcm-discount-badge {font-size:14px; padding:3px 6px;}
    .pcm-note {font-size:13px; line-height:1.4; color:#475569;}
    .sold-qty-pill, .sales-rank-pill, .prime-pill {font-size:13px; font-weight:600;}
    .pcm-bottom-bar {gap:4px; margin-top:6px; padding-top:6px;}
    .pcm-buy-btn-compact {font-size:15px; min-height:48px; width:100%; padding:8px 4px; line-height:1.25;}
    .pcm-share {width:100%;}
    .pcm-share summary {font-size:14px; padding:10px 0;}
    .soc-chip {font-size:13px; min-height:44px; padding:0 10px;}
    .tab-content-panel h2, .vetrina-promo h2 {font-size:21px !important; line-height:1.3 !important;}
    .haul-promo {padding:10px !important;}
    .haul-promo > div:first-child {font-size:16px !important;}
    .haul-promo > div:nth-child(2) {display:grid !important; grid-template-columns:repeat(2,minmax(0,1fr)); gap:6px !important;}
    .haul-promo > div:nth-child(2) > div {min-width:0 !important; padding:8px !important;}
    .haul-promo > div:nth-child(2) > div:first-child {grid-column:1 / -1; display:flex; justify-content:space-between; align-items:center; gap:6px;}
    .haul-promo > div:nth-child(2) > div > div:first-child {font-size:20px !important;}
    .haul-promo > div:nth-child(2) > div > div:last-child {font-size:14px !important;}
    .haul-promo > div:last-child {font-size:13px !important; line-height:1.4;}
    .vetrina-promo {padding:10px !important; margin-bottom:8px !important;}
    .vetrina-promo > div {padding:8px !important; font-size:14px !important; line-height:1.4 !important;}
    .vetrina-promo > div > div {font-size:16px !important; line-height:1.35 !important;}
    .st-key-search_keyword_input input {font-size:16px !important; min-height:48px;}
    .st-key-search_submit_button button {min-height:48px !important; font-size:16px !important;}
    .st-key-search_sort label p, .st-key-search_prime_only label p {font-size:14px !important;}
    div[data-testid="stAlert"] p {font-size:14px !important; line-height:1.45;}
    div[data-testid="stCaptionContainer"] p {font-size:13px !important; line-height:1.4;}
    .site-footer-box {font-size:13px; line-height:1.5; padding:10px;}
    div[data-testid="stHorizontalBlock"]:has(.st-key-page_1) button {font-size:13px !important; min-height:44px !important;}
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



def open_haul() -> None:
    """Apre HAUL e genera un nuovo campionamento casuale."""
    st.session_state["current_tab"] = "haul"
    st.session_state["haul_refresh_token"] = str(time.time_ns())
    st.session_state["haul_loaded_token"] = None
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
    ordered = product_dedup.unique(products or [])

    # Ordine di sicurezza per elementi che non hanno metadati di ranking.
    for index, product in enumerate(ordered):
        product.setdefault("_loaded_position", index)

    if sort_type == "Prezzo minimo":
        ordered.sort(
            key=lambda product: (
                product.get("prezzo_verificato") is not True or not product.get("prezzo_finale"),
                float(product.get("prezzo_finale") or float("inf")) if product.get("prezzo_verificato") is True else float("inf"),
                int(product.get("_loaded_position") or 0),
            )
        )
        return ordered

    if sort_type == "Quantità vendite":
        def sales_key(product: dict) -> tuple:
            sold_qty = product.get("sold_qty_month")
            sales_rank = product.get("sales_rank")
            amazon_position = product.get("_amazon_position")
            loaded_position = int(product.get("_loaded_position") or 0)

            try:
                if sold_qty is not None:
                    return (0, -int(sold_qty), loaded_position)
            except (TypeError, ValueError):
                pass

            try:
                if sales_rank is not None:
                    return (1, int(sales_rank), loaded_position)
            except (TypeError, ValueError):
                pass

            try:
                if amazon_position is not None:
                    return (2, int(amazon_position), loaded_position)
            except (TypeError, ValueError):
                pass

            return (3, loaded_position, loaded_position)

        ordered.sort(key=sales_key)
        return ordered

    return ordered


def _prepare_new_search() -> None:
    # Il callback precede la creazione dei widget nel rerun.
    st.session_state["search_sort"] = "Prezzo minimo"


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


SEARCH_LIMIT_NOTICE = (
    "Hai raggiunto il limite di ricerche nell’ultima ora. "
    "Puoi continuare direttamente su Amazon."
)


def _session_search_limit() -> int:
    try:
        return max(1, int(st.secrets.get("amazon_api", {}).get("searches_per_hour", 10)))
    except Exception:
        return 10


def _quota_status(consume=False):
    visitor = st.session_state.get("visitor_id")
    if not visitor:
        return {"allowed": False, "remaining": None, "retry_at": 0}
    try:
        return visitor_limit.check(visitor, _session_search_limit(), consume)
    except Exception as exc:
        LOGGER.error("Limite visitatore non disponibile: %s", type(exc).__name__)
        return {"allowed": False, "remaining": None, "retry_at": 0}


def _session_limit_reached() -> bool:
    return _quota_status()["remaining"] == 0


@st.fragment(run_every="15s")
def _watch_quota_expiry():
    blocked = _session_limit_reached()
    previous = st.session_state.get("quota_was_blocked", blocked)
    st.session_state["quota_was_blocked"] = blocked
    if previous != blocked:
        st.rerun()


def _retry_remaining() -> int:
    return max(0, math.ceil(st.session_state.get("search_retry_at", 0) - time.time()))


@st.fragment(run_every="1s")
def _watch_search_retry():
    remaining = _retry_remaining()
    if remaining:
        st.info(f"Non riusciamo a mostrare i risultati in questo momento. Attendi {remaining} secondi e riprova.")
    elif st.session_state.pop("search_retry_at", 0):
        st.session_state["search_notice"] = "Puoi riprovare: premi Cerca. Oppure scopri le proposte in Vetrina."
        st.rerun()


def _search_allowed() -> bool:
    if _retry_remaining():
        return False
    now = time.monotonic()
    if now < st.session_state.get("next_search_at", 0):
        st.session_state["search_notice"] = "Attendi un momento prima della prossima ricerca."
        return False
    status = _quota_status(consume=True)
    if not status["allowed"]:
        st.session_state["search_notice"] = (
            SEARCH_LIMIT_NOTICE if status["remaining"] == 0
            else "La ricerca non è disponibile in questo momento. Riprova tra poco."
        )
        return False
    st.session_state["next_search_at"] = now + 5
    return True


def _amazon_request(function, **kwargs):
    st.session_state["amazon_unavailable"] = False
    try:
        return function(**kwargs)
    except amazon_api.shared_results.RetryPending as exc:
        st.session_state["search_retry_at"] = exc.retry_at
        st.session_state["search_notice"] = ""
        st.session_state["amazon_unavailable"] = True
        return None
    except amazon_api.api_budget.BudgetUnavailable as exc:
        LOGGER.info("Ricerca sospesa: %s", exc)
        st.session_state["amazon_unavailable"] = True
        st.session_state["search_notice"] = (
            "La ricerca interna è temporaneamente non disponibile. "
            "Riprova tra poco."
        )
        return None


def _perform_search(target_count: int) -> None:
    cfg = st.session_state["last_search"]
    target_count = max(10, min(int(target_count), MAX_RESULTS))

    with st.spinner(f"Ricerca di {target_count} prodotti..."):
        results = _amazon_request(amazon_api.ottieni_offerte_avanzate,
            keyword=cfg["keyword"],
            sort_type=cfg["sort"],
            solo_spedizione_gratuita=cfg["prime_only"],
            item_count=target_count,
        )

    if results is None:
        st.session_state["has_searched"] = True
        return
    normalized_results = product_dedup.unique(results or [])

    for index, product in enumerate(normalized_results):
        product.setdefault("_loaded_position", index)

    st.session_state["offerte"] = _sort_loaded_products(
        normalized_results,
        str(cfg.get("sort") or "Prezzo minimo"),
    )
    st.session_state["item_count"] = len(normalized_results)
    st.session_state["has_searched"] = True
    st.session_state["no_more_results"] = False

    if not results:
        LOGGER.info("Ricerca senza risultati: %s", amazon_api.get_search_diagnostics())
        st.session_state["search_notice"] = (
            "Non abbiamo trovato prodotti per questa ricerca. "
            "Prova un altro termine di ricerca."
        )
    elif len(results) < target_count:
        st.session_state["search_notice"] = (
            f"Recuperati {len(results)} prodotti per questa ricerca. "
            "Puoi caricarne altri con il pulsante qui sotto."
        )
    else:
        st.session_state["search_notice"] = ""

def _load_more() -> None:
    existing = list(st.session_state.get("offerte", []))
    previous_count = len(existing)

    if previous_count >= MAX_RESULTS:
        st.session_state["search_notice"] = (
            f"Limite di {MAX_RESULTS} prodotti raggiunto."
        )
        return

    if not _search_allowed():
        return
    add_count = min(10, MAX_RESULTS - previous_count)
    cfg = st.session_state["last_search"]
    excluded_asins = tuple(
        sorted(
            {
                str(product.get("asin") or "").strip().upper()
                for product in product_dedup.flatten(existing)
                if str(product.get("asin") or "").strip()
            }
        )
    )

    with st.spinner("Caricamento di altri prodotti..."):
        new_results = _amazon_request(amazon_api.ottieni_offerte_avanzate,
            keyword=cfg["keyword"],
            sort_type=cfg["sort"],
            solo_spedizione_gratuita=cfg["prime_only"],
            item_count=add_count,
            exclude_asins=excluded_asins,
        )

    if new_results is None:
        if _retry_remaining():
            st.rerun()
        return
    merged = product_dedup.unique(existing + list(new_results or []))[:MAX_RESULTS]
    for index, product in enumerate(merged):
        product.setdefault("_loaded_position", index)

    st.session_state["offerte"] = _sort_loaded_products(
        merged, str(cfg.get("sort") or "Prezzo minimo")
    )
    st.session_state["item_count"] = len(merged)
    st.session_state["has_searched"] = True

    new_count = len(merged)
    if new_count > previous_count:
        st.session_state["current_page"] = max(1, (new_count + 9) // 10)
        st.session_state["scroll_to_current_results_page"] = True
        st.session_state["no_more_results"] = False
        added = new_count - previous_count
        st.session_state["search_notice"] = (
            "" if added == add_count
            else f"Aggiunti {added} nuovi prodotti."
        )
    else:
        st.session_state["scroll_to_current_results_page"] = False
        st.session_state["no_more_results"] = False
        st.session_state["search_notice"] = (
            "Non è stato possibile recuperare altri prodotti in questo momento."
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



def _card_image_candidates(product: dict) -> list[str]:
    candidates: list[str] = []

    primary = str(product.get("immagine_url") or "").strip()
    if primary:
        candidates.append(primary)

    extra = product.get("immagine_fallback_urls") or []
    if isinstance(extra, str):
        extra = [extra]

    for url in extra:
        clean = str(url or "").strip()
        if clean and clean not in candidates:
            candidates.append(clean)

    asin = str(product.get("asin") or "").strip().upper()
    if len(asin) == 10:
        legacy = (
            f"https://images-na.ssl-images-amazon.com/images/P/{asin}.01.LZZZZZZZ.jpg",
            f"https://images-na.ssl-images-amazon.com/images/P/{asin}.09.LZZZZZZZ.jpg",
            f"https://images-na.ssl-images-amazon.com/images/P/{asin}.jpg",
        )
        for url in legacy:
            if url not in candidates:
                candidates.append(url)

    return candidates

def render_product_card(product: dict, eager_image: bool = False) -> None:
    title = str(product.get("titolo") or "Prodotto Amazon")
    link = str(product.get("link_affiliato") or "")
    image_candidates = _card_image_candidates(product)
    image_url = image_candidates[0] if image_candidates else IMG_FALLBACK_SVG
    image_fallback_candidates = image_candidates[1:]

    safe_title = html.escape(title)
    variant_label = html.escape(
        "Taglia: " + str(product.get("size") or "da verificare")
        + " · Colore: " + str(product.get("color") or "da verificare")
    )
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

    if verified and final_price is not None and math.isfinite(final_price) and final_price > 0:
        discount = html.escape(str(product.get("sconto") or ""))

        discount_html = (
            f"<span class='pcm-discount-badge'>{discount}</span>"
            if discount
            else ""
        )

        old_html = ""
        if old_price is not None and math.isfinite(old_price) and old_price > final_price:
            old_html = (
                f"<span class='pcm-price-old'>€{_format_eur(old_price)}</span>"
                f"<span class='pcm-savings'>Risparmi €{_format_eur(old_price - final_price)}</span>"
            )

        price_html = (
            f"<span class='pcm-price-final'>€{_format_eur(final_price)}</span>"
            f"{discount_html}"
            f"{old_html}"
        )
    else:
        price_html = (
            "<span class='pcm-price-final' style='font-size:1.05rem;'>"
            "Prezzo da verificare"
            "</span>"
        )

    badge_parts = []

    sold_qty_month = product.get("sold_qty_month")
    sold_qty_label = str(product.get("sold_qty_label") or "").strip()

    if sold_qty_month:
        try:
            sold_qty_int = int(sold_qty_month)
            if not sold_qty_label:
                shown = f"{sold_qty_int:,}".replace(",", ".")
                sold_qty_label = f"{shown}+ acquistati nel mese scorso"

            badge_parts.append(
                f"<span class='sold-qty-pill'>"
                f"🔥 {html.escape(sold_qty_label)}"
                f"</span>"
            )
        except (TypeError, ValueError):
            pass

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

    note = ""

    saving_basis_label = str(product.get("saving_basis_label") or "").strip()

    if (
        verified
        and saving_basis_label
        and old_price is not None
        and final_price is not None
        and old_price > final_price
    ):
        note += f"Prezzo di riferimento: {saving_basis_label}."

    if old_price and final_price and verified and old_price > final_price and not saving_basis_label:
        note += " Confronto con il prezzo di riferimento mostrato da Amazon."
    if sold_qty_month:
        note += " Acquisti mensili: soglia indicata da Amazon."
    elif sales_rank:
        note += " Posizione in classifica, non quantità venduta."

    share = _share_urls(
        title,
        link,
        final_price if verified else None,
    )

    image_loading = "eager" if eager_image else "lazy"
    image_priority = "high" if eager_image else "auto"

    safe_image_fallbacks = [
        html.escape(url, quote=True)
        for url in image_fallback_candidates
    ]

    fallback_js_parts = []
    for index, fallback_url in enumerate(safe_image_fallbacks):
        condition = "if" if index == 0 else "else if"
        fallback_js_parts.append(
            f"{condition}(this.dataset.imgfb!='{index + 1}')"
            "{"
            f"this.dataset.imgfb='{index + 1}';"
            f"this.src='{fallback_url}';"
            "return;"
            "}"
        )

    fallback_js_parts.append(
        "this.onerror=null;"
        f"this.src='{safe_fallback}';"
    )
    image_onerror = "".join(fallback_js_parts)

    image_html = (
        f"<img src='{safe_image}' "
        f"loading='{image_loading}' "
        f"fetchpriority='{image_priority}' "
        f"decoding='async' "
        f"alt='{safe_title_attr}' "
        f"onerror=\"{image_onerror}\">"
    )

    card_html = (
        "<div class='product-card-modern'>"
        "<div class='pcm-top'>"
        "<div class='pcm-img-box'>"
        + image_html
        + "</div>"
        "<div class='pcm-details'>"
        f"<div class='pcm-title'>{safe_title}</div>"
        f"<div class='pcm-note'><strong>{variant_label}</strong></div>"
        f"<div class='pcm-prices'>{price_html}</div>"
        f"<div class='pcm-badges-row'>{badges_html}</div>"
        f"<div class='pcm-note'>{html.escape(note)}</div>"
        "<div class='pcm-bottom-bar'>"
        f"<a class='pcm-buy-btn-compact' href='{safe_link}' "
        "target='_blank' rel='noopener noreferrer sponsored'>"
        "🛒 Vedi offerta"
        "</a>"
        "<details class='pcm-share'><summary>Condividi</summary><div class='pcm-social-row'>"
        f"<a class='soc-chip soc-wa' href='{html.escape(share['wa'], quote=True)}' "
        "target='_blank' rel='noopener noreferrer'>WA</a>"
        f"<a class='soc-chip soc-fb' href='{html.escape(share['fb'], quote=True)}' "
        "target='_blank' rel='noopener noreferrer'>FB</a>"
        f"<a class='soc-chip soc-tg' href='{html.escape(share['tg'], quote=True)}' "
        "target='_blank' rel='noopener noreferrer'>TG</a>"
        f"<a class='soc-chip soc-mail' href='{html.escape(share['mail'], quote=True)}'>"
        "Mail</a>"
        "</div></details>"
        "</div>"
        "</div>"
        "</div>"
        "</div>"
    )

    st.markdown(card_html, unsafe_allow_html=True)
    variants = product.get("variants", [])
    if len(variants) > 1:
        with st.expander(f"Altre varianti e offerte ({len(variants) - 1})"):
            for variant in variants[1:]:
                label = (
                    f"Taglia: {variant.get('size') or 'da verificare'} · "
                    f"Colore: {variant.get('color') or 'da verificare'}"
                )
                price = variant.get("prezzo_finale")
                if variant.get("prezzo_verificato") is True and price:
                    label += f" · €{_format_eur(float(price))}"
                else:
                    label += " · Prezzo da verificare"
                st.write(label)
                st.link_button("Vedi questa variante su Amazon", variant["link_affiliato"])



def _initialize_browser_identity() -> None:
    """Identity is only needed for searching; a component failure leaves navigation usable."""
    try:
        component = components.declare_component(
            "browser_identity", path=str(Path(__file__).parent / "browser_identity")
        )
        value = component(key="persistent_browser_identity", default=None)
        if isinstance(value, str) and re.fullmatch(r"[a-fA-F0-9-]{36}", value):
            st.session_state["visitor_id"] = value
    except Exception:
        LOGGER.exception("Inizializzazione identificativo visitatore fallita")


# HEADER
st.markdown(
    """
    <div id="top_page"></div>
    <div class="brand-header-box">
        <h1 class="brand-title-single">Scala dei Turchi</h1>
        <div class="brand-subtitle-single">
            <span class="badge-ai-pill">AI DEALS</span>
            <span class="brand-author">by <strong>Davide Marziano</strong></span>
        </div>
    </div>
    """,
    unsafe_allow_html=True,
)

active_tab = st.session_state.get("current_tab", "haul")

# NAV PUBBLICA: HAUL / Vetrina / Cerca.
st.markdown("<div class='nav-wrap'>", unsafe_allow_html=True)
nav1, nav2, nav3 = st.columns([1, 1, 1], gap="small")

with nav1:
    st.button(
        "🛍️ HAUL",
        key="nav_btn_haul",
        type="primary" if active_tab == "haul" else "secondary",
        on_click=open_haul,
        use_container_width=True,
    )

with nav2:
    st.button(
        "🔥 Vetrina",
        key="nav_btn_vetrina",
        type="primary" if active_tab == "vetrina" else "secondary",
        on_click=open_vetrina,
        use_container_width=True,
    )

with nav3:
    st.button(
        "🔍 Cerca",
        key="nav_btn_cerca",
        type="primary" if active_tab == "cerca" else "secondary",
        on_click=set_tab,
        args=("cerca",),
        use_container_width=True,
    )

st.markdown("</div>", unsafe_allow_html=True)

# Optional mobile guidance must not interrupt product browsing.
try:
    home_shortcut = components.declare_component(
        "home_shortcut", path=str(Path(__file__).parent / "home_shortcut")
    )
    home_shortcut(key="home_shortcut_prompt", default=None)
except Exception:
    LOGGER.exception("Avviso schermata Home non disponibile")

partner_tag = amazon_api.get_partner_tag()

if not partner_tag:
    LOGGER.error("Configurazione Amazon incompleta: partner_tag assente")
    st.info("Le offerte sono temporaneamente non disponibili. Riprova tra poco.")

active_tab = st.session_state.get("current_tab", "haul")
st.markdown("<div class='tab-content-panel'>", unsafe_allow_html=True)

if active_tab == "haul":
    haul_url = amazon_api.build_amazon_haul_link()

    st.markdown(
        """
        <h2 style='font-size:1.02rem;font-weight:900;color:#0369a1;
        margin:2px 0 5px 2px;'>🛍️ Amazon HAUL</h2>

        <div class='haul-promo' style='background:linear-gradient(135deg,#fff7ed,#fffbeb);
        border:1px solid #fdba74;border-radius:10px;padding:9px 10px;
        margin:0 0 8px 0;color:#7c2d12;font-size:.72rem;line-height:1.45;'>
        <div style="font-size:.95rem;font-weight:900;color:#7c2d12;margin-bottom:8px;">I vantaggi Amazon Haul</div>
        <div style="display:flex;flex-wrap:wrap;gap:8px;">
          <div style="flex:1;min-width:140px;background:#ecfdf5;border:2px solid #059669;border-radius:10px;padding:10px;color:#065f46;">
            <div style="font-size:1.15rem;font-weight:900;">Spedizione gratis</div>
            <div style="font-size:.85rem;">con <strong>3 articoli</strong></div>
          </div>
          <div style="flex:1;min-width:110px;background:#eff6ff;border:2px solid #2563eb;border-radius:10px;padding:10px;color:#1e40af;">
            <div style="font-size:1.5rem;font-weight:900;">−5%</div>
            <div style="font-size:.85rem;">con <strong>4 articoli</strong></div>
          </div>
          <div style="flex:1;min-width:110px;background:#fff7ed;border:2px solid #ea580c;border-radius:10px;padding:10px;color:#9a3412;">
            <div style="font-size:1.5rem;font-weight:900;">−10%</div>
            <div style="font-size:.85rem;">con <strong>5 o più articoli</strong></div>
          </div>
        </div>
        <div style="margin-top:7px;font-size:.7rem;">Si applicano le condizioni Amazon Haul.</div>
        </div>
        """,
        unsafe_allow_html=True,
    )



    current_token = str(st.session_state["haul_refresh_token"])

    if (
        partner_tag
    ):
        previous_asins = tuple(
            str(asin).strip().upper()
            for asin in st.session_state.get("haul_previous_asins", [])
            if str(asin).strip()
        )

        with st.spinner("Selezione casuale prodotti HAUL..."):
            haul_products = _amazon_request(amazon_api.ottieni_haul_casuale,
                item_count=10,
                refresh_token=current_token,
                exclude_asins=previous_asins,
            )

        new_haul = product_dedup.unique(haul_products or [])
        st.session_state["offerte_haul"] = new_haul
        if new_haul:
            st.session_state["haul_previous_asins"] = [
                str(product.get("asin") or "").strip().upper()
                for product in new_haul
                if str(product.get("asin") or "").strip()
            ]

        # Eventuali schede precedenti vengono gestite dalla cache condivisa,
        # che rimuove i prezzi scaduti e limita il periodo di conservazione.
        st.session_state["haul_loaded_token"] = current_token

    haul_products = product_dedup.unique(st.session_state.get("offerte_haul", []))

    if haul_products:
        st.caption(
            f"{len(haul_products)} prodotti selezionati casualmente dalla pagina HAUL."
        )
        for index, product in enumerate(haul_products):
            render_product_card(product, eager_image=(index == 0))
    else:
        st.info(
            "Non è stato possibile leggere i prodotti HAUL in questo momento. "
            "Premi di nuovo HAUL per riprovare."
        )

elif active_tab == "vetrina":
    st.markdown(
        """
        <section class="vetrina-promo" style="background:linear-gradient(135deg,#fff7ed,#fffbeb);
        border:1px solid #fdba74;border-radius:12px;padding:12px;
        margin:2px 0 12px 0;">
          <h2 style="font-size:1.08rem;font-weight:900;color:#9a3412;
          margin:0 0 10px 0;line-height:1.4;">🔥 Offerte in Vetrina</h2>
          <div style="background:#eff6ff;border:2px solid #2563eb;
          border-radius:10px;padding:12px;margin-bottom:8px;">
            <div style="font-size:1.15rem;font-weight:900;color:#1e40af;
            line-height:1.4;">🔎 Meno ricerche, più scoperte</div>
          </div>
          <div style="background:#ecfdf5;border:2px solid #059669;
          border-radius:10px;padding:11px 12px;color:#065f46;
          font-size:.9rem;line-height:1.6;">
            Parti dalla nostra Vetrina per trovare nuove idee per i tuoi acquisti.
          </div>
        </section>
        """,
        unsafe_allow_html=True,
    )

    current_token = "shared"

    if (
        partner_tag
    ):
        with st.spinner("Aggiornamento offerte Amazon..."):
            showcase = _amazon_request(amazon_api.ottieni_vetrina_casuale,
                item_count=3,
                refresh_token=current_token,
            )

        new_showcase = product_dedup.unique(showcase or [])
        st.session_state["offerte_vetrina"] = new_showcase
        # Nessun prezzo di una vecchia selezione dopo un refresh fallito.
        st.session_state["vetrina_loaded_token"] = current_token

    showcase = product_dedup.unique(st.session_state.get("offerte_vetrina", []))

    if showcase:
        for index, product in enumerate(showcase):
            render_product_card(product, eager_image=(index == 0))
    else:
        st.info("La vetrina è temporaneamente non disponibile.")
        st.link_button("Scopri le offerte su Amazon",
                       amazon_api.build_amazon_search_link("offerte del giorno"),
                       use_container_width=True)

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

    _initialize_browser_identity()

    if not st.session_state.get("visitor_id"):
        st.info("La ricerca non è ancora pronta. Puoi intanto consultare HAUL e Vetrina.")
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
            on_click=_prepare_new_search,
            disabled=_session_limit_reached() or bool(_retry_remaining()) or not st.session_state.get("visitor_id"),
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

    st.checkbox(
        "🚚 Solo prodotti Prime",
        key="search_prime_only",
    )

    if submitted:
        deadline = amazon_api.search_retry_at(
            keyword=str(st.session_state.get("search_keyword_input") or "").strip(),
            sort_type=str(st.session_state.get("search_sort") or "Prezzo minimo"),
            solo_spedizione_gratuita=bool(st.session_state.get("search_prime_only", False)),
            item_count=10,
        )
        if deadline > time.time():
            st.session_state["search_retry_at"] = deadline
    previous_search = dict(st.session_state["last_search"])
    if submitted and _search_allowed():
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
        st.session_state["no_more_results"] = False
        _perform_search(10)
        if st.session_state.get("amazon_unavailable"):
            st.session_state["last_search"] = previous_search
            if _retry_remaining():
                st.rerun()

    if _session_limit_reached():
        st.info(SEARCH_LIMIT_NOTICE)
    elif st.session_state.get("search_notice") and st.session_state["search_notice"] != SEARCH_LIMIT_NOTICE:
        st.info(st.session_state["search_notice"])

    if _session_limit_reached():
        st.link_button(
            "Continua su AMAZON",
            amazon_api.build_amazon_search_link(
                str(st.session_state.get("search_keyword_input") or "offerte")
            ),
            use_container_width=True,
        )
        st.caption("Puoi continuare a consultare i risultati e scoprire altre idee in Vetrina.")
        st.button("Scopri la Vetrina", key="quota_vetrina", on_click=open_vetrina)
    _watch_quota_expiry()
    if st.session_state.get("search_retry_at"):
        _watch_search_retry()


    if st.session_state.get("amazon_unavailable") and not _session_limit_reached():
        st.button("Scopri la Vetrina", key="unavailable_vetrina", on_click=open_vetrina)

    results = product_dedup.unique(st.session_state.get("offerte", []))

    if results:
        total = len(results)
        pages = max(1, (total + 9) // 10)
        current_page = min(
            max(1, int(st.session_state.get("current_page", 1))),
            pages,
        )
        st.session_state["current_page"] = current_page

        if pages > 1:
            # Una sola riga orizzontale: P.1 P.2 P.3 ...
            # Il CSS impedisce a Streamlit di impilare le colonne su mobile.
            page_cols = st.columns([1] * pages, gap="small")

            for page_number, col in enumerate(page_cols, start=1):
                with col:
                    if st.button(
                        f"Pagina {page_number}",
                        type=(
                            "primary"
                            if page_number == current_page
                            else "secondary"
                        ),
                        key=f"page_{page_number}",
                        use_container_width=True,
                    ):
                        st.session_state["current_page"] = page_number
                        st.session_state["scroll_to_current_results_page"] = True
                        st.rerun()

        start = (current_page - 1) * 10
        end = min(start + 10, total)

        st.markdown(
            f"<p style='font-size:.74rem;font-weight:800;color:#0284c7;"
            f"margin:5px 0;'>Prodotti {start + 1}-{end} di {total}</p>",
            unsafe_allow_html=True,
        )

        # Punto esatto verso cui scorrere dopo "Carica altri 10".
        # È collocato subito prima della prima scheda della pagina corrente.
        st.markdown(
            "<div id='search-current-page-top'></div>",
            unsafe_allow_html=True,
        )

        for index, product in enumerate(results[start:end]):
            render_product_card(product, eager_image=(index == 0))

        st.button(
            "➕ Carica altri 10 prodotti ⬇️",
            on_click=_load_more,
            use_container_width=True,
            disabled=(
                len(results) >= MAX_RESULTS
                or bool(_retry_remaining())
                or _session_limit_reached()
                or bool(st.session_state.get("no_more_results", False))
            ),
        )

        if st.session_state.get("scroll_to_current_results_page", False):
            # Flag one-shot: evita che ogni rerun successivo faccia di nuovo scroll.
            st.session_state["scroll_to_current_results_page"] = False

            components.html(
                """
                <script>
                (function () {
                    let attempts = 0;
                    const maxAttempts = 30;

                    const timer = setInterval(function () {
                        attempts += 1;

                        try {
                            const doc = window.parent.document;
                            const target = doc.getElementById(
                                "search-current-page-top"
                            );

                            if (target) {
                                target.scrollIntoView({
                                    behavior: "smooth",
                                    block: "start"
                                });
                                clearInterval(timer);
                                return;
                            }
                        } catch (error) {
                            // Nessun errore viene mostrato all'utente.
                        }

                        if (attempts >= maxAttempts) {
                            clearInterval(timer);
                        }
                    }, 100);
                })();
                </script>
                """,
                height=0,
            )

    elif (
        st.session_state.get("has_searched")
        and not _retry_remaining()
        and not st.session_state.get("search_notice")
    ):
        st.info("Premi Cerca per riprovare, oppure scopri le proposte in Vetrina.")

elif active_tab == "privacy":
    st.markdown(
        "<h2 style='font-size:.94rem;color:#0369a1;'>Informativa privacy</h2>",
        unsafe_allow_html=True,
    )

    st.markdown(
        """
        Il sito contiene collegamenti affiliati ad Amazon.it.
        Gli acquisti idonei possono generare una commissione per il titolare del sito.

        Per applicare il limite orario delle ricerche, il browser conserva
        un identificatore casuale. Il server lo associa agli orari delle
        ricerche recenti; questo identificatore non richiede nome o email.

        Il browser memorizza anche la chiusura dell’invito ad aggiungere il sito
        alla schermata Home, per non riproporlo prima di tre giorni.

        """
    )

    st.button(
        "← Torna alla vetrina",
        on_click=open_vetrina,
    )

st.markdown("</div>", unsafe_allow_html=True)

st.markdown(
    """
    <div class="site-footer-box">
        In qualità di Affiliato Amazon io ricevo un guadagno dagli acquisti idonei.<br>
        <a href="?privacy=1" target="_self">Informativa privacy</a>
    </div>
    """,
    unsafe_allow_html=True,
)



with st.expander("📲 Aggiungi alla schermata Home"):
    st.markdown("**iPhone · Safari:** Condividi → Aggiungi alla schermata Home → Aggiungi.")
    st.markdown("**Android · Chrome:** menu ⋮ → Aggiungi a schermata Home → conferma il collegamento.")
    st.caption("Se navighi dentro un’altra app, apri prima il sito in Safari o Chrome. Il collegamento richiede Internet.")
