# ADR 0012: School onboarding runs in one transaction, not as a job

- **Status:** Accepted
- **Date:** 2026-10-22

## Context

12-api-design proposed returning an onboarding job. The defaults are about 100 rows.

## Decision

Creating a school inserts the school, settings, admin account and all defaults in one transaction on the console (ssms_platform). Only the welcome SMS is queued.

## Consequences

A school is never half-onboarded; the console waits well under a second.

## Evidence

`app/services/platform.py::create_school`, `app/services/onboarding.py`; `tests/test_platform.py::test_create_school_with_defaults_and_first_login`.
