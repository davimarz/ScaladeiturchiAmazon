# Changelog

## 2026-09-14 — P2 audit package

- ricerca: “Carica altri” continua la stessa quota utente;
- paginazione mobile Precedente/Successiva;
- navigazione sticky e controlli ricerca adattivi;
- prezzo, provenienza e freschezza separati;
- Prime distingue verifica dettaglio da rilevazione card;
- cache Redis centralizzata e completamente opzionale;
- serializzazione cache Redis stretta, senza conversioni implicite;
- snapshot telemetrici JSON e ratio prezzo/immagine/cache;
- boundary dedicati per HAUL, Vetrina e servizi applicativi;
- CSP e `postMessage` più restrittivi nei componenti browser;
- possibilità di rigenerare l’identificatore locale;
- GitHub Actions pin-nate a SHA;
- Ruff, mypy, CodeQL e test E2E/accessibilità ampliati;
- tema Streamlit centralizzato in `.streamlit/config.toml`.

## 2026-09-14 — P1 audit package

- Creators API primary-first con retry automatico dopo 60 minuti;
- cache dettaglio per ASIN e timeout globale Vetrina;
- separazione navigazione/refresh HAUL e Vetrina;
- ricerca con prefetch 6 e visualizzazione 3;
- stale cache Redis, timestamp prezzo dedicato, lazy loading immagini;
- test Python 3.12/3.14 ed E2E Playwright.

## 2026-09-14 — UI a 3 prodotti

HAUL, Vetrina e Cerca passano a 3 prodotti visibili per volta.
