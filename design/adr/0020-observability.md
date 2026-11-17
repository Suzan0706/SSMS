# ADR 0020: Metrics by route template, scrubbed error reports, JSON logs

- **Status:** Accepted
- **Date:** 2026-10-27

## Context

NFR-13 asks for alerts on 5xx rate, slow callbacks and queue size, and for logs that can be searched by request.
Schools' data is personal data (PDPA 2022): error reports must not carry it to a third party.

## Decision

The request middleware records `ssms_http_requests_total{method,route,status}` and
`ssms_http_request_seconds{method,route}` with the **route template** (never the raw path, which holds ids). Several
uvicorn workers share counters through `PROMETHEUS_MULTIPROC_DIR`. `/metrics` lives on the API's internal port, is
not proxied by Nginx, and can require a bearer token. Logs are one JSON object per line with the request id.
Sentry is optional; events lose request bodies, cookies, query strings, authorization, signature and device-key
headers, and user data before they leave. Sample Prometheus scrape and alert rules ship in `ssms/ops/`.

## Consequences

Dashboards and alerts work without code changes per route; no personal data in metrics or error reports. Business
metrics (SMS credit, open privacy requests) stay on the school dashboards, not in Prometheus.

## Evidence

`app/core/observability.py`, `app/core/middleware.py`; `tests/test_observability.py`; `design/18-operations.md`.
