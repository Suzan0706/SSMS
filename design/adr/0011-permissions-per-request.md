# ADR 0011: Permissions are loaded on every request (no perm_ver claim)

- **Status:** Accepted
- **Date:** 2026-10-22

## Context

The design draft put a `perm_ver` claim in the JWT to force refresh after role changes. That still leaves up to 15 minutes in which a removed role keeps working, and needs a version counter on every user.

## Decision

The JWT carries only who (sub) and which school (sch). Every request loads the user's status and permissions in one indexed query under RLS. Disabled users and suspended schools are refused at once.

## Consequences

One extra small query per request; revocation is immediate. The `roles` claim is informational only.

## Evidence

`app/api/deps.py::current_principal`; `tests/test_people.py::test_disable_user_and_role_rules`, `tests/test_platform.py::test_suspending_a_school_blocks_its_users`.
