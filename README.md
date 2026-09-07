# Scala dei Turchi — applicazione Amazon

## Versione corrente

Applicazione Streamlit con HAUL, Vetrina e ricerca di prodotti Amazon. Questa documentazione descrive esclusivamente il comportamento attuale.

### HAUL e Vetrina

- HAUL: selezione condivisa per 60 secondi dal caricamento completato. Un refresh prima della scadenza riutilizza i prodotti. Recupero dalla pagina web HAUL.
- Vetrina: selezione condivisa per 600 secondi, aggiornata alla prima visita dopo la scadenza. Non esiste un job che interroga Amazon senza visitatori.
- Un solo caricamento per chiave nel processo. Gli altri visitatori attendono al massimo 20 secondi; poi ricevono eventuali schede precedenti o nessun risultato.
- Dopo un errore: pausa di 30 secondi prima di riprovare. Schede precedenti conservate al massimo 15 minuti dopo la scadenza, senza prezzo e sconto. La selezione nuova può coincidere con la precedente se il catalogo è limitato.

### Ricerca

- Creators API prima scelta; fallback web in modalità hybrid. La cache completa dura 10 minuti, distinta per termini, filtri, ordinamento, quantità e ASIN esclusi.
- Cerca e Carica altri 10 consumano un tentativo del limite personale. Pagina 1/Pagina 2 e ordinamento locale non consumano richieste personali.
- I risultati API vengono cercati fino al limite di 10 pagine. Il recupero HTML prosegue fino al target con al massimo 5 pagine e 50 candidati pertinenti, con controllo del tempo tra i batch a 90 secondi. Le operazioni già in corso possono terminare oltre tale tempo.
- Un elenco parziale indica solo i prodotti recuperati, non l'intero catalogo. Mancanza di risposte, filtri e budget possono impedire di raggiungere il target.
- La pertinenza è un controllo lessicale conservativo con alcuni sinonimi. Non è un classificatore universale. Una ricerca di marchio non viene limitata a una sola categoria. La parola offerte non disattiva il controllo del marchio.

### Prezzi e Prime

- Prezzo API dalla stessa offerta selezionata; prezzo web verificato nel dettaglio. Sconto calcolato solo da una coppia di prezzi confrontabili. Se il prezzo barrato del widget è ambiguo, viene omesso.
- Il prezzo di riferimento non prova un precedente prezzo storico. Variante, destinazione, abbonamento e condizioni Amazon possono influenzare quanto appare al cliente.
- Solo prodotti Prime: serve un badge nel blocco consegna del dettaglio. Non basta una citazione nel titolo o nella navigazione. Se non verificabile, il prodotto viene escluso.
- Quando la pagina dettaglio è già stata letta, l'evidenza Prime viene riutilizzata per evitare un secondo download immediato. La verifica può richiedere traffico web aggiuntivo; i selettori potrebbero non riconoscere nuovi layout Amazon.

### Limite personale

10 tentativi negli ultimi 60 minuti, configurabili con searches_per_hour. Il conteggio avviene prima della richiesta e include tentativi senza risultati. I click respinti durante la pausa di 5 secondi non consumano un tentativo.

Il componente locale browser_identity conserva un UUID in localStorage. Il server conserva gli orari recenti in SQLite. Refresh e sessioni dello stesso browser condividono il limite; cancellare i dati del sito o cambiare browser può aggirarlo. Non è autenticazione personale.

Continua su AMAZON nella ricerca appare solo al limite. Il controllo di scadenza ogni 15 secondi mentre Cerca è attiva non chiama Amazon. Se browser storage o database non sono disponibili, nuove ricerche personali non partono.

### Budget globale e hosting

- daily_request_budget: 800 tentativi catalogo al giorno UTC per impostazione predefinita, inclusi retry. È una soglia locale, NON la quota reale assegnata da Amazon. Configurarla con margine rispetto alla propria quota.
- request_interval_seconds: minimo 1,1 secondi tra prenotazioni. Attesa massima di 5 secondi per il turno API.
- Il database .runtime/api_usage.sqlite3 richiede disco scrivibile e persistente. Non eliminarlo per azzerare i contatori. OAuth ha limiti separati dal budget catalogo.
- Cache in memoria condivisa nello stesso processo. Contatori condivisi tra processi solo se usano lo stesso database. Per repliche con dischi separati occorrono cache e contatori centralizzati; non è una configurazione multi-server pronta.
- Ispezione contatore: python api_budget.py --limit 800. Usare il limite configurato. I log tecnici restano sul server.

### Configurazione e installazione

Caricare tutti i file e le sottocartelle dello ZIP. Avvio: streamlit run app.py. Installare requirements.txt. Conservare le proprie credenziali nei Secrets; secrets.example.toml non contiene credenziali utilizzabili.

Campi nella sezione amazon_api: partner_tag, credential_id, credential_secret, credential_version, daily_request_budget, request_interval_seconds, searches_per_hour, data_source_mode.

Modalità hybrid predefinita: recupero web disponibile. api_only disabilita il fallback generale e HAUL; il filtro Prime richiesto rimane una verifica web del dettaglio. Il vecchio enable_html_fallback viene ignorato. application_id resta un campo descrittivo, non viene inviato per ottenere il token.

### Diagnostica

Errori API: operation, http e cause indicano lo stadio fallito. Risposte esterne ricevute non equivalgono a prodotti estratti. HTTP 202 è pending; pagine riconosciute come verifica/consenso vengono scartate. Non vengono salvati token, payload OAuth o HTML integrale nei log.

Un risultato vuoto non viene segnalato come un generico ValueError. Se tutte le fonti falliscono, il programma non inventa schede o prezzi.

### Verifiche e limiti

Sintassi e test locali su cache, concorrenza, quote, recupero progressivo, pertinenza, prezzi, Prime e diagnostica. HTTP e Streamlit sono simulati nei test: non equivalgono a una verifica end-to-end dell'interfaccia o dell'account Amazon. Prestazioni reali, persistenza del disco e localStorage devono essere verificati sul deployment effettivo. Non viene garantita accessibilità di Amazon dal server hosting.


### Avvio dal prezzo crescente

Ogni click su Cerca reimposta Prezzo minimo. Creators API usa Price:LowToHigh; tutte le varianti di ricerca web Amazon usano s=price-asc-rank. Anche il collegamento di ricerca diretto su Amazon richiede questo ordinamento. Rimane possibile riordinare localmente per quantità vendite dopo la ricerca. Le fonti esterne non garantiscono l'ordine globale Amazon: in quel caso sono ordinati soltanto i prezzi dei prodotti recuperati. Prezzi ignoti in fondo, senza promettere il minimo assoluto del catalogo o includere automaticamente le spese di spedizione.
