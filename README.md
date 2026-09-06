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


## V17 - velocità, vetrina resiliente e immagini grandi

### Vetrina
- massimo 3 prodotti per apertura più rapida;
- fino a 5 keyword alternative a rotazione;
- si ferma appena trova almeno un prodotto reale;
- fallback generici `offerte amazon` / `offerte del giorno`;
- se un refresh fallisce mantiene la precedente vetrina valida della sessione.

### Ricerca
- verifiche prezzo parallele: 4 -> 8;
- timeout HTML: 8s -> 5s;
- snapshot dettaglio: 75s -> 120s;
- caricamento +10 incrementale invariato;
- circuit breaker 403: 60 minuti invariato.

### Immagini
- mobile: 126x126 -> 100% x 260px, layout verticale;
- desktop: 160x160 -> 190x190;
- preferenza per `data-a-dynamic-image` e `srcset` ad alta risoluzione;
- prima immagine visibile: eager loading + priorità alta.


## V18 - messaggio prezzo non verificato

Il messaggio:
`Prezzo non verificabile con certezza dalla pagina prodotto.`

è stato sostituito con:
`Il prezzo può cambiare frequentemente: verifica quello aggiornato direttamente dal link Amazon.`


## V19 - pagina Amazon HAUL

- nuova prima scheda di navigazione: `HAUL`;
- ordine navigazione: `HAUL -> Vetrina -> Cerca`;
- tre pulsanti forzati su una sola riga anche su smartphone;
- lettura prodotti da `https://www.amazon.it/haul/store`;
- fino a 10 prodotti casuali reali per apertura/refresh;
- il set precedente viene escluso quando il pool HAUL contiene abbastanza
  prodotti differenti;
- se Amazon blocca temporaneamente il fetch, viene mantenuta la selezione
  HAUL valida precedente della sessione;
- immagini ad alta risoluzione e layout mobile V17/V18 mantenuti.

### Condizioni Haul riportate in UI
Sono state usate le condizioni pubblicate ufficialmente da Amazon:
- consegna gratuita da 15 EUR;
- 5% sugli ordini oltre 30 EUR;
- 10% sugli ordini oltre 50 EUR.

Le soglie non vengono presentate come legate al numero di articoli, perché
la documentazione Amazon verificata le esprime in valore dell'ordine.


## V20 - correzione consegna gratuita Amazon Haul

Aggiornata la descrizione HAUL:
- 3 o più articoli: consegna gratuita;
- le percentuali 5% / 10% restano indicate come condizioni promozionali da
  verificare direttamente su Amazon finché non vengono confermate con evidenza
  specifica per 4 e 5 articoli.


## V21 - regole complete Amazon Haul

Aggiornata la descrizione promozionale della pagina HAUL:
- 3 articoli: consegna gratuita;
- 4 articoli: 5% di sconto;
- 5 o più articoli: 10% di sconto.

Resta visibile una nota che invita a verificare le condizioni aggiornate
direttamente su Amazon Haul, perché le promozioni possono cambiare.


## V22 - ricerca Amazon più robusta

Correzioni principali:
- `_search_html_fallback` non è più cacheato come risultato completo:
  un fallimento temporaneo/zero risultati non resta bloccato in cache;
- l'HTML valido continua a essere cacheato normalmente;
- per ogni pagina vengono provate in parallelo 3 forme equivalenti della
  ricerca Amazon (`k`, `i=aps`, `search-alias=aps`);
- parser di emergenza indipendente da `s-search-result` / `data-asin`:
  cerca direttamente i link `/dp/ASIN` e ricostruisce la card dal contenitore;
- titolo recuperabile anche da `aria-label`, attributo `title`, testo link
  o `alt` dell'immagine;
- merge degli ASIN trovati dalle diverse varianti senza duplicati;
- prezzo e verifica detail/corePrice V21 rimangono invariati;
- circuit breaker 403 resta a 60 minuti.

Questo intervento è mirato soprattutto a query comuni come `notebook`,
nelle quali Amazon può servire un markup differente tra una richiesta e l'altra.


## V23 - fetch Amazon resiliente

Integrazione ragionata dei suggerimenti Base44:

- HTML timeout aumentato da 5 a 10 secondi;
- marker CAPTCHA/blocco aggiunti anche in italiano;
- curl_cffi usa `chrome` come fingerprint principale;
- `safari` viene provato soltanto quando Chrome ha ricevuto una risposta
  bloccata/inutilizzabile, non dopo un timeout, per evitare ritardi eccessivi;
- Requests Session resta l'ultimo fallback;
- controllo di sanità della SERP compatibile anche con il parser V22:
  accetta i vecchi marker oppure link `/dp/` e `/gp/product/`;
- log diagnostici con lunghezza HTML, senza credenziali;
- stato pubblico `get_search_diagnostics()` per distinguere fetch bloccato,
  markup non leggibile e reale assenza di risultati;
- messaggio utente differenziato e senza mostrare 403 o dettagli tecnici.

La logica di verifica prezzi corePrice/apexPriceToPay non è stata modificata.


## V24 - ricerca adattiva orientata a 10 prodotti

Strategia nuova:

1. Creators API resta prima scelta, con circuit breaker 403 a 60 minuti.
2. Nel fallback HTML viene richiesta prima una sola URL principale.
3. Se quella URL produce già 10 ASIN unici, non vengono fatte altre richieste SERP.
4. Solo se mancano prodotti vengono scaricate due URL alternative in parallelo.
5. Se la prima pagina non contiene alcun segnale prodotto, viene fatto un solo
   retry controllato dopo 0,8 secondi.
6. Se anche il recovery non vede prodotti, la scansione si ferma invece di
   martellare inutilmente pagine 2/3/4 dello stesso IP bloccato.
7. La discovery raccoglie prima fino a 10 prodotti reali.
8. Solo dopo vengono verificate le pagine dettaglio/prezzi.
9. Le verifiche dettaglio usano massimo 5 worker e timeout 7 secondi, per
   ridurre il rischio di anti-bot rispetto a 8 richieste simultanee.
10. La SERP ha timeout 12 secondi per tollerare latenza Streamlit Cloud.

Obiettivo: massimizzare la probabilità di ottenere i 10 prodotti richiesti
con meno richieste simultanee e una sequenza adattiva, non con brute force.


## V25 - discovery multistadio

Quando Creators API è nel circuit breaker 403, la ricerca segue ora:

1. Amazon Search desktop principale;
2. due varianti desktop solo se servono;
3. Amazon mobile/lightweight `/gp/aw/s`;
4. retry controllato della prima pagina;
5. come ultima risorsa, un indice web esterno viene usato esclusivamente
   per scoprire URL/ASIN `amazon.it`;
6. gli ASIN trovati esternamente vengono poi arricchiti tramite la pagina
   prodotto Amazon: titolo, immagine principale, prezzo e social proof.

La fonte finale dei dati prodotto resta quindi Amazon; la ricerca esterna
serve soltanto a recuperare gli URL quando l'endpoint Search di Amazon è
bloccato dal datacenter Streamlit.

Altre modifiche:
- snapshot dettaglio include ora titolo e immagine principale;
- `#productTitle`, `#landingImage`, `data-old-hires`, dynamic image e OpenGraph
  vengono usati per arricchire schede scoperte senza SERP;
- target sempre 10 prodotti, fermandosi appena raggiunto.


## V26 - ricerca resiliente a 503 / challenge Streamlit

Basata sui log reali del 2026-09-06:
- Amazon Search restituiva HTTP 503 con body ~2 KB;
- alcune risposte HTTP 200 erano shell da ~2.3 KB senza link prodotto;
- DuckDuckGo andava in ConnectTimeout.

Modifiche:
- le pagine Search 200 senza segnali `/dp/`, `data-asin`, ecc. non vengono più cacheate;
- dopo 2 fallimenti Search consecutivi si apre un circuit breaker HTML di 10 minuti;
- mentre il breaker è aperto si saltano desktop/mobile Amazon Search e si passa subito al discovery esterno;
- discovery esterno parallelo: Bing RSS + Google HTML + DuckDuckGo HTML;
- timeout esterno 6 secondi: i tre provider vengono interrogati insieme, non in sequenza;
- parser dei redirect Google/DDG/Bing verso URL `amazon.it`;
- vengono accettati solo ASIN reali estratti da URL Amazon;
- le pagine prodotto Amazon continuano ad arricchire titolo, immagine e prezzo;
- Creators API circuit breaker resta a 60 minuti.
