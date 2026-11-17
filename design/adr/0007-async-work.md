# ADR 0007: Fast acknowledgements, Celery for slow work, dispatch after commit

- **Status:** Accepted
- **Date:** 2026-10-22

## Context

Payment callbacks must be answered in under 2 s; imports, PDFs and SMS can take minutes and must retry.

## Decision

Requests store the work and return (202 + job). Celery tasks are idempotent, retry with exponential backoff and jitter, and are acknowledged late. Tasks are dispatched only after the creating transaction commits. Development and E2E may run tasks inline (`SSMS_TASKS_INLINE`, refused in production).

## Consequences

Workers can crash or repeat a job safely; there is a short delay between request and result.

## Evidence

`app/tasks/`, `app/services/imports.py::run_job`; `tests/test_imports.py`, `tests/test_auth.py::test_sms_task_sends_once`.
