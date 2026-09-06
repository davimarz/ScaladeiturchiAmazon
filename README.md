# Scala dei Turchi – Amazon Streamlit

Web app Streamlit con ricerca Amazon, Vetrina, paginazione e schede prodotto.

## Flusso dati

1. Creators API viene tentata per prima.
2. In caso di `AssociateNotEligible` il backend attiva un circuit breaker di 15 minuti e usa il fallback HTML senza ripetere 403 a ogni ricerca.
3. Il fallback HTML trova ASIN/titolo/immagine.
4. Il prezzo viene verificato sulla pagina dettaglio `corePrice` prima di essere mostrato.
5. `Carica altri 10` recupera solo ASIN nuovi: non rivalida i prodotti già caricati.

## Ottimizzazioni V14

- un solo tentativo `curl_cffi` + un fallback `requests`;
- keep-alive HTTP con Session per thread;
- cache HTML ricerca limitata a 24 pagine;
- cache compatta del prezzo dettaglio (non conserva tutto l'HTML prodotto);
- cache e stato condiviso protetti da lock;
- circuit breaker Creators API dopo 403 `AssociateNotEligible`;
- caricamento incrementale reale di +10 prodotti;
- nessuna riapertura delle pagine dettaglio già caricate;
- prezzo HTML non considerato verificato finché il `corePrice` dettaglio non è stato letto.

## File

- `app.py` – UI e stato Streamlit
- `amazon_api.py` – Creators API + fallback HTML
- `requirements.txt` – dipendenze
- `.gitignore` – esclude secrets/cache/file locali

Le credenziali devono restare nei Secrets di Streamlit Cloud e non nel repository.
