# ADR 0017: Absence alerts only on recorded evidence

- **Status:** Accepted
- **Date:** 2026-10-23

## Context

Guardians must get one SMS when their child is absent (FR-36). The design counted a student as absent when nothing
showed them present. A school that forgets the register, or whose gate reader is down, would then message every
parent of the school at 08:30 — costly, and parents stop trusting the alerts.

## Decision

A student is absent only when the school recorded it: the stream's morning register marks them ABSENT, or the
stream has no register that day while the gate is in use (at least one tap) and the student did not tap. A tap or a
PRESENT, LATE or EXCUSED mark always wins. The job runs every 5 minutes on weekdays and acts between the school's
cut-off and 12:00 (VERIFY), never on weekends, holidays or outside terms. `absence_alerts` (unique per student and
day) and the SMS key `absence:<student>:<date>` make every run safe to repeat; the primary guardian who receives SMS
is the only recipient.

## Consequences

No false mass alerts; a register taken after the cut-off still alerts within 5 minutes until noon. A student absent
from an unrecorded stream on a day without gate use gets no alert, which the attendance reports make visible.

## Evidence

`app/services/alerts.py`; `tests/test_sms_alerts.py::test_absence_alerts`.
