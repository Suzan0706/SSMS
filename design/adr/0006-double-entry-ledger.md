# ADR 0006: Double-entry ledger with a deferred balance check

- **Status:** Accepted
- **Date:** 2026-10-22

## Context

Bursars reconcile GePG, mobile money, bank and cash; auditors need balanced books.

## Decision

Every money event writes a journal with ledger lines; a DEFERRABLE INITIALLY DEFERRED trigger checks debits = credits at commit. Ledger rows are append-only; mistakes are reversed, never edited.

## Consequences

Reconciliation and audit are straightforward; writes cost a few extra rows.

## Evidence

`schema.sql` §15; integrity tests F5*. (Phase 3 builds the API.)
