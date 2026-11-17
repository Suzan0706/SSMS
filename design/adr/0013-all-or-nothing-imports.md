# ADR 0013: Bulk imports are validated completely and written all-or-nothing

- **Status:** Accepted
- **Date:** 2026-10-22

## Context

Schools import hundreds of students from Excel. Partial imports leave duplicates and confusion when the file is fixed and uploaded again.

## Decision

The job validates every row (field rules shared with the API, classes, duplicates in file and school, stream capacity) before writing. Any error produces an XLSX error report and nothing is written; otherwise all rows are written in one transaction. Uploads require an Idempotency-Key.

## Consequences

Re-uploading a corrected file is always safe; a 2000-row file holds one transaction for a few seconds.

## Evidence

`app/services/imports.py`; `tests/test_imports.py`.
