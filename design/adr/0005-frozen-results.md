# ADR 0005: Published results are frozen; changes are amendments

- **Status:** Accepted
- **Date:** 2026-10-22

## Context

Report cards are legal records; silent edits after publication destroy trust.

## Decision

`publish_results()` copies results into frozen tables (UPDATE/DELETE blocked by trigger). A change needs a result amendment approved by a school_admin (maker-checker) and creates a new version.

## Consequences

Full history and auditability; corrections take two people.

## Evidence

`schema.sql` §15.2–15.3; integrity tests F7*. (Phase 2 builds the API.)
