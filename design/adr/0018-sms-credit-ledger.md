# ADR 0018: SMS credit as an append-only ledger

- **Status:** Accepted
- **Date:** 2026-10-23

## Context

Schools buy SMS bundles; every message costs its segment count (FR-66). Without a rule, a school without credit
either sends at the platform's cost or silently loses messages, including sign-in codes.

## Decision

`sms_credit_transactions` is append-only (UPDATE revoked): TOPUP by the platform console, DEBIT when a message is
queued (one per message), REFUND when the provider refuses it for good. The balance is the view
`v_sms_credit_balance`, always filtered by school. Queueing takes a per-school advisory lock, so two senders cannot
spend the same credit. Without enough credit a message is stored as SKIPPED (`no_credit`) and never sent — except
sign-in codes and new-account passwords, which may take the balance below zero. Announcements check the full cost
first and are refused (422) instead of half-sent. Falling below 100 credits notifies users with `sms.manage`.

## Consequences

Every credit movement is explained by a row; schools see why a message was not sent. Delivery failures reported
later by the provider are not refunded (the provider charges them).

## Evidence

`app/services/sms.py`; `tests/test_sms_alerts.py`, `tests/test_communication.py`.
