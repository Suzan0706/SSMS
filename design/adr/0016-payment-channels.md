# ADR 0016: Payment channels behind adapters, one ledger path

- **Status:** Accepted
- **Date:** 2026-10-23

## Context

Fees arrive by GePG control number, four mobile wallets, bank deposits and cash. Each channel has its own message
format, and the GePG and aggregator specifications are not public (signature details and codes are VERIFY items).
Callbacks can repeat, arrive out of order, or carry an amount different from the bill.

## Decision

- Each channel is an adapter that only turns a message into a `payments` row: `gepg.py` (signed XML, simulator in
  development), `mobile.py` (one HMAC-signed JSON format through an aggregator), bank deposits (bursar or parent
  reports, bank officer confirms) and cash (bursar). Callbacks insert with `ON CONFLICT DO NOTHING` on
  `(school_id, channel, external_ref)`, so a repeat is answered but never paid twice.
- One service, `payments.process`, does the rest for every channel in one transaction: allocate (the bill's
  invoice first, then oldest due, remainder to credit), post the balanced journal (clearing account → 1300 / 2100),
  issue the gapless receipt number and queue the receipt SMS. It is idempotent (it stops when a receipt exists).
- Money rows are immutable in the database; a mistake is undone only by an approved reversal (maker-checker) that
  posts the reversing journal.

## Consequences

Adding a channel (for example a bank API) means one adapter and a clearing account, with no change to allocation,
ledger or receipts. Live use still needs the GePG SP certificate and specification and an aggregator contract
(VERIFY items in `gepg.py` and `mobile.py`). Production refuses simulator mode, missing keys and a short webhook
secret.

## Evidence

`app/services/payments.py`, `gepg.py`, `mobile.py`; `tests/test_finance.py::test_gepg_control_number_and_signed_payment`
and the mobile, reversal and reconciliation tests; `tests/finance_helpers.assert_books_balance`.
