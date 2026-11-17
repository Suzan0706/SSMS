# ADR 0022: 3NF is enforced by a test, with written exceptions

- **Status:** Accepted
- **Date:** 2026-10-31

## Context

The rule "3NF" lived only in a document, and an audit found columns that could be derived from others. Reviews alone do
not stop a redundant column from being added under time pressure.

## Decision

Remove what can be derived. Where a copy must stay because the row can exist without the link, use a composite foreign key
so the database refuses a disagreement. `tests/test_normalisation.py` scans the live catalog for columns reachable through
another foreign key and for names that suggest a stored calculation; each exception needs a written reason in the test.

## Consequences

A new redundant column fails the build. The scan is a heuristic: it finds foreign-key paths and names, not every possible
dependency in free text, so review still matters. Composite keys add a few extra unique indexes. Stale exceptions also fail,
so the list stays accurate.
