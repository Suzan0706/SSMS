# ADR 0021: Data-subject "delete" anonymises and keeps legal records

- **Status:** Accepted
- **Date:** 2026-10-27

## Context

PDPA 2022 gives people the right to erasure, but the school must keep financial records (ledger, receipts) and
published results, and other people's records point to the same rows (a guardian's payments, a class's positions).

## Decision

A DELETE request is completed by `POST /data-subject-requests/{id}/anonymise`: names become "Aliyefutwa #<tag>",
date of birth, phone, e-mail, username, password, refresh tokens, birth-certificate/NIDA numbers, photo, address
and occupation are removed, consents are withdrawn, the person stops receiving SMS, and health notes are destroyed.
Ledgers, receipts, invoices, attendance and published results stay, now pointing at an anonymous person. Active staff
cannot be anonymised (end the employment first), nor can the officer anonymise themselves. Every step is audited.
EXPORT requests produce one JSON file of what the school holds; requests are due in 30 days (VERIFY).

## Consequences

Totals, positions and the books stay correct; the person is no longer identifiable from the school's data. Backups
still contain the old data until they expire (14 days nightly; document this in the reply to the person).

## Evidence

`app/services/privacy.py`; `tests/test_analytics.py::test_data_subject_requests`.
