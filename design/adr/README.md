# Architecture decision records

One file per decision. Status of all records: **Accepted** (2026-10-22).

| ADR | Decision |
|---|---|
| [0001](0001-pool-model-tenancy.md) | Shared schema, school_id, forced RLS and composite foreign keys |
| [0002](0002-resolvers.md) | SECURITY DEFINER resolvers for lookups before the school is known |
| [0003](0003-uuidv7.md) | UUIDv7 generated in the API |
| [0004](0004-rules-in-db-and-services.md) | Business rules enforced in the database and in services |
| [0005](0005-frozen-results.md) | Published results are frozen; changes are amendments |
| [0006](0006-double-entry-ledger.md) | Double-entry ledger with a deferred balance check |
| [0007](0007-async-work.md) | Fast acknowledgements, Celery for slow work, dispatch after commit |
| [0008](0008-offline-concurrency.md) | Optimistic concurrency for marks, client ids for attendance |
| [0009](0009-provider-adapters.md) | Provider adapters for SMS and payments |
| [0010](0010-field-encryption.md) | Application-level encryption with a keyed blind index |
| [0011](0011-permissions-per-request.md) | Permissions are loaded on every request (no perm_ver claim) |
| [0012](0012-synchronous-onboarding.md) | School onboarding runs in one transaction, not as a job |
| [0013](0013-all-or-nothing-imports.md) | Bulk imports are validated completely and written all-or-nothing |
| [0014](0014-report-cards.md) | Report cards are rendered on request; the class bundle is a job |
| [0015](0015-timetable-generator.md) | Synchronous timetable generator with a default bell schedule |
| [0016](0016-payment-channels.md) | Payment channels behind adapters, one ledger path |
| [0017](0017-absence-evidence.md) | Absence alerts only on recorded evidence |
| [0018](0018-sms-credit-ledger.md) | SMS credit as an append-only ledger |
| [0019](0019-facility-fees-on-the-term-invoice.md) | Facility fees go on the term invoice |
| [0020](0020-observability.md) | Metrics by route template, scrubbed error reports, JSON logs |
| [0021](0021-anonymise-not-delete.md) | Data-subject "delete" anonymises and keeps legal records |
| [0022](0022-normalisation-guard.md) | 3NF is enforced by a test, with written exceptions |
