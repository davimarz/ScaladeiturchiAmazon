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


## V15 - correzione prezzo SERP + verifica dettaglio

È stata integrata la parte valida della proposta Base44:

- il prezzo attuale SERP privilegia `data-a-color="base"`;
- `.a-text-price` è escluso da tutti i selettori del prezzo attuale;
- il prezzo barrato viene cercato solo in `.a-price.a-text-price`
  o `data-a-strike="true"`;
- `old_price` parte da `None`, non dal prezzo finale;
- whole/fraction vengono letti solo dentro il nodo prezzo corrente.

La logica V14/V13 sulla pagina dettaglio resta però prioritaria:
- il prezzo definitivo arriva da `corePrice` / `apexPriceToPay`;
- il prezzo SERP non è mai marcato come verificato;
- se la pagina dettaglio non è verificabile, il prezzo SERP non viene
  mostrato come prezzo certo.

Questa combinazione è più robusta del solo fix SERP.


## V16 - Circuit breaker 403 a 60 minuti

Quando Creators API risponde `403 AssociateNotEligible`, il backend:
- passa subito al fallback HTML;
- non ripete chiamate Creators API per 60 minuti;
- dopo 60 minuti prova automaticamente di nuovo;
- appena una chiamata API torna a rispondere 200, il blocco viene azzerato.
