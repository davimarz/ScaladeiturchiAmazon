from __future__ import annotations

import logging
import math
import time
import uuid
from pathlib import Path

import streamlit as st
import streamlit.components.v1 as components

import amazon_api
import amazon_gateway
import app_constants
import catalog_service
import product_dedup
import telemetry
import ui_components
import visitor_limit

st.set_page_config(
    page_title="Scala dei Turchi | Offerte Amazon",
    page_icon="🛍️",
    layout="wide",
    initial_sidebar_state="collapsed",
)

LOGGER = logging.getLogger("amazon_affiliate_app")
amazon_api.LOGGER.setLevel(logging.WARNING)
MAX_RESULTS = amazon_gateway.MAX_RESULTS

DEFAULTS = {
    "current_tab": "haul",
    "offerte_haul": [],
    "haul_refresh_token": str(time.time_ns()),
    "haul_loaded_token": None,
    "haul_seen_asins": [],
    "offerte_vetrina": [],
    "vetrina_refresh_token": str(time.time_ns()),
    "vetrina_loaded_token": None,
    "vetrina_seen_asins": [],
    "offerte": [],
    "has_searched": False,
    "current_page": 1,
    "search_keyword_input": "",
    "search_sort": app_constants.SORT_PRICE,
    "search_prime_only": False,
    "last_search": {"keyword": "", "sort": app_constants.SORT_PRICE, "prime_only": False},
    "search_notice": "",
    "next_search_at": 0.0,
}
for key, value in DEFAULTS.items():
    st.session_state.setdefault(key, value)

if st.session_state.get("current_tab") not in {"haul", "vetrina", "cerca", "privacy"}:
    st.session_state["current_tab"] = "haul"
try:
    if str(st.query_params.get("privacy", "")) == "1":
        st.session_state["current_tab"] = "privacy"
except Exception:
    pass

ui_components.inject_css()


def _clear_query_params() -> None:
    try:
        st.query_params.clear()
    except Exception:
        pass


def _set_tab(name: str) -> None:
    st.session_state["current_tab"] = name
    _clear_query_params()


def _open_haul() -> None:
    st.session_state["current_tab"] = "haul"
    st.session_state["haul_refresh_token"] = str(time.time_ns())
    st.session_state["haul_loaded_token"] = None
    _clear_query_params()


def _open_vetrina() -> None:
    st.session_state["current_tab"] = "vetrina"
    st.session_state["vetrina_refresh_token"] = str(time.time_ns())
    st.session_state["vetrina_loaded_token"] = None
    _clear_query_params()


def _clear_search() -> None:
    """Clear search-related state safely from a widget callback."""
    st.session_state["search_keyword_input"] = ""
    st.session_state["offerte"] = []
    st.session_state["has_searched"] = False
    st.session_state["search_notice"] = ""
    st.session_state["current_page"] = 1


def _valid_uuid(value: object) -> str | None:
    try:
        parsed = uuid.UUID(str(value))
    except (ValueError, TypeError, AttributeError):
        return None
    return str(parsed)


def _initialize_browser_identity() -> None:
    try:
        component = components.declare_component("browser_identity", path=str(Path(__file__).parent / "browser_identity"))
        value = component(key="persistent_browser_identity", default=None)
        valid = _valid_uuid(value)
        if valid:
            st.session_state["visitor_id"] = valid
        elif value:
            LOGGER.warning("invalid visitor id rejected")
            telemetry.increment("invalid_visitor_id")
    except Exception:
        LOGGER.exception("Browser identity unavailable")


def _search_limit() -> int:
    try:
        return max(1, int(st.secrets.get("amazon_api", {}).get("searches_per_hour", 10)))
    except Exception:
        return 10


def _quota(consume: bool = False) -> dict:
    visitor = st.session_state.get("visitor_id")
    if not visitor:
        return {"allowed": False, "remaining": None, "retry_at": 0}
    try:
        return visitor_limit.check(visitor, _search_limit(), consume)
    except Exception as exc:
        LOGGER.warning("Quota unavailable: %s", type(exc).__name__)
        telemetry.increment("quota_backend_error")
        return {"allowed": False, "remaining": None, "retry_at": 0}


def _retry_label(retry_at: float) -> str:
    remaining = max(0, int(float(retry_at or 0) - time.time()))
    if remaining <= 0:
        return "tra poco"
    minutes, seconds = divmod(remaining, 60)
    if minutes:
        return f"tra {minutes} min {seconds:02d} s"
    return f"tra {seconds} s"


def _search_allowed() -> bool:
    now = time.monotonic()
    if now < float(st.session_state.get("next_search_at", 0)):
        st.session_state["search_notice"] = "Attendi qualche secondo prima di una nuova ricerca."
        return False
    status = _quota(consume=True)
    if not status.get("allowed"):
        st.session_state["search_notice"] = (
            f"Hai raggiunto il limite orario. Potrai cercare di nuovo {_retry_label(status.get('retry_at', 0))}."
            if status.get("remaining") == 0
            else "La ricerca non è disponibile in questo momento."
        )
        return False
    st.session_state["next_search_at"] = now + app_constants.SEARCH_COOLDOWN_SECONDS
    return True


def _sort_products(products: list[dict], label: str) -> list[dict]:
    items = product_dedup.unique(products or [])
    if label == app_constants.SORT_PRICE:
        def price_key(product: dict) -> tuple:
            try:
                price = float(product.get("prezzo_finale"))
                verified = product.get("prezzo_verificato") is True and math.isfinite(price) and price > 0
            except (TypeError, ValueError):
                verified, price = False, float("inf")
            return (not verified, price)
        return sorted(items, key=price_key)

    def popularity_key(product: dict) -> tuple:
        sold = product.get("sold_qty_month")
        rank = product.get("sales_rank")
        try:
            if sold is not None:
                return (0, -int(sold))
        except (TypeError, ValueError):
            pass
        try:
            if rank is not None:
                return (1, int(rank))
        except (TypeError, ValueError):
            pass
        return (2, int(product.get("_amazon_position") or 10**9))
    return sorted(items, key=popularity_key)


def _load_search(target: int, append: bool = False) -> None:
    started = time.perf_counter()
    cfg = dict(st.session_state.get("last_search") or {})
    existing = list(st.session_state.get("offerte") or []) if append else []
    excluded = [str(p.get("asin") or "").strip().upper() for p in product_dedup.flatten(existing)]
    count = min(max(1, int(target)), MAX_RESULTS - len(existing) if append else MAX_RESULTS)
    if count <= 0:
        return
    try:
        with telemetry.timed("search_seconds"):
            products = catalog_service.search_products(
                keyword=str(cfg.get("keyword") or ""),
                sort_type=app_constants.SORT_TO_API.get(str(cfg.get("sort") or app_constants.SORT_PRICE), app_constants.SORT_PRICE),
                prime_only=bool(cfg.get("prime_only")),
                item_count=count,
                exclude_asins=excluded,
            )
    except amazon_api.shared_results.RetryPending as exc:
        st.session_state["search_notice"] = f"Amazon è temporaneamente occupato. Riprova {_retry_label(exc.retry_at)}."
        telemetry.increment("search_retry_pending")
        return
    except amazon_api.api_budget.BudgetUnavailable:
        st.session_state["search_notice"] = "La ricerca interna è temporaneamente non disponibile. Riprova più tardi."
        telemetry.increment("search_budget_unavailable")
        return
    except Exception:
        LOGGER.exception("Search failed")
        st.session_state["search_notice"] = "Non è stato possibile completare la ricerca."
        telemetry.increment("search_error")
        return

    merged = product_dedup.unique(existing + list(products or []))[:MAX_RESULTS]
    st.session_state["offerte"] = _sort_products(merged, str(cfg.get("sort") or app_constants.SORT_PRICE))
    st.session_state["has_searched"] = True
    if append and len(merged) > len(existing):
        st.session_state["current_page"] = max(1, (len(merged) + app_constants.SEARCH_PAGE_SIZE - 1) // app_constants.SEARCH_PAGE_SIZE)
    if products:
        st.session_state["search_notice"] = ""
        telemetry.increment("search_success")
        telemetry.observe("time_to_first_card_seconds", time.perf_counter() - started)
    else:
        st.session_state["search_notice"] = "Nessun nuovo prodotto disponibile. Prova un termine diverso."


ui_components.render_brand()
active_tab = st.session_state["current_tab"]
nav1, nav2, nav3 = st.columns(3, gap="small")
with nav1:
    st.button("HAUL", key="nav_haul", type="primary" if active_tab == "haul" else "secondary", on_click=_open_haul, use_container_width=True)
with nav2:
    st.button("Vetrina", key="nav_vetrina", type="primary" if active_tab == "vetrina" else "secondary", on_click=_open_vetrina, use_container_width=True)
with nav3:
    st.button("Cerca", key="nav_search", type="primary" if active_tab == "cerca" else "secondary", on_click=_set_tab, args=("cerca",), use_container_width=True)

try:
    shortcut = components.declare_component("home_shortcut", path=str(Path(__file__).parent / "home_shortcut"))
    shortcut(key="home_shortcut_prompt", default=None)
except Exception:
    LOGGER.debug("Home shortcut component unavailable", exc_info=True)

partner_tag = amazon_gateway.get_partner_tag()
if not partner_tag:
    st.error("Configurazione Amazon incompleta: le offerte sono temporaneamente non disponibili.")

active_tab = st.session_state["current_tab"]

if active_tab == "haul":
    st.markdown("<div class='promo'><span class='haul-badge'>HAUL</span> Scopri una selezione di prodotti. Promozioni e condizioni possono cambiare: verifica sempre i dettagli su Amazon.</div>", unsafe_allow_html=True)
    current_token = str(st.session_state["haul_refresh_token"])
    if partner_tag and st.session_state.get("haul_loaded_token") != current_token:
        try:
            with st.spinner("Sto cercando nuove proposte HAUL…"), telemetry.timed("haul_load_seconds"):
                products = catalog_service.get_haul_selection(app_constants.DISPLAY_BATCH_SIZE, current_token, st.session_state.get("haul_seen_asins", []))
            st.session_state["offerte_haul"] = product_dedup.unique(products or [])
            st.session_state["haul_seen_asins"] = catalog_service.extend_history(st.session_state.get("haul_seen_asins", []), st.session_state["offerte_haul"], catalog_service.HAUL_HISTORY_LIMIT)
            st.session_state["haul_loaded_token"] = current_token
            telemetry.increment("haul_refresh_success")
        except amazon_api.shared_results.RetryPending:
            st.info("HAUL è in aggiornamento. Riprova tra poco.")
        except Exception:
            LOGGER.exception("HAUL load failed")
            telemetry.increment("haul_refresh_error")
            st.info("Non è stato possibile aggiornare HAUL in questo momento.")

    products = product_dedup.unique(st.session_state.get("offerte_haul", []))
    if products:
        ui_components.render_section_label(f"Proposte HAUL · {len(products)} prodotti")
        ui_components.render_price_notice()
        for index, product in enumerate(products):
            ui_components.render_product_card(product, eager_image=index == 0)
        st.button(f"Mostrami altri {app_constants.DISPLAY_BATCH_SIZE}", key="haul_more", on_click=_open_haul, use_container_width=True)
        ui_components.render_back_to_top()
    else:
        st.info("Nessun prodotto HAUL disponibile adesso.")
        st.link_button("Apri Amazon HAUL", amazon_gateway.build_haul_link(), use_container_width=True)

elif active_tab == "vetrina":
    st.markdown("<div class='promo'><strong>Vetrina</strong> · Idee d’acquisto aggiornate senza dover fare subito una ricerca.</div>", unsafe_allow_html=True)
    current_token = str(st.session_state["vetrina_refresh_token"])
    if partner_tag and st.session_state.get("vetrina_loaded_token") != current_token:
        try:
            with st.spinner("Sto aggiornando la Vetrina…"), telemetry.timed("showcase_load_seconds"):
                products = catalog_service.get_showcase_selection(app_constants.DISPLAY_BATCH_SIZE, current_token, st.session_state.get("vetrina_seen_asins", []))
            st.session_state["offerte_vetrina"] = product_dedup.unique(products or [])
            st.session_state["vetrina_seen_asins"] = catalog_service.extend_history(st.session_state.get("vetrina_seen_asins", []), st.session_state["offerte_vetrina"], catalog_service.SHOWCASE_HISTORY_LIMIT)
            st.session_state["vetrina_loaded_token"] = current_token
            telemetry.increment("showcase_refresh_success")
        except Exception:
            LOGGER.exception("Showcase load failed")
            telemetry.increment("showcase_refresh_error")
            st.info("La Vetrina è temporaneamente non disponibile.")

    products = product_dedup.unique(st.session_state.get("offerte_vetrina", []))
    if products:
        ui_components.render_section_label(f"Scelti per te · {len(products)} prodotti")
        ui_components.render_price_notice()
        for index, product in enumerate(products):
            ui_components.render_product_card(product, eager_image=index == 0)
        st.button(f"Aggiorna altre {app_constants.DISPLAY_BATCH_SIZE} proposte", key="showcase_more", on_click=_open_vetrina, use_container_width=True)
        ui_components.render_back_to_top()
    else:
        st.link_button("Scopri le offerte su Amazon", amazon_gateway.build_search_link("offerte del giorno"), use_container_width=True)

elif active_tab == "cerca":
    _initialize_browser_identity()
    st.subheader("Cerca su Amazon")
    status = _quota()
    if not st.session_state.get("visitor_id"):
        st.info("La ricerca si sta inizializzando. HAUL e Vetrina restano disponibili.")
    elif status.get("remaining") is not None:
        if status.get("remaining") == 0:
            st.caption(f"Ricerche disponibili: 0 · nuova ricerca {_retry_label(status.get('retry_at', 0))}")
        else:
            st.caption(f"Ricerche disponibili nell’ultima ora: {status.get('remaining')} su {_search_limit()}")

    col_search, col_button, col_clear = st.columns([5, 1, 1], gap="small")
    with col_search:
        st.text_input("Prodotto", placeholder="Es. cuffie bluetooth, scarpe running, friggitrice ad aria…", label_visibility="collapsed", key="search_keyword_input")
    with col_button:
        submitted = st.button("Cerca", key="search_submit", type="primary", use_container_width=True, disabled=not st.session_state.get("visitor_id") or status.get("remaining") == 0)
    with col_clear:
        st.button("Cancella", key="clear_search", use_container_width=True, on_click=_clear_search)

    st.radio("Ordina per", app_constants.SORT_OPTIONS, horizontal=True, key="search_sort")
    st.checkbox("Solo prodotti Prime", key="search_prime_only")
    st.caption("“Più venduti” usa indicatori di popolarità disponibili da Amazon; non è un conteggio esatto delle unità vendute.")

    if submitted:
        keyword = " ".join(str(st.session_state.get("search_keyword_input") or "").split())
        if not keyword:
            st.session_state["search_notice"] = "Inserisci almeno un prodotto o una categoria."
        elif _search_allowed():
            st.session_state["last_search"] = {"keyword": keyword, "sort": str(st.session_state.get("search_sort") or app_constants.SORT_PRICE), "prime_only": bool(st.session_state.get("search_prime_only"))}
            st.session_state["current_page"] = 1
            st.session_state["offerte"] = []
            _load_search(app_constants.SEARCH_PAGE_SIZE, append=False)

    notice = str(st.session_state.get("search_notice") or "")
    if notice:
        st.info(notice)

    results = _sort_products(st.session_state.get("offerte", []), str(st.session_state.get("search_sort") or app_constants.SORT_PRICE))
    st.session_state["offerte"] = results
    if results:
        ui_components.render_section_label(f"Risultati di ricerca · {len(results)} prodotti caricati")
        ui_components.render_price_notice()
        total = len(results)
        pages = max(1, math.ceil(total / app_constants.SEARCH_PAGE_SIZE))
        current_page = min(max(1, int(st.session_state.get("current_page", 1))), pages)
        if pages > 1:
            page = st.selectbox("Pagina", list(range(1, pages + 1)), index=current_page - 1, format_func=lambda value: f"Pagina {value}")
            st.session_state["current_page"] = int(page)
            current_page = int(page)
        start = (current_page - 1) * app_constants.SEARCH_PAGE_SIZE
        end = min(start + app_constants.SEARCH_PAGE_SIZE, total)
        st.caption(f"Prodotti {start + 1}-{end} di {total}")
        for index, product in enumerate(results[start:end]):
            ui_components.render_product_card(product, eager_image=index == 0)

        status = _quota()
        can_load = len(results) < MAX_RESULTS and status.get("remaining") != 0
        if st.button(f"Carica altri {app_constants.SEARCH_PAGE_SIZE}", key="load_more", use_container_width=True, disabled=not can_load):
            if _search_allowed():
                _load_search(min(app_constants.SEARCH_PAGE_SIZE, MAX_RESULTS - len(results)), append=True)
                st.rerun()
        ui_components.render_back_to_top()

    status = _quota()
    if status.get("remaining") == 0:
        st.info(f"Limite orario raggiunto. Potrai cercare di nuovo {_retry_label(status.get('retry_at', 0))}. I risultati già caricati restano consultabili.")
        st.link_button("Continua su Amazon", amazon_gateway.build_search_link(str(st.session_state.get("search_keyword_input") or "offerte")), use_container_width=True)

elif active_tab == "privacy":
    st.subheader("Informativa privacy")
    st.markdown(
        """
**Titolare del trattamento:** Davide Marziano. Contatto: profilo GitHub del titolare collegato nel footer.

**Dati trattati.** Il sito usa un identificatore casuale del browser per applicare il limite orario delle ricerche e conserva sul server gli orari recenti associati a un identificatore pseudonimizzato. Non sono richiesti nome, email o account.

**Finalità e base giuridica.** I dati tecnici sono usati per prevenire abusi, proteggere le risorse del servizio e mantenere preferenze locali dell’interfaccia.

**Conservazione.** Gli eventi di ricerca sono eliminati automaticamente dopo 60 minuti. L’identificatore browser scade dopo 90 giorni. Telemetria e log tecnici devono essere conservati solo per il tempo necessario alla diagnostica e secondo la configurazione effettiva dell’hosting.

**Destinatari e servizi esterni.** L’applicazione è ospitata sull’infrastruttura configurata dal titolare e contiene collegamenti ad Amazon.it. Se Redis è configurato, viene usato per cache, rate limit e budget distribuito. Aprendo un collegamento Amazon, il trattamento successivo è soggetto alle informative Amazon.

**Diritti.** Nei casi previsti dal GDPR è possibile richiedere accesso, rettifica, cancellazione, limitazione o opposizione e proporre reclamo all’autorità competente.

**Affiliazione.** In qualità di Affiliato Amazon il titolare riceve un guadagno dagli acquisti idonei. Prezzi, disponibilità, promozioni e condizioni possono cambiare; fanno fede le informazioni mostrate su Amazon al momento dell’acquisto.
        """
    )
    st.link_button("Contatta il titolare", "https://github.com/davimarz", use_container_width=True)
    st.button("Torna alla Vetrina", on_click=_open_vetrina, use_container_width=True)

ui_components.render_footer()
with st.expander("Aggiungi alla schermata Home"):
    st.markdown("**iPhone / Safari:** Condividi → Aggiungi alla schermata Home.  \n**Android / Chrome:** menu → Aggiungi a schermata Home.")
