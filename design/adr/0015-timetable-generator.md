# ADR 0015: Synchronous timetable generator with a default bell schedule

- **Status:** Accepted
- **Date:** 2026-10-23

## Context

Schools need a usable first timetable quickly; the design proposed a background job and had no table for periods.

## Decision

Most-constrained lessons first (fewest suitable rooms, busiest teachers), each subject spread over the week, one repair move when a lesson does not fit; existing slots are respected unless `replace`. The draft is returned in the same request; `persist=true` saves it in one transaction where the three EXCLUDE constraints are the final check. The grid is Monday–Friday, nine 40-minute periods (VERIFY per school).

## Consequences

Fast enough for whole schools (64 lessons in tens of milliseconds); it is not an optimiser, so complex schools may still adjust by hand; unplaced lessons are reported with a reason.

## Evidence

`app/services/timetable.py`; `tests/test_timetable.py::test_generator_fills_two_streams_without_clashes`.
