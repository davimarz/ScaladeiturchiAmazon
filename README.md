# Scala dei Turchi - Streamlit Amazon Hybrid

## Flusso prodotti

1. La web app prova prima Amazon Creators API.
2. Se Creators API restituisce abbastanza prodotti, usa esclusivamente quelli.
3. Se Creators API fallisce (incluso HTTP 403 AssociateNotEligible), restituisce
   zero risultati o restituisce meno prodotti del necessario, il backend passa
   automaticamente al fallback HTML.
4. L'utente non vede errori API o pulsanti di fallback: vede soltanto le schede
   prodotto disponibili nella pagina della web app.
5. La ricerca iniziale mostra fino a 10 prodotti; `Carica altri 10` aumenta il
   target fino a 50.

## Dati HTML

Il fallback HTML prova a leggere soltanto dati presenti nella pagina Amazon:
- ASIN
- titolo
- immagine
- prezzo
- eventuale prezzo precedente e sconto calcolato
- presenza Prime

Non vengono inventati recensioni, vendite, prezzi o spedizioni.

## Dipendenze

- Streamlit
- requests
- BeautifulSoup
- curl_cffi

## Nota tecnica

Il fallback HTML è meno stabile dell'API ufficiale e può smettere di funzionare
se Amazon cambia markup o blocca le richieste dal server Streamlit. Creators API
rimane sempre la fonte prioritaria.
