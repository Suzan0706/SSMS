# ADR 0002: SECURITY DEFINER resolvers for lookups before the school is known

- **Status:** Accepted
- **Date:** 2026-10-22

## Context

Login by school code, parent OTP by phone, refresh cookies, device keys and GePG callbacks arrive before any tenant context exists, so RLS would return nothing.

## Decision

Six functions owned by `ssms_resolver` (BYPASSRLS, column-level SELECT only) map an external identifier to ids and nothing else. Only `ssms_app` may execute them. Everything after the lookup runs under RLS.

## Consequences

The bypass is small, reviewable and returns no business data. New pre-tenant entry points need a new resolver and a test.

## Evidence

`schema.sql` §18; `app/services/auth.py`; isolation tests I11–I16.
