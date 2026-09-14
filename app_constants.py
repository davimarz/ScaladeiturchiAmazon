from __future__ import annotations

SORT_PRICE = "Prezzo minimo"
SORT_POPULAR = "Più venduti"
SORT_OPTIONS = (SORT_PRICE, SORT_POPULAR)
SORT_TO_API = {SORT_PRICE: SORT_PRICE, SORT_POPULAR: "Quantità vendite"}

# Una sola fonte per le dimensioni UI/catalogo.
DISPLAY_BATCH_SIZE = 3
SEARCH_PAGE_SIZE = DISPLAY_BATCH_SIZE
# Recupera due pagine per richiesta ma continua a mostrarne 3 alla volta.
SEARCH_PREFETCH_SIZE = DISPLAY_BATCH_SIZE * 2
SEARCH_DETAIL_RECOVERY_LIMIT = DISPLAY_BATCH_SIZE
SEARCH_COOLDOWN_SECONDS = 5
# "Carica altri" appartiene alla stessa ricerca dell'utente: il budget Amazon
# resta separato e continua a limitare le chiamate al provider.
LOAD_MORE_COUNTS_AS_USER_SEARCH = False

# Il percorso Creators API rimane sempre prioritario. Dopo un 403
# AssociateNotEligible il fallback è temporaneo e il primary viene ritentato
# automaticamente dopo un'ora.
CREATORS_PRIMARY_RETRY_SECONDS = 60 * 60

CACHE_SCHEMA_VERSION = 8
SHOWCASE_DETAIL_CACHE_TTL = 15 * 60
SHOWCASE_DETAIL_STALE_FOR = 60 * 60
SHOWCASE_DETAIL_ENRICH_TIMEOUT = 7.0
PRICE_FRESHNESS_SECONDS = 30 * 60
TELEMETRY_LOG_EVERY_EVENTS = 50

SUGGESTED_SEARCHES = (
    "Cuffie bluetooth",
    "Casa e cucina",
    "Smartwatch",
    "Scarpe running",
    "Cura persona",
    "Accessori smartphone",
)
