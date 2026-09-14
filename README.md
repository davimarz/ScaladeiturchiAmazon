# Scala dei Turchi — applicazione Amazon

Applicazione Streamlit per scoprire prodotti Amazon tramite **HAUL**, **Vetrina** e **Cerca**.

## Comportamento attuale

- HAUL, Vetrina e Cerca mostrano **3 prodotti per pagina/blocco**.
- Navigare tra le sezioni non forza un nuovo recupero: le proposte restano in sessione.
- “Mostrami altri 3” e “Aggiorna altre 3 proposte” cambiano esplicitamente la selezione.
- Cerca recupera fino a 6 risultati per richiesta e ne mostra 3 per pagina.
- “Carica altri risultati” continua la stessa ricerca e **non consuma una nuova quota utente**; il budget globale delle richieste Amazon resta separato.
- Prezzi e sconti vengono mostrati solo quando provengono da un segnale Amazon affidabile e ancora fresco.
- `_fetched_at`, `price_verified_at` e `displayed_at` rappresentano rispettivamente recupero dati, verifica prezzo e momento di visualizzazione.

## Priorità della sorgente Amazon e affiliazione

Il percorso principale resta **Creators API con le credenziali dell’account affiliato**. Il `partner_tag` configurato continua a essere applicato ai link idonei.

La policy è **primary-first**:

1. Creators API viene tentata per prima;
2. se Amazon risponde `AssociateNotEligible`, il primary entra in cooldown temporaneo;
3. durante il cooldown può essere usato il fallback Amazon/HTML, se abilitato;
4. dopo **60 minuti** Creators API viene ritentata automaticamente;
5. se torna disponibile, riprende la precedenza;
6. fallback e cooldown non cancellano né modificano credenziali o Partner Tag.

## Architettura

- `app.py`: stato sessione e orchestrazione Streamlit.
- `services.py`: facade `HaulService`, `ShowcaseService`, `SearchService`.
- `app_constants.py`: batch, timeout, cache schema e policy condivise.
- `catalog_service.py`: pool, campionamento, freschezza prezzi e metriche visibilità.
- `amazon_gateway.py`: confine applicativo verso le sorgenti Amazon e cache dettagli per ASIN.
- `creators_api.py`: policy Creators API primary-first.
- `haul_parser.py`: boundary HAUL.
- `showcase_parser.py`: boundary Vetrina.
- `amazon_html.py`: parsing HTML Amazon specifico.
- `http_client.py`: boundary HTTP e classificazione di risposte vuote/bloccate/503.
- `price_parser.py`: parsing prezzo, listino, sconto e JSON-LD.
- `amazon_api.py`: compatibilità legacy, progressivamente ridotta.
- `product_models.py`: modello prodotto e costanti per affidabilità/provenienza prezzi.
- `shared_results.py`: cache in memoria e Redis opzionale con fresh/stale.
- `redis_client.py`: client Redis opzionale centralizzato.
- `api_budget.py`: budget/pacing Amazon con SQLite di default e Redis opzionale.
- `visitor_limit.py`: limite rolling-hour per browser.
- `telemetry.py`: contatori, P50/P95, ratio e snapshot JSON periodici.
- `ui_components.py`: card, CSS, accessibilità e link affiliati.

## HAUL e Vetrina

Le sezioni mantengono la selezione precedente quando un aggiornamento fallisce. La Vetrina arricchisce soltanto i 3 prodotti visibili, in parallelo, con cache per ASIN e deadline globale.

Le metriche includono `price_visible_ratio`, `image_visible_ratio`, `detail_cache_hit_ratio` e numero di richieste dettaglio Amazon.

## Cerca

Una nuova ricerca consuma una quota utente. I successivi “Carica altri risultati” appartengono alla stessa ricerca e non consumano un’altra quota browser. Il budget globale API continua comunque a proteggere il servizio.

La paginazione mobile usa **Precedente / Pagina X/Y / Successiva** invece di molti pulsanti numerati.

## Prezzi

Un prezzo viene mostrato solo se:

- è verificato dalla pagina dettaglio Amazon; oppure
- proviene da un nodo prezzo Amazon esplicito considerato affidabile;
- e `price_verified_at` rientra nella finestra di freschezza configurata.

La provenienza (`price_source`) resta separata dalla semplice sorgente della scheda prodotto. Non vengono inventati prezzi, listini o sconti.

## Mobile e accessibilità

- navigazione principale sticky su smartphone;
- controlli ricerca adattivi sui display stretti;
- immagini con dimensioni stabili, lazy loading e priorità alta solo per la prima card;
- target touch da almeno 44 px;
- focus tastiera e `prefers-reduced-motion`;
- indicazione accessibile della sezione attiva;
- test Playwright per viewport mobile, tastiera e zoom 200%/400%.

Il prompt “Aggiungi alla schermata Home” è l’unico percorso di installazione rapida mostrato; il vecchio duplicato nell’expander è stato rimosso.

## Privacy

Il browser genera un UUID casuale che scade dopo 90 giorni. L’utente può rigenerarlo dalla pagina Privacy.

Sul server viene pseudonimizzato con **HMAC-SHA256** quando `VISITOR_HASH_SECRET` è configurato; senza tale segreto viene usato SHA-256. I termini di ricerca non vengono inseriti nei nuovi log diagnostici applicativi.

## Redis

Redis **non è obbligatorio**. Per una singola istanza Streamlit l’app usa SQLite/memoria e resta pienamente funzionante.

Se in futuro viene configurato Redis, `redis_client.py` centralizza timeout e supporta `rediss://` TLS. `STRICT_REDIS=1` ha senso soltanto quando Redis è realmente usato in produzione multi-instance.

## Sicurezza e qualità

La CI esegue:

- Python 3.12 e 3.14;
- compilazione e test unitari;
- Ruff per errori statici;
- mypy sui boundary tipizzati;
- `pip-audit`;
- Gitleaks;
- E2E Playwright e controlli accessibilità di base.

GitHub Actions sono pin-nate a commit SHA. È presente anche un workflow CodeQL per Python.

## Secrets Amazon

Configurare i valori nella sezione `amazon_api` dei Secrets Streamlit senza inserirli nel repository:

- `partner_tag`
- `credential_id`
- `credential_secret`
- `credential_version`
- `daily_request_budget`
- `request_interval_seconds`
- `searches_per_hour`
- `data_source_mode`

Non pubblicare mai credential secret, password applicative o altri token in chat, issue, commit o screenshot.

## Test locali

```bash
python -m pip install -r requirements-dev.txt
python -m compileall -q .
ruff check --select E9,F63,F7,F82 .
mypy app_constants.py product_models.py redis_client.py services.py
pytest -q -m "not e2e"
```

## Nota sull’affiliazione

In qualità di Affiliato Amazon il titolare riceve un guadagno dagli acquisti idonei. Prezzi, disponibilità, promozioni e condizioni possono cambiare; fanno fede le informazioni mostrate su Amazon al momento dell’acquisto.
