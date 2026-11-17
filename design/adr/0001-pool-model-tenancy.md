# ADR 0001: Shared schema, school_id, forced RLS and composite foreign keys

- **Status:** Accepted
- **Date:** 2026-10-22

## Context

SSMS serves hundreds of small schools. A database or schema per school multiplies migrations, connections and backups; most schools have a few hundred students.

## Decision

All schools share one schema. Every tenant table has `school_id`, `UNIQUE (school_id, id)` and composite foreign keys `(school_id, x_id)`. Row-Level Security is ENABLED and FORCED with policy `tenant_isolation` on `app_school_id()`. The API sets `SET LOCAL app.school_id` per transaction from the verified JWT.

## Consequences

Three independent layers stop cross-school access (application filter, RLS, composite FKs). A missing context returns zero rows (fail closed). Very large schools can later move to their own database with the same schema.

## Evidence

`design/sql/schema.sql` §13; `tests/test_people.py::test_other_schools_records_are_not_found`; `design/sql/tests/01_isolation.sql` I02–I10.
