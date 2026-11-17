# ADR 0014: Report cards are rendered on request; the class bundle is a job

- **Status:** Accepted
- **Date:** 2026-10-23

## Context

Amendments create new result versions at any time. A stored PDF per student would be stale between an approval and the next regeneration, and local storage cannot issue signed URLs.

## Decision

`GET /students/{id}/report-card` renders the PDF (ReportLab, about 3 KB per page) from the current results each time. The REPORT_CARDS job renders the whole class into one printable PDF after publication or an approved amendment, and queues the results SMS once per consenting primary guardian.

## Consequences

Always correct; each download costs a few database reads and ~20 ms of rendering. A CDN cache can be added later keyed on the latest amendment time.

## Evidence

`app/services/report_cards.py`; `tests/test_results.py`; visual check in sw and en.
