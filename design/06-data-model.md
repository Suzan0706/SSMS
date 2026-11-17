# 6. Data Model — DDL Notes

The executable design consists of three parts:

- [sql/schema.sql](sql/schema.sql): PostgreSQL 16+, 99 tables, 10 views, 23 functions, 6 resolvers;
- [sql/seed.sql](sql/seed.sql): two schools;
- [sql/tests/](sql/tests/): 43 database tests.

This section explains the rules the DDL follows and why. Phase 1 turns the file into the Alembic baseline migration, as was done for version 1.

## 6.1 Load order and roles

| Step | Runs as | What |
|---|---|---|
| 1 | superuser (once per cluster) | Section 0 of `schema.sql`: roles `ssms_owner`, `ssms_app`, `ssms_resolver`, `ssms_platform`, `ssms_reporting`; `btree_gist` extension |
| 2 | `SET ROLE ssms_owner` (inside the file) | Every table, view, trigger and function, so the owner is not a superuser and FORCED RLS applies to it too |
| 3 | superuser (`RESET ROLE`, end of file) | Resolver ownership → `ssms_resolver`; column-level grants for resolvers; grants for runtime roles |
| 4 | `ssms_owner` | `seed.sql`: one transaction per school with `SET LOCAL app.school_id` |
| 5 | `ssms_app` | API and Celery at runtime; tests in `sql/tests/` |

`ssms_app` gets SELECT/INSERT/UPDATE on business tables, and DELETE only on the housekeeping tables (`otp_codes`, `refresh_tokens`, `idempotency_keys`, `notifications`). It has no UPDATE on ledgers, journals, frozen results or `audit_logs`, and no access to `platform_admins`. Everything else is soft-deleted with `deleted_at`.

## 6.2 Table conventions

| Rule | Implementation |
|---|---|
| Identity | `id UUID PRIMARY KEY DEFAULT gen_random_uuid()`. The API generates time-ordered UUIDv7 (better B-tree locality); the default is a fallback. |
| Tenant column | `school_id UUID NOT NULL REFERENCES schools` on all 94 tenant tables, plus `UNIQUE (school_id, id)` on each, which is the target of composite FKs. |
| Composite FKs | `FOREIGN KEY (school_id, student_id) REFERENCES students (school_id, id)`. A row cannot reference another school's row (test I07). |
| Audit columns | `created_at`, `updated_at` (trigger `fn_touch_updated_at` on every table), `created_by` (composite FK → `users`, added by a loop). |
| Soft delete | `deleted_at` on master data. Uniqueness is enforced with partial unique indexes `WHERE deleted_at IS NULL`. There is no `deleted_at` on ledgers, logs, frozen results or allocations. |
| Enumerations | `VARCHAR + CHECK`, which is easier to migrate than native ENUMs. |
| Money | `NUMERIC(14,2)` TZS; never float. |
| Time | `DATE`, `TIME`, `TIMESTAMPTZ` (UTC) only; `timerange` (custom range over `time`) for timetable clash checks. |
| Phones | Validated as `255XXXXXXXXX` by the API before encryption; the school office phone (not personal data) has a CHECK. |
| Bilingual labels | `name_en` / `name_sw`, `remark_en` / `remark_sw`, templates per `language`. |

## 6.3 Multi-tenancy rules

1. **RLS on every tenant table**, ENABLED and FORCED, with one policy each: `USING (school_id = app_school_id()) WITH CHECK (school_id = app_school_id())`. `schools` uses `id = app_school_id()`.
2. **`app_school_id()`** reads `current_setting('app.school_id', true)`. It is unset → NULL → no rows (test I02).
3. **Per-transaction context.** The API runs `SET LOCAL app.school_id`, `app.user_id`, `app.client_ip` and `app.request_id` at the start of each transaction (SQLAlchemy `after_begin` hook, as in version 1). Celery tasks do the same per job.
4. **Views use `security_invoker = true`**, so they obey the caller's RLS; a normal view would run as its owner.
5. **Global uniqueness only where the identifier is external or random:** `schools.code`, `gepg_bills.bill_ref` and `control_number` (needed to route callbacks), `refresh_tokens.token_hash`, `devices.api_key_hash`. Everything else, including `payments (school_id, channel, external_ref)` and `rfid_cards (school_id, token_hash)`, is unique per school (F3, test I10).
6. **Resolvers** (section 18 of the schema) are the only cross-tenant reads; see [15-security.md](15-security.md#153-row-level-security-and-resolvers).

## 6.4 Encryption of personal data (PDPA 2022)

| Data | Column(s) | Method |
|---|---|---|
| Phone numbers | `users.phone_enc`, `phone_hash`, `phone_last4`; `sms_messages.to_phone_enc`; `payments.payer_phone_hash/last4` | AES-256-GCM in the application (key from the secret store, versioned key id in the ciphertext header); HMAC-SHA256 blind index with a separate key for exact lookup (login, duplicates); last 4 digits for display |
| NIDA | `students.nida_enc/hash` (optional for minors), `guardians.nida_enc/hash` | same |
| Birth certificate (RITA) | `students.birth_cert_no_enc/hash` | same; unique per school by hash |
| Health notes | `health_records.notes_enc` | same; `health.read` permission + consent |
| Passwords | `users.password_hash`, `platform_admins.password_hash` | Argon2id (pwdlib) |
| Tokens | `refresh_tokens.token_hash`, `otp_codes.code_hash`, `devices.api_key_hash`, `rfid_cards.token_hash` | SHA-256; the raw value is never stored |

Ciphertext never leaves the API layer in clear form. Audit rows drop every `*_enc` and `*_hash` key and `password_hash` (`fn_redact`, test F9b). Key rotation re-encrypts in a background job using the key id in the header. The seed uses **fake bytes** (`0xFA4E…`) and an unkeyed SHA-256 stand-in.

## 6.5 Normalisation (3NF)

- **1NF.** Atomic columns; no lists in text (qualifications, stops, installments and combination subjects are rows).
- **2NF.** Association tables (`class_subjects`, `combination_subjects`, `student_guardians`, `role_permissions`, `teaching_assignments`) have no partial dependencies.
- **3NF.** No transitive dependencies:
  - a mark's term comes from its component;
  - a student's class and year come from the enrolment's stream;
  - `best_n_subjects` sits on the scheme, not on each division rule;
  - SMS credit balance is a view (`v_sms_credit_balance`);
  - installment status is a view (`v_installment_status`);
  - student type (primary/secondary) is derived from the class level.
- **Derived, never stored:** a transport assignment's route comes from its stop; a lesson session's stream from its
  timetable slot; a reconciliation run's matched and exception counts from its items.
- **Copies tied to their source by composite foreign keys:** an enrolment and its application (student, year), a hostel
  allocation and its request (student, term), a bank confirmation and its payment (student, amount), a reversal request
  and its reversal (payment). The rows can exist without the link, so the columns stay; when the link is set the database
  refuses a disagreement. An enrolment's combination may differ from the application's, because students change.
- **Reference tables instead of repeated text:** a school holds `district_id`, and the region comes from the district;
  a room's equipment is rows pointing at one per-school item, so spelling cannot split a search.
- **Automatic guard:** `tests/test_normalisation.py` scans the database. A new column reachable through another foreign
  key, or named like a stored calculation, fails the build until it is removed or given a written reason.
- **Copies kept on purpose (no drift possible or meaning differs):** `result_publications.scheme_version` and all result
  rows (the record as published); `gepg_bills.amount_tzs` (the bill as issued); `reconciliation_runs.system_total_tzs`
  (what the system held at the run); `sms_messages` body and phone (what was actually sent); `users.phone_last4` and
  `phone_hash`, `payments.payer_phone_last4` (searching and display without decrypting); `school_id` on every table
  (tenant isolation, ADR 0001).
- **Controlled, trigger-maintained derived columns** (documented exceptions):
  1. `invoices.total_tzs`, `paid_tzs` and `status` are recomputed from lines and allocations by `trg_invoices_derive` **on every write of the invoice row**, so they cannot drift, and direct overwrites are ignored (test F6a). `balance_tzs` is a generated column. These are kept because parent portals and aging reports read balances far more often than they change.
  2. `invoice_lines.description` and `amount_tzs` are **snapshots** at billing time. A later fee change must not alter an issued invoice.
  3. `published_results` and `student_term_summaries` store computed values on purpose. They are the legal record **as published**, frozen, and versioned through amendments.
  4. `students.status` is the current state; `student_status_history` is its event log. Both are written in one transaction by the service.

## 6.6 Integrity triggers and functions

| Rule | Mechanism | Test |
|---|---|---|
| No teacher, room or stream double-booking | `EXCLUDE USING gist (… WITH =, slot WITH &&) WHERE deleted_at IS NULL` ×3 on `timetable_slots`; ×2 on `exams` | T01–T03 |
| Back-to-back periods allowed | `slot = timerange(start, end, '[)')` | T04 |
| One enrolment per student per year | `UNIQUE (school_id, student_id, academic_year_id)` | T05 |
| One open application per student per year | partial unique index | — |
| One absence SMS per student per day | `UNIQUE (school_id, student_id, absence_date)` + SMS `idempotency_key` | T06 |
| Capacity: stream, hostel room, bus, venue seats, library copies | `fn_capacity_guard` (locks the parent row) | T07 |
| Venue bookings do not overlap | EXCLUDE | T08 |
| Score ≤ component max; locked after publish; version + 1 | `fn_mark_entries_guard` | F4a, F4b |
| Weights total 100; no missing marks | `results_firewall()` | F4c |
| Publish atomically; once per class and term | `publish_results()` (SQLSTATE `SS422` when blocked) | F4d, F4e |
| Results frozen; amendments only with approval, maker ≠ checker | `fn_block_change`, `fn_published_result_guard`, `amend_result()`, CHECK | F7a–F7c |
| Every journal balances at commit | deferred constraint triggers `fn_journal_balanced` | F5a–F5c |
| Ledger, allocations, reversals append-only | `fn_block_change` + no UPDATE grant | F5b |
| Invoice totals derived; no cancel after payment | `fn_invoices_derive` | F6a, F6d |
| Allocations: confirmed payment, same student, ≤ balance, ≤ payment | `fn_allocation_guard` | F6b |
| Payments immutable; legal status transitions; reversal by two people | `fn_payments_guard`, `fn_payment_reversal_apply`, CHECK | F6c |
| Receipts: only PDF key and SMS time may be filled later | `fn_receipts_guard` | — |
| Gapless per-school numbers | `next_document_no()` (`INSERT … ON CONFLICT DO UPDATE … RETURNING`, row lock to commit) | seed |
| Audit every change with actor, request id, redaction | `fn_audit_row` on 31 tables; `audit_logs` statement trigger blocks UPDATE/DELETE/TRUNCATE | F9a–F9c |

## 6.7 Views

| View | Purpose |
|---|---|
| `v_current_results`, `v_current_term_summaries` | Latest version of each frozen result/summary (amendments) |
| `v_component_weight_totals` | Weight totals per term, level, subject (firewall, setup screen) |
| `v_payment_unallocated` | Unallocated part of each confirmed payment (student credit) |
| `v_student_fee_position` | Outstanding balance and credit per student |
| `v_installment_status` | Installments covered in due order: PAID / DUE / OVERDUE |
| `v_invoice_aging` | Aging buckets NOT_DUE, 1–30, 31–60, 61–90, 90+ |
| `v_chronic_absence` | Students absent ≥ 3 register days in an ISO week |
| `v_stream_occupancy` | Enrolled vs capacity per stream and year |
| `v_sms_credit_balance` | SMS credits left per school |

## 6.8 Indexing for scale

- **Tenant-first composite indexes.** Every unique and lookup index starts with `school_id` (e.g. `(school_id, status, due_date)` on invoices), so one school's queries never scan another's data.
- **Partial indexes for hot filters:** unread notifications, open library loans, active enrolments, active cards, queued SMS.
- **BRIN** on `audit_logs.occurred_at`; the table can be partitioned by month when it passes ~50 M rows (ADR in Phase 6).
- **Results day.** Parent portals read `v_current_term_summaries` and `published_results` by `(school_id, enrolment_id)`; the indexes `ix_published_results_enrolment` and `uq_sts_original` make that an index-only lookup. Report cards are pre-rendered PDFs in object storage. See [11-architecture.md](11-architecture.md#114-results-day-and-scale).
