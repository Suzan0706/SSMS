# ADR 0008: Optimistic concurrency for marks, client ids for attendance

- **Status:** Accepted
- **Date:** 2026-10-22

## Context

Teachers enter marks and attendance on weak networks and sync later.

## Decision

Mark entries carry a `version` checked by `fn_mark_entries_guard`; attendance carries a client record id so a re-sent batch is not duplicated.

## Consequences

No lost updates and safe retries; clients must handle version conflicts.

## Evidence

`schema.sql` (mark_entries, attendance_records). (Phases 2 and 4.)
