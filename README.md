# Scala dei Turchi — applicazione Amazon

Applicazione Streamlit per scoprire prodotti Amazon tramite HAUL, Vetrina e ricerca.

## Cosa cambia in questa revisione

- La cache HAUL conserva un **pool di prodotti**, non una selezione già sorteggiata.
- Ogni sessione mantiene una cronologia fino a 50 ASIN HAUL e privilegia prodotti non ancora mostrati.
- HAUL e Vetrina vengono ricaricati solo quando cambia il relativo refresh token, non a ogni rerun Streamlit.
- La Vetrina ruota tra più categorie e mantiene una cronologia separata.
- Le schede prodotto hanno gerarchia visiva più semplice, target touch da almeno 44 px e focus tastiera visibile.
- I campi taglia/colore mancanti non vengono più mostrati come “da verificare”.
- L'ordinamento “Quantità vendite” è rinominato **Più venduti** e viene spiegato come indicatore di popolarità, non come conteggio esatto delle vendite.
- Ogni prezzo mostrato è accompagnato da data/ora di aggiornamento e da un avviso sul possibile cambiamento del prezzo.
- L'informativa privacy è stata ampliata e l'identificatore browser scade dopo 90 giorni.
- Gli UUID dei visitatori sono hashati prima della persistenza lato server.
- Il rate limit e il budget API possono usare Redis condiviso tramite `REDIS_URL` per deployment multi-instance.
- Sono presenti test di regressione, CI GitHub Actions e Dependabot.
- Le dipendenze sono fissate a versioni esplicite.

## Architettura

- `app.py`: navigazione, stato sessione e flusso Streamlit.
- `catalog_service.py`: rotazione HAUL/Vetrina, cronologie, ricerca e timestamp dei dati.
- `ui_components.py`: schede prodotto, CSS, avvisi di prezzo e footer.
- `telemetry.py`: contatori e tempi operativi aggregati in memoria.
- `amazon_api.py`: integrazione catalogo Amazon e fallback legacy.
- `product_dedup.py`: deduplicazione per ASIN/modello/varianti.
- `shared_results.py`: cache condivisa nel processo con stale fallback.
- `api_budget.py`: budget/pacing API, Redis opzionale e SQLite fallback.
- `visitor_limit.py`: limite ricerche per browser, Redis opzionale e SQLite fallback.

## HAUL

`catalog_service.get_haul_selection()` separa due concetti:

1. il pool HAUL viene recuperato e condiviso per un breve TTL;
2. la selezione dei 10 prodotti avviene dopo, usando il token della sessione e gli ASIN già visti.

In questo modo un click su “Mostrami altri 10” non riutilizza semplicemente la selezione condivisa precedente. Se il pool Amazon non contiene abbastanza prodotti nuovi, l'app può riutilizzare elementi precedenti senza duplicarli nella stessa selezione.

## Vetrina

La Vetrina usa pool condivisi per categoria e campionamento per sessione. La cache riduce le chiamate mentre il refresh dell'utente modifica realmente la selezione quando il catalogo disponibile lo consente.

## Ricerca

La ricerca continua a privilegiare Creators API tramite `amazon_api.py`. I risultati vengono deduplicati, ordinati localmente e caricati a blocchi di 10 fino al limite configurato. “Più venduti” usa, nell'ordine, acquisti mensili quando disponibili, sales rank e posizione Amazon come fallback.

Per massimizzare la conformità e la stabilità, in produzione è consigliato configurare la modalità Amazon autorizzata prevista dal proprio account e ridurre/evitare i fallback HTML quando non necessari. Il fallback web presente in `amazon_api.py` è mantenuto come compatibilità legacy e resta soggetto a cambi di markup, blocchi anti-bot e condizioni del Programma di Affiliazione.

## Prezzi e contenuti Amazon

Le schede mostrano un prezzo soltanto quando il dato è marcato come verificato. Accanto alla scheda viene mostrato l'orario di aggiornamento e viene resa visibile l'informativa secondo cui prezzi e disponibilità possono cambiare e fanno fede i dati mostrati su Amazon al momento dell'acquisto.

Le promozioni HAUL non sono più codificate nell'interfaccia come percentuali/soglie permanenti: l'app invita a verificare condizioni e promozioni direttamente su Amazon.

Questa implementazione riduce il rischio di informazioni promozionali obsolete, ma non sostituisce una verifica legale/contrattuale periodica delle politiche Amazon e del GDPR.

## Privacy

Il componente `browser_identity` salva in `localStorage` un UUID casuale con data di creazione e lo rigenera dopo 90 giorni. Il server salva solo l'hash SHA-256 dell'identificatore insieme agli eventi di ricerca necessari al limite orario. Gli eventi più vecchi di 60 minuti vengono eliminati automaticamente dal flusso del limiter.

L'informativa privacy è accessibile dal footer. Il titolare deve verificare che i contatti, l'hosting, i tempi reali di conservazione dei log e gli eventuali servizi terzi corrispondano alla propria configurazione effettiva.

## Stato condiviso e scaling

Per una singola istanza è disponibile il database SQLite `.runtime/api_usage.sqlite3`.

Per più istanze configurare:

```bash
REDIS_URL=redis://utente:password@host:6379/0
```

Con Redis, budget API e limite visitatore possono condividere lo stato tra repliche. Se Redis non è configurato, viene usato SQLite. `SCALA_STATE_DB` permette di spostare il file SQLite su un volume persistente condiviso, anche se Redis resta la soluzione consigliata per deployment multi-instance.

## Secrets Amazon

Configurare i valori nella sezione `amazon_api` dei secrets Streamlit, senza inserirli nel repository. I principali campi sono:

- `partner_tag`
- `credential_id`
- `credential_secret`
- `credential_version`
- `daily_request_budget`
- `request_interval_seconds`
- `searches_per_hour`
- `data_source_mode`

`.streamlit/secrets.toml`, `.env`, `.runtime/` e file SQLite sono ignorati da Git.

## Installazione

```bash
python -m pip install -r requirements.txt
streamlit run app.py
```

## Test

```bash
python -m compileall -q .
pytest -q
```

La CI esegue compilazione e test su Python 3.12. Dependabot controlla settimanalmente dipendenze Python e GitHub Actions.

## Metriche operative

`telemetry.py` registra in memoria contatori e tempi per HAUL, Vetrina e ricerca. I log applicativi possono essere collegati al sistema di osservabilità dell'hosting. Le metriche da seguire in produzione includono:

- tempo caricamento HAUL;
- tempo caricamento Vetrina;
- durata ricerca;
- refresh riusciti/falliti;
- errori/budget non disponibile;
- numero di ASIN nuovi rispetto alla cronologia della sessione.

## Nota sull'affiliazione

In qualità di Affiliato Amazon il titolare riceve un guadagno dagli acquisti idonei. Prezzi, disponibilità, promozioni e condizioni possono cambiare; fanno fede le informazioni mostrate su Amazon al momento dell'acquisto.
