# Compliance checklist

This file is an engineering checklist, not legal advice or legal certification.

## Amazon Associates

Review the current Amazon.it Associates Operating Agreement and Program Policies before each production release:

- https://programma-affiliazione.amazon.it/help/operating/agreement
- https://programma-affiliazione.amazon.it/help/operating/policies

Current implementation safeguards:

- the affiliate disclosure remains visible in the footer;
- price cards show an update timestamp;
- a price/availability change disclaimer is shown near product listings;
- the interface no longer hard-codes HAUL discount percentages or shipping thresholds as permanent facts;
- affiliate links point to Amazon.it, use HTTPS and carry `rel="sponsored"`;
- missing/unverified prices are shown as “Prezzo da verificare su Amazon” instead of being inferred;
- “Più venduti” is described as a popularity indicator and not as an exact sales count.

### Product content source

Creators API is the preferred source in `amazon_api.py`. Legacy HTML fallback remains isolated for resilience and HAUL discovery. Because Amazon can change both technical access rules and contractual requirements, the deployment owner must verify that each enabled fallback is permitted for the account and intended use. Disable non-authorized fallback modes in production if required by the current Program Policies.

## GDPR / privacy

Engineering controls included in this revision:

- no account, name or email is required for ordinary searches;
- the browser identifier is random and expires after 90 days;
- the server stores a SHA-256 hash of the identifier rather than the raw UUID;
- search-event rows older than 60 minutes are removed by the rolling limiter;
- the privacy page documents purpose, retention, recipients, rights and affiliate behavior;
- browser messaging validates the parent window and targets the parent origin derived from the embedding page when available.

The deployment owner must still verify:

- the real hosting provider and subprocessors;
- actual server-log retention;
- a valid privacy contact channel;
- any analytics/cookie tools added outside this repository;
- international transfers, if any;
- whether a cookie/consent banner becomes necessary after adding optional tracking technologies.

## Release review

Before deploying:

1. Run `python -m compileall -q .` and `pytest -q`.
2. Verify the Amazon affiliate tag on rendered links.
3. Verify price timestamps and disclaimer visibility on desktop and mobile.
4. Test HAUL refresh repeatedly and confirm new ASINs are preferred until the pool is exhausted.
5. Test keyboard focus, 200% zoom and small-screen layout.
6. Confirm secrets are absent from git history and logs.
7. Confirm Redis is configured if more than one application instance is running.
8. Re-check the current Amazon Program Policies for material changes.
