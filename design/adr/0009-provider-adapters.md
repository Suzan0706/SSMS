# ADR 0009: Provider adapters for SMS and payments

- **Status:** Accepted
- **Date:** 2026-10-22

## Context

Tanzanian SMS aggregators and payment channels change prices and APIs.

## Decision

Each provider sits behind a small adapter chosen by configuration (`SSMS_SMS_PROVIDER`: console, beem, nextsms). Provider HTTP details are marked VERIFY until confirmed with the provider.

## Consequences

Switching provider is a configuration change; each adapter needs its own contract test.

## Evidence

`app/services/sms.py`; `tests/test_sms.py`.
