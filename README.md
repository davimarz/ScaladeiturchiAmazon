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


## V7 - correzione ricerca

Problema corretto: il fallback HTML della ricerca con "Prezzo minimo" aggiungeva
il parametro Amazon `s=price-asc-rank`, mentre la Vetrina usava una pagina
standard. Su Streamlit la variante ordinata poteva restituire markup diverso o
non parsabile.

Ora:
- Vetrina e Cerca usano lo stesso recupero HTML standard;
- "Prezzo minimo" viene ordinato localmente dopo l'estrazione;
- se il primo URL HTML produce zero schede, viene provato anche l'URL alternativo;
- è stato eliminato il doppio messaggio "Nessun prodotto trovato";
- il fallback "Quantità vendite" non usa più le recensioni come vendite.


## V8 - ordinamento in tempo reale

- `Prezzo minimo` e `Quantità vendite` sono ora widget fuori dal form.
- Il click sul radio riordina immediatamente tutte le schede già caricate.
- Non viene eseguita una nuova richiesta Amazon quando si cambia ordinamento.
- Se sono stati caricati 20, 30, 40 o 50 prodotti, viene riordinato l'intero set.
- Dopo il cambio ordinamento si torna automaticamente alla pagina 1.
- Per i prodotti API si usa `WebsiteSalesRank` quando disponibile.
- Per il fallback HTML si conserva l'ordine originale Amazon in
  `_amazon_position`, così è possibile ripristinarlo dopo un ordinamento prezzo.


## V9 - feedback quantità vendite
- Mostra `X+ acquistati nel mese scorso` quando Amazon espone il dato.
- La quantità è una soglia minima mensile, non il totale storico.
- Ordinamento Quantità vendite:
  1. quantità mensile decrescente;
  2. WebsiteSalesRank crescente;
  3. ordine Amazon.
- Il cambio ordinamento resta immediato.


## V10 - scroll automatico dopo Carica altri 10

Quando si preme `Carica altri 10 prodotti`:
1. vengono recuperati i nuovi prodotti;
2. `current_page` passa alla pagina appena aggiunta;
3. dopo il rerun Streamlit la pagina scorre automaticamente;
4. lo scroll termina esattamente prima della prima scheda della pagina corrente;
5. il comportamento è one-shot e non si ripete nei rerun successivi.


## V11 - pulsanti paginazione su una sola riga

- I pulsanti P.1, P.2, P.3... restano affiancati orizzontalmente.
- Il layout non viene impilato verticalmente su smartphone.
- Con il limite di 50 prodotti ci sono al massimo 5 pulsanti.
- Se lo spazio fosse insufficiente, il contenitore può scorrere orizzontalmente.
- Cliccando una pagina, lo scroll porta al primo prodotto della pagina scelta.
