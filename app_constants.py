from __future__ import annotations

SORT_PRICE = "Prezzo minimo"
SORT_POPULAR = "Più venduti"
SORT_OPTIONS = (SORT_PRICE, SORT_POPULAR)
SORT_TO_API = {SORT_PRICE: SORT_PRICE, SORT_POPULAR: "Quantità vendite"}
DISPLAY_BATCH_SIZE = 4
SEARCH_PAGE_SIZE = DISPLAY_BATCH_SIZE
SEARCH_COOLDOWN_SECONDS = 5
SUGGESTED_SEARCHES = (
    "Cuffie bluetooth",
    "Casa e cucina",
    "Smartwatch",
    "Scarpe running",
    "Cura persona",
    "Accessori smartphone",
)
