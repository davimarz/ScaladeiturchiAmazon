# Compliance checklist

Questo file è una checklist tecnica e non costituisce consulenza o certificazione legale.

## Amazon Associates

Prima di ogni release di produzione verificare le condizioni correnti del Programma Affiliazione Amazon.it.

Salvaguardie applicative:

- disclosure affiliato sempre visibile nel footer;
- link Amazon HTTPS con Partner Tag e `rel="sponsored"`;
- prezzi mostrati solo da segnali Amazon espliciti e ancora freschi;
- `price_verified_at` è distinto dal semplice timestamp della scheda;
- prezzo precedente e sconto non vengono inventati;
- prezzi non affidabili/scaduti non vengono mostrati come correnti;
- Creators API resta il percorso primary-first;
- dopo `AssociateNotEligible` il fallback è temporaneo e il primary viene ritentato dopo 60 minuti;
- il fallback non elimina credenziali né Partner Tag;
- “Più venduti” resta descritto come indicatore di popolarità, non conteggio esatto delle vendite.

### Fallback HTML

I fallback HTML sono isolati dietro boundary dedicati (`http_client.py`, `haul_parser.py`, `showcase_parser.py`, `amazon_html.py`). Il titolare deve verificare periodicamente che ogni modalità abilitata sia compatibile con le policy applicabili al proprio account. Se necessario usare `data_source_mode="api_only"`.

## GDPR / privacy

Controlli implementati:

- nessun account, nome o email richiesti per le ricerche ordinarie;
- identificatore browser casuale con scadenza 90 giorni;
- possibilità per l’utente di rigenerare l’identificatore dalla pagina Privacy;
- pseudonimizzazione HMAC-SHA256 quando `VISITOR_HASH_SECRET` è configurato, SHA-256 come fallback;
- eventi del limite ricerche eliminati dopo 60 minuti;
- nuovi log diagnostici non includono intenzionalmente il termine di ricerca;
- componenti browser con CSP restrittiva e `postMessage` verso origin verificata;
- Redis è opzionale e non è requisito per la singola istanza.

Il titolare deve comunque verificare hosting, subprocessori, retention reale dei log, contatto privacy e trasferimenti internazionali.

## Release review

1. `python -m compileall -q .`
2. `ruff check --select E9,F63,F7,F82 .`
3. `mypy app_constants.py product_models.py redis_client.py services.py`
4. `pytest -q -m "not e2e"`
5. verificare Partner Tag su link HAUL, Vetrina e Cerca;
6. verificare prezzi/timestamp/disclaimer su desktop e mobile;
7. testare tastiera e zoom 200%/400%;
8. controllare assenza di segreti in Git e log;
9. verificare ruleset `main` e deploy key read-only;
10. ricontrollare le policy Amazon correnti.
