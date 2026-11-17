# ADR 0010: Application-level encryption with a keyed blind index

- **Status:** Accepted
- **Date:** 2026-10-22

## Context

The Personal Data Protection Act 2022 requires protecting phone, NIDA and birth-certificate numbers; database dumps and backups must not reveal them.

## Decision

AES-256-GCM per field (format version | key id | nonce | ciphertext, field name as associated data) and HMAC-SHA256 blind indexes for exact lookups. Keys come from the environment and rotate by key id. Clear values are shown only to roles that need them; identifiers are read through an audited endpoint.

## Consequences

No SQL search by partial phone/NIDA; key loss means data loss (keys must be backed up separately).

## Evidence

`app/core/crypto.py`; `tests/test_core.py::test_field_cipher_round_trip_rotation_and_binding`, `tests/test_people.py::test_identifiers_are_audited`.
