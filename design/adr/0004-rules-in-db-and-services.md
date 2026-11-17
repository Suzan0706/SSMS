# ADR 0004: Business rules enforced in the database and in services

- **Status:** Accepted
- **Date:** 2026-10-22

## Context

Concurrency (two clerks admitting into the last seat) and buggy clients can break rules checked only in Python; rules checked only in SQL give poor error messages.

## Decision

Invariants live in the database (CHECK, EXCLUDE, triggers such as `fn_capacity_guard`); services check the same rules first to return friendly, field-level errors. SQLSTATEs map to one error format.

## Consequences

Rules hold under any client. Some logic exists twice and must change together (drift tests help).

## Evidence

`app/core/errors.py` (`_SQLSTATE`), `app/services/people.py::flush_or_rule` (STREAM_FULL).
