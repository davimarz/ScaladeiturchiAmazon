# Security

## Secrets

Do not commit Amazon credentials, Redis URLs, tokens or Streamlit secrets. Use the hosting provider's secret store. `.streamlit/secrets.toml`, `.env` and runtime databases are ignored by Git.

Rotate credentials immediately if they are ever exposed in commits, logs, screenshots or issue content.

## Runtime controls

- Product links rendered by the UI are restricted to HTTPS `amazon.it` hosts.
- Dynamic product text is HTML-escaped before rendering.
- External links use `noopener noreferrer`; affiliate links also use `sponsored`.
- Browser visitor identifiers expire after 90 days and are SHA-256 hashed before server-side persistence.
- Search rate limiting is fail-safe and can use shared Redis state with `REDIS_URL`.
- API request pacing and daily budget can use the same shared Redis deployment.
- HTML retrieval has timeouts and circuit breakers in `amazon_api.py`.

## Multi-instance deployments

Set `REDIS_URL` for shared counters. Without Redis the application falls back to SQLite and is suitable primarily for a single instance or a deployment where all processes share the same persistent database file.

## Dependency maintenance

Dependencies are pinned. GitHub Actions runs compilation and tests on every pull request, and Dependabot checks Python packages and Actions weekly. Review dependency updates before merging.

## Reporting

Security issues should be reported privately to the repository owner through an available private contact channel rather than by posting credentials or exploit details in a public issue.
