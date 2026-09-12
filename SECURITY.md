# Security

## Secrets

Do not commit Amazon credentials, Redis URLs, tokens, Streamlit secrets or `VISITOR_HASH_SECRET`. Use the hosting provider's secret store. `.streamlit/secrets.toml`, `.env` and runtime databases are ignored by Git.

Rotate credentials immediately if they are ever exposed in commits, logs, screenshots or issue content.

## Runtime controls

- Product links rendered by the UI are restricted to HTTPS `amazon.it` hosts.
- Product images are restricted to known Amazon/CDN HTTPS hosts.
- Dynamic product text is HTML-escaped before rendering.
- External links use `noopener noreferrer`; affiliate links also use `sponsored`.
- Browser visitor identifiers expire after 90 days and are HMAC-SHA256 pseudonymized when `VISITOR_HASH_SECRET` is configured.
- Invalid browser UUID values are rejected before use.
- Search rate limiting and API budget can use shared Redis state with `REDIS_URL`.
- Set `STRICT_REDIS=1` on multi-instance deployments so Redis outages fail closed instead of silently falling back to per-instance SQLite.
- Shared catalog result caching can use Redis (`SCALA_SHARED_CACHE_REDIS=1`, enabled by default when Redis is configured).
- HTML retrieval has timeouts and circuit breakers in `amazon_api.py`.

## GitHub and deployment

- Protect `main` in GitHub so changes require a pull request and a passing `CI` check before merge.
- Keep the Streamlit deploy key read-only unless write access is explicitly required.
- Review repository deploy keys periodically and remove unknown or unused keys.
- CI runs tests, dependency auditing (`pip-audit`) and secret scanning (`gitleaks`).

## Multi-instance deployments

Recommended environment:

```text
REDIS_URL=redis://...
STRICT_REDIS=1
VISITOR_HASH_SECRET=<long-random-secret>
SCALA_SHARED_CACHE_REDIS=1
```

Without Redis the application falls back to SQLite and is intended primarily for a single instance.

## Dependency maintenance

Runtime and development dependencies are separated. Dependencies are pinned. Dependabot checks Python packages and GitHub Actions weekly. Review dependency updates before merging.

## Reporting

Security issues should be reported privately to the repository owner through an available private contact channel rather than by posting credentials or exploit details in a public issue.
