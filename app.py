from __future__ import annotations

import logging
import math
import time
import uuid
from pathlib import Path

import streamlit as st
import streamlit.components.v1 as components

import amazon_gateway
import app_constants
import catalog_service
import services
import telemetry
import ui_components
import visitor_limit

st.set_page_config(page_title="Scala dei Turchi | Offerte Amazon", page_icon="🛍️", layout="wide", initial_sidebar_state="collapsed")
LOGGER = logging.getLogger("amazon_affiliate_app")
logging.getLogger("amazon_affiliate").setLevel(logging.WARNING)
MAX_RESULTS = amazon_gateway.MAX_RESULTS
DEFAULTS = {"current_tab":"haul","offerte_haul":[],"haul_refresh_token":str(time.time_ns()),"haul_loaded_token":None,"haul_seen_asins":[],"offerte":[],"has_searched":False,"current_page":1,"search_keyword_input":"","search_sort":app_constants.SORT_PRICE,"search_prime_only":False,"last_search":{"keyword":"","sort":app_constants.SORT_PRICE,"prime_only":False},"search_notice":"","next_search_at":0.0,"visitor_id":None,"reset_identity_requested":False,"identity_reset_notice":False}
for key,value in DEFAULTS.items(): st.session_state.setdefault(key,value)
if st.session_state.get("current_tab") not in {"haul","cerca","privacy"}: st.session_state["current_tab"]="haul"
try:
    if str(st.query_params.get("privacy",""))=="1": st.session_state["current_tab"]="privacy"
except Exception: pass
ui_components.inject_css()

def _clear_query_params():
    try: st.query_params.clear()
    except Exception: pass

def _set_tab(name): st.session_state["current_tab"]=name; _clear_query_params()
def _refresh_haul(): st.session_state["current_tab"]="haul"; st.session_state["haul_refresh_token"]=str(time.time_ns()); st.session_state["haul_loaded_token"]=None; _clear_query_params()
def _clear_search(): st.session_state["search_keyword_input"]=""; st.session_state["offerte"]=[]; st.session_state["has_searched"]=False; st.session_state["search_notice"]=""; st.session_state["current_page"]=1
def _request_identity_reset(): st.session_state["reset_identity_requested"]=True; st.session_state["identity_reset_notice"]=False

def _valid_uuid(value):
    try: return str(uuid.UUID(str(value)))
    except (ValueError,TypeError,AttributeError): return None

def _initialize_browser_identity(reset=False):
    try:
        component=components.declare_component("browser_identity",path=str(Path(__file__).parent/"browser_identity"))
        value=component(key="persistent_browser_identity",default=None,reset_identity=bool(reset)); valid=_valid_uuid(value)
        if valid:
            previous=st.session_state.get("visitor_id"); st.session_state["visitor_id"]=valid
            if reset and valid!=previous: st.session_state["reset_identity_requested"]=False; st.session_state["identity_reset_notice"]=True
        elif value: LOGGER.warning("invalid_visitor_id_rejected"); telemetry.increment("invalid_visitor_id")
    except Exception as exc: LOGGER.warning("browser_identity_unavailable error_type=%s",type(exc).__name__); telemetry.increment("browser_identity_error")

def _search_limit():
    try: return max(1,int(st.secrets.get("amazon_api",{}).get("searches_per_hour",10)))
    except Exception: return 10

def _quota(consume=False):
    visitor=st.session_state.get("visitor_id")
    if not visitor: return {"allowed":False,"remaining":None,"retry_at":0,"backend":"none"}
    try: return visitor_limit.check(visitor,_search_limit(),consume)
    except Exception as exc: LOGGER.warning("quota_unavailable error_type=%s",type(exc).__name__); telemetry.increment("quota_backend_error"); return {"allowed":False,"remaining":None,"retry_at":0,"backend":"error"}

def _retry_label(retry_at):
    remaining=max(0,int(float(retry_at or 0)-time.time()))
    if remaining<=0:return "tra poco"
    minutes,seconds=divmod(remaining,60); return f"tra {minutes} min {seconds:02d} s" if minutes else f"tra {seconds} s"

def _search_allowed(*,consume_quota,known_status=None):
    now=time.monotonic()
    if now<float(st.session_state.get("next_search_at",0)): st.session_state["search_notice"]="Attendi qualche secondo prima di una nuova richiesta."; return False
    status=known_status or _quota(False)
    if status.get("remaining")==0: st.session_state["search_notice"]=f"Hai raggiunto il limite orario. Potrai cercare di nuovo {_retry_label(status.get('retry_at',0))}."; return False
    if status.get("remaining") is None and status.get("backend")=="error": st.session_state["search_notice"]="La ricerca non è disponibile in questo momento."; return False
    if consume_quota:
        consumed=_quota(True)
        if not consumed.get("allowed"): st.session_state["search_notice"]=f"Hai raggiunto il limite orario. Potrai cercare di nuovo {_retry_label(consumed.get('retry_at',0))}." if consumed.get("remaining")==0 else "La ricerca non è disponibile in questo momento."; return False
    st.session_state["next_search_at"]=now+app_constants.SEARCH_COOLDOWN_SECONDS; return True

def _sort_products(products,label):
    items=list(products or [])
    if label==app_constants.SORT_PRICE:
        def price_key(product):
            try: price=float(product.get("prezzo_finale")); displayable=catalog_service.price_is_displayable(product) and math.isfinite(price) and price>0
            except (TypeError,ValueError): displayable,price=False,float("inf")
            return (not displayable,price)
        return sorted(items,key=price_key)
    def popularity_key(product):
        try:
            sold=product.get("sold_qty_month")
            if sold is not None:return (0,-int(sold))
        except (TypeError,ValueError):pass
        try:
            rank=product.get("sales_rank")
            if rank is not None:return (1,int(rank))
        except (TypeError,ValueError):pass
        return (2,int(product.get("_amazon_position") or 10**9))
    return sorted(items,key=popularity_key)

def _load_search(target,append=False):
    started=time.perf_counter(); cfg=dict(st.session_state.get("last_search") or {}); existing=list(st.session_state.get("offerte") or []) if append else []
    excluded=[str(p.get("asin") or "").strip().upper() for p in existing if str(p.get("asin") or "").strip()]; count=min(max(1,int(target)),MAX_RESULTS-len(existing) if append else MAX_RESULTS)
    if count<=0:return
    try:
        with telemetry.timed("search_seconds"): products=services.search_service.search(keyword=str(cfg.get("keyword") or ""),sort_type=app_constants.SORT_TO_API.get(str(cfg.get("sort") or app_constants.SORT_PRICE),app_constants.SORT_PRICE),prime_only=bool(cfg.get("prime_only")),item_count=count,exclude_asins=excluded)
    except amazon_gateway.RetryPending as exc: st.session_state["search_notice"]=f"Amazon è temporaneamente occupato. Riprova {_retry_label(exc.retry_at)}."; telemetry.increment("search_retry_pending"); return
    except amazon_gateway.BudgetUnavailable: st.session_state["search_notice"]="La ricerca interna è temporaneamente non disponibile. Riprova più tardi."; telemetry.increment("search_budget_unavailable"); return
    except Exception as exc: LOGGER.warning("search_failed error_type=%s",type(exc).__name__); st.session_state["search_notice"]="Non è stato possibile completare la ricerca."; telemetry.increment("search_error"); return
    by_asin={}; anonymous=[]
    for product in [*existing,*list(products or [])]:
        asin=str(product.get("asin") or "").strip().upper()
        if asin:by_asin[asin]=dict(product)
        else:anonymous.append(dict(product))
    merged=[*by_asin.values(),*anonymous][:MAX_RESULTS]; st.session_state["offerte"]=_sort_products(merged,str(cfg.get("sort") or app_constants.SORT_PRICE)); st.session_state["has_searched"]=True
    if append and len(merged)>len(existing):st.session_state["current_page"]=max(1,(len(existing)//app_constants.SEARCH_PAGE_SIZE)+1)
    if products: st.session_state["search_notice"]=""; telemetry.increment("search_success"); telemetry.observe("time_to_first_card_seconds",time.perf_counter()-started)
    else:st.session_state["search_notice"]="Nessun nuovo prodotto disponibile. Prova un termine diverso."

def _render_navigation():
    active=st.session_state["current_tab"]
    with st.container(key="main_nav"):
        ui_components.render_nav_accessibility(active); nav1,nav2=st.columns(2,gap="small")
        with nav1:st.button("HAUL",key="nav_haul",type="primary" if active=="haul" else "secondary",on_click=_set_tab,args=("haul",),use_container_width=True)
        with nav2:st.button("Cerca",key="nav_search",type="primary" if active=="cerca" else "secondary",on_click=_set_tab,args=("cerca",),use_container_width=True)

ui_components.render_brand(); _render_navigation(); partner_tag=amazon_gateway.get_partner_tag()
if not partner_tag:st.error("Configurazione Amazon incompleta: le offerte sono temporaneamente non disponibili.")
active_tab=st.session_state["current_tab"]

if active_tab=="haul":
    st.markdown("<div class='promo'><span class='haul-badge'>HAUL</span> Scopri una selezione di prodotti. Promozioni e condizioni possono cambiare: verifica sempre i dettagli su Amazon.</div>",unsafe_allow_html=True)
    current_token=str(st.session_state["haul_refresh_token"])
    if partner_tag and st.session_state.get("haul_loaded_token")!=current_token:
        try:
            with st.spinner("Sto cercando nuove proposte HAUL…"),telemetry.timed("haul_load_seconds"):products=services.haul_service.get(app_constants.DISPLAY_BATCH_SIZE,current_token,st.session_state.get("haul_seen_asins",[]))
            if products:st.session_state["offerte_haul"]=list(products); st.session_state["haul_seen_asins"]=catalog_service.extend_history(st.session_state.get("haul_seen_asins",[]),products,catalog_service.HAUL_HISTORY_LIMIT)
            st.session_state["haul_loaded_token"]=current_token; telemetry.increment("haul_refresh_success")
        except amazon_gateway.RetryPending:st.info("HAUL è in aggiornamento. Restano visibili le proposte precedenti.")
        except Exception as exc:LOGGER.warning("haul_load_failed error_type=%s",type(exc).__name__); telemetry.increment("haul_refresh_error"); st.info("Aggiornamento HAUL non riuscito; restano visibili le proposte precedenti.")
    products=list(st.session_state.get("offerte_haul",[]))
    if products:
        ui_components.render_section_label(f"Proposte HAUL · {len(products)} prodotti"); ui_components.render_price_notice()
        for index,product in enumerate(products):ui_components.render_product_card(product,eager_image=index==0)
        st.button(f"Mostrami altri {app_constants.DISPLAY_BATCH_SIZE}",key="haul_more",on_click=_refresh_haul,use_container_width=True); ui_components.render_back_to_top()
    else:st.info("Nessun prodotto HAUL disponibile adesso."); st.link_button("Apri Amazon HAUL",amazon_gateway.build_haul_link(),use_container_width=True)

elif active_tab=="cerca":
    _initialize_browser_identity(); st.subheader("Cerca su Amazon"); status=_quota(False)
    if not st.session_state.get("visitor_id"):st.info("La ricerca si sta inizializzando. HAUL resta disponibile.")
    elif status.get("remaining") is not None:
        if status.get("remaining")==0:st.caption(f"Ricerche disponibili: 0 · nuova ricerca {_retry_label(status.get('retry_at',0))}")
        else:st.caption(f"Nuove ricerche disponibili nell’ultima ora: {status.get('remaining')} su {_search_limit()}")
    with st.container(key="search_controls"):
        col_search,col_button,col_clear=st.columns([5,1,1],gap="small")
        with col_search:st.text_input("Prodotto",placeholder="Es. cuffie bluetooth, scarpe running, friggitrice ad aria…",label_visibility="collapsed",key="search_keyword_input")
        with col_button:submitted=st.button("Cerca",key="search_submit",type="primary",use_container_width=True,disabled=not st.session_state.get("visitor_id") or status.get("remaining")==0)
        with col_clear:st.button("Cancella",key="clear_search",use_container_width=True,on_click=_clear_search)
    st.radio("Ordina per",app_constants.SORT_OPTIONS,horizontal=True,key="search_sort"); st.checkbox("Solo prodotti Prime",key="search_prime_only")
    st.caption("“Più venduti” usa indicatori di popolarità Amazon. Ogni pagina mostra 3 prodotti; “Carica altri” continua la stessa ricerca e non consuma una nuova quota utente.")
    if submitted:
        keyword=" ".join(str(st.session_state.get("search_keyword_input") or "").split())
        if not keyword:st.session_state["search_notice"]="Inserisci almeno un prodotto o una categoria."
        elif _search_allowed(consume_quota=True,known_status=status):
            st.session_state["last_search"]={"keyword":keyword,"sort":str(st.session_state.get("search_sort") or app_constants.SORT_PRICE),"prime_only":bool(st.session_state.get("search_prime_only"))}; st.session_state["current_page"]=1; st.session_state["offerte"]=[]
            with st.spinner(f"Sto cercando “{keyword}” su Amazon…"):_load_search(app_constants.SEARCH_PREFETCH_SIZE,append=False)
    notice=str(st.session_state.get("search_notice") or "")
    if notice:st.info(notice)
    results=_sort_products(st.session_state.get("offerte",[]),str(st.session_state.get("search_sort") or app_constants.SORT_PRICE)); st.session_state["offerte"]=results
    if results:
        ui_components.render_section_label(f"Risultati di ricerca · {len(results)} prodotti caricati"); ui_components.render_price_notice(); total=len(results); pages=max(1,math.ceil(total/app_constants.SEARCH_PAGE_SIZE)); current_page=min(max(1,int(st.session_state.get("current_page",1))),pages)
        if pages>1:
            prev_col,info_col,next_col=st.columns([1,1.5,1],gap="small")
            with prev_col:
                if st.button("‹ Precedente",disabled=current_page<=1,use_container_width=True,key="search_prev"):current_page-=1; st.session_state["current_page"]=current_page
            with info_col:st.markdown(f"<div style='text-align:center;padding:.65rem 0;font-weight:700'>Pagina {current_page}/{pages}</div>",unsafe_allow_html=True)
            with next_col:
                if st.button("Successiva ›",disabled=current_page>=pages,use_container_width=True,key="search_next"):current_page+=1; st.session_state["current_page"]=current_page
        start=(current_page-1)*app_constants.SEARCH_PAGE_SIZE; end=min(start+app_constants.SEARCH_PAGE_SIZE,total); st.caption(f"Prodotti {start+1}-{end} di {total}")
        for index,product in enumerate(results[start:end]):ui_components.render_product_card(product,eager_image=index==0)
        can_load=len(results)<MAX_RESULTS and status.get("remaining")!=0
        if st.button(f"Carica altri risultati · {app_constants.SEARCH_PAGE_SIZE} per pagina",key="load_more",use_container_width=True,disabled=not can_load):
            if _search_allowed(consume_quota=app_constants.LOAD_MORE_COUNTS_AS_USER_SEARCH,known_status=status):
                with st.spinner("Sto cercando altri prodotti su Amazon…"):_load_search(min(app_constants.SEARCH_PREFETCH_SIZE,MAX_RESULTS-len(results)),append=True)
                st.rerun()
        ui_components.render_back_to_top()
    if status.get("remaining")==0:st.info(f"Limite orario raggiunto. Potrai fare una nuova ricerca {_retry_label(status.get('retry_at',0))}. I risultati già caricati restano consultabili."); st.link_button("Continua su Amazon",amazon_gateway.build_search_link(str(st.session_state.get("search_keyword_input") or "offerte")),use_container_width=True)

elif active_tab=="privacy":
    reset_requested=bool(st.session_state.get("reset_identity_requested")); _initialize_browser_identity(reset=reset_requested); st.subheader("Informativa privacy")
    st.markdown("""**Titolare del trattamento:** Davide Marziano. Contatto: profilo GitHub del titolare collegato nel footer.

**Dati trattati.** Il sito usa un identificatore casuale del browser per applicare il limite orario delle ricerche. Sul server viene conservata una forma pseudonimizzata: HMAC-SHA256 quando `VISITOR_HASH_SECRET` è configurato, altrimenti SHA-256. Non sono richiesti nome, email o account.

**Finalità e base giuridica.** I dati tecnici servono a prevenire abusi, proteggere le risorse del servizio e mantenere preferenze locali dell’interfaccia. L'identificatore browser non è un sistema antifrode forte.

**Conservazione.** Gli eventi di ricerca vengono eliminati dopo 60 minuti e l’identificatore browser scade dopo 90 giorni. I log tecnici devono restare coerenti con la retention effettivamente configurata sull'hosting.

**Destinatari e servizi esterni.** L’applicazione è ospitata sull’infrastruttura configurata dal titolare e contiene collegamenti ad Amazon.it. Aprendo un collegamento Amazon, il trattamento successivo è soggetto alle informative Amazon.

**Diritti.** Nei casi previsti dal GDPR è possibile richiedere accesso, rettifica, cancellazione, limitazione o opposizione e proporre reclamo all’autorità competente.

**Affiliazione.** In qualità di Affiliato Amazon il titolare riceve un guadagno dagli acquisti idonei. Prezzi, disponibilità, promozioni e condizioni possono cambiare; fanno fede le informazioni mostrate su Amazon al momento dell’acquisto.""")
    if st.session_state.get("identity_reset_notice"):st.success("Identificatore locale rigenerato."); st.session_state["identity_reset_notice"]=False
    st.button("Rigenera identificatore locale",on_click=_request_identity_reset,use_container_width=True,help="Elimina l'identificatore locale corrente e ne crea uno nuovo."); st.link_button("Contatta il titolare","https://github.com/davimarz",use_container_width=True); st.button("Torna a HAUL",on_click=_set_tab,args=("haul",),use_container_width=True)

ui_components.render_footer()
