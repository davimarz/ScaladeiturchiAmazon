# Scala dei Turchi — applicazione Amazon

Applicazione Streamlit per scoprire prodotti Amazon tramite **HAUL**, **Vetrina** e **Cerca**.

## Comportamento attuale

- HAUL, Vetrina e Cerca mostrano **3 prodotti per pagina/blocco**.
- Navigare tra HAUL, Vetrina e Cerca **non forza un nuovo recupero**: le proposte già visualizzate restano in sessione.
- I pulsanti “Mostrami altri 3” e “Aggiorna altre 3 proposte” sono gli unici che chiedono esplicitamente un nuovo campione.
- La ricerca recupera fino a **6 risultati per richiesta** e ne mostra 3 per pagina, così la pagina successiva può essere già pronta.
- Prezzi e sconti vengono visualizzati solo quando provengono da un segnale Amazon considerato affidabile: verifica dettaglio oppure nodo prezzo esplicito Amazon.
- Prezzo, dati prodotto e relativi timestamp sono distinti: `_fetched_at` indica il recupero della scheda, `price_verified_at` la verifica del prezzo.

## Priorità della sorgente Amazon e affiliazione

Il percorso principale resta **Creators API con le credenziali configurate per l’account affiliato**. Il `partner_tag` configurato continua a essere applicato ai link idonei.

La policy è intenzionalmente **primary-first**:

1. Creators API viene tentata per prima;
2. se Amazon risponde con `AssociateNotEligible`, il circuito primary viene sospeso temporaneamente;
3. il fallback Amazon/HTML può essere usato durante il cooldown se `data_source_mode` lo consente;
4. dopo **60 minuti** Creators API viene ritentata automaticamente;
5. se torna disponibile, riprende la precedenza;
6. fallback, cooldown e retry **non eliminano né modificano** credential ID, secret o Partner Tag.

La costante applicativa è `CREATORS_PRIMARY_RETRY_SECONDS = 3600` e deve restare allineata a `amazon_api.CREATORS_403_COOLDOWN`.

Per disabilitare i fallback HTML usare:

```toml
[amazon_api]
data_source_mode = "api_only"
```

La modalità predefinita/ibrida mantiene invece il failover temporaneo.

## Architettura

- `app.py`: navigazione, session state e flusso Streamlit.
- `app_constants.py`: unica fonte per batch UI, prefetch, recovery e timeout condivisi.
- `catalog_service.py`: pool HAUL/Vetrina, campionamento, timestamp e ricerca.
- `amazon_gateway.py`: confine applicativo verso le sorgenti Amazon; unico recovery dettaglio della ricerca e cache dettagli ASIN.
- `creators_api.py`: policy e accesso alla ricerca primary-first.
- `amazon_html.py`: parser/flow HTML specifici per HAUL e Vetrina.
- `http_client.py`: confine HTTP pubblico usato dai nuovi flussi HTML; mantiene temporaneamente compatibilità con il legacy in `amazon_api.py`.
- `price_parser.py`: parsing prezzo corrente, listino, sconto, JSON-LD e markup Amazon.
- `amazon_api.py`: compatibilità legacy e implementazione Creators/fallback storico; viene progressivamente ridotto.
- `product_models.py`: modello `Product` condiviso.
- `product_dedup.py`: deduplicazione ASIN/modello/varianti.
- `shared_results.py`: cache memoria/Redis con fresh + stale fallback.
- `api_budget.py`: budget/pacing API condiviso.
- `visitor_limit.py`: limite ricerche rolling-hour.
- `telemetry.py`: metriche operative in memoria.
- `ui_components.py`: card prodotto, CSS, disclaimer e link affiliati.

## HAUL

Il pool HAUL viene condiviso per un TTL breve. Ogni sessione mantiene la cronologia degli ASIN già mostrati e preferisce prodotti non ancora visti. La navigazione verso HAUL non cambia la selezione; soltanto “Mostrami altri 3” aggiorna il token di campionamento.

In caso di errore di aggiornamento, le proposte già presenti in sessione restano visibili.

## Vetrina

La Vetrina usa pagine Amazon dirette (offerte, più venduti, novità, tendenze), crea un pool condiviso e seleziona 3 prodotti. Solo i prodotti effettivamente mostrati vengono arricchiti dal dettaglio Amazon.

I dettagli sono memorizzati per ASIN per 15 minuti. Le tre verifiche vengono eseguite in parallelo con una deadline globale; se una richiesta dettaglio è lenta o fallisce, la card di base viene comunque mantenuta invece di bloccare l’intera Vetrina.

La cache della Vetrina mantiene anche uno stale condiviso Redis per resistere a errori temporanei del loader.

## Cerca

Una nuova ricerca recupera fino a 6 prodotti, ma l’interfaccia continua a mostrarne 3 per pagina. Il recovery dettaglio dei risultati incompleti avviene in un solo livello (`amazon_gateway.py`), evitando la precedente doppia verifica.

“Prezzo minimo” ordina usando la stessa regola con cui l’interfaccia decide se un prezzo è visualizzabile, quindi considera anche prezzi Amazon SERP affidabili e non soltanto `prezzo_verificato=True`.

Una nuova ricerca e un ulteriore caricamento consumano ciascuno una quota del limite orario; l’interfaccia lo indica esplicitamente.

## Prezzi

Il prezzo può essere mostrato quando:

- è stato verificato sulla pagina dettaglio Amazon; oppure
- proviene da un nodo prezzo Amazon esplicito marcato con `_serp_price_confidence="base_price_node"`.

Non vengono inventati prezzi, listini o sconti. Se il dato non è affidabile, la card rimanda alla verifica su Amazon.

Quando disponibile, la UI usa `price_verified_at` per il testo “Prezzo verificato …”. `_fetched_at` viene usato soltanto per indicare quando sono stati recuperati i dati generali del prodotto.

## Cache e Redis

`shared_results.py` usa due livelli Redis:

- chiave **fresh** con TTL normale;
- chiave **stale** con una finestra più lunga.

Se il loader fallisce ma esiste uno stale valido, lo stale viene restituito anche quando `report_failure=True`; l’errore viene sollevato solo quando non esiste alcun dato utilizzabile. Per i cataloghi stale, i prezzi vengono rimossi per non presentare come corrente un valore vecchio.

Configurazione raccomandata per produzione multi-instance:

```text
REDIS_URL=rediss://...
STRICT_REDIS=1
VISITOR_HASH_SECRET=<segreto-lungo-casuale>
SCALA_SHARED_CACHE_REDIS=1
```

Se `STRICT_REDIS=1`, un guasto Redis non degrada silenziosamente verso SQLite per i controlli distribuiti.

## Privacy e rate limit

Il componente browser genera un UUID casuale con durata massima di 90 giorni. Sul server l’identificatore viene pseudonimizzato; con `VISITOR_HASH_SECRET` viene usato HMAC-SHA256.

Gli eventi del limiter vengono rimossi dopo 60 minuti. La policy applicativa per i log tecnici diagnostici è di non conservarli oltre 30 giorni; la configurazione effettiva dell’hosting deve rispettare questa policy.

Il limite per UUID browser è un controllo di uso ordinario, non una misura antifrode forte: cancellando `localStorage` l’identificatore può essere rigenerato. Il budget API globale rimane la protezione di servizio separata.

## Secrets Amazon

Configurare nella sezione `amazon_api` dei secrets Streamlit, senza inserirli nel repository:

- `partner_tag`
- `credential_id`
- `credential_secret`
- `credential_version`
- `daily_request_budget`
- `request_interval_seconds`
- `searches_per_hour`
- `data_source_mode`

`.streamlit/secrets.toml`, `.env`, `.runtime/` e file SQLite devono restare esclusi da Git.

## Test e CI

La CI esegue:

- compilazione;
- test unitari su Python **3.12 e 3.14**;
- test con Redis;
- `pip-audit`;
- Gitleaks;
- smoke test end-to-end Playwright su viewport smartphone.

Sono presenti fixture HTML Amazon ridotte e anonimizzate per storefront, HAUL e JSON-LD.

Comandi locali:

```bash
python -m pip install -r requirements-dev.txt
python -m compileall -q .
pytest -q -m "not e2e"
```

## Controlli amministrativi da mantenere

Questi controlli non possono essere imposti dal codice dell’app:

- protezione di `main` con PR e CI obbligatorie;
- deploy key Streamlit in sola lettura salvo necessità esplicita di scrittura;
- `STRICT_REDIS=1`, `REDIS_URL` e `VISITOR_HASH_SECRET` realmente configurati nel deployment;
- retention dei log del provider coerente con la policy dichiarata.

## Nota sull’affiliazione

In qualità di Affiliato Amazon il titolare riceve un guadagno dagli acquisti idonei. Prezzi, disponibilità, promozioni e condizioni possono cambiare; fanno fede le informazioni mostrate su Amazon al momento dell’acquisto.
