# 17. Summary of Corrections

The corrections are in three groups:

- **17.1** against the original UML/DFD baseline (the "General Use Case" model);
- **17.2** against version 1 of this project (the single-school design in `docs/`, `db/`, `backend/`);
- **17.3** defects found and fixed while building and testing this Phase 0 design.

## 17.1 Against the original baseline model

| # | Baseline | Problem | Correction in SSMS | Where |
|---|---|---|---|---|
| 1 | Students and Instructors inherit from Registrar | A student "is a" registrar and inherits `add()`/`update()` and password fields | Abstract `User` (Person + login) → `Student`, `Guardian`, `Staff`; Teacher, School Admin and Bursar are **roles** of Staff | [08](08-class-diagram.md), `users`, `students`, `staff`, `guardians` |
| 2 | Plain `stud_pass`, `ins_pass` | Plaintext passwords in two tables | One `users.password_hash` (Argon2id); OTP-only parents have no password; audit redacts hashes | [06](06-data-model.md#64-encryption-of-personal-data-pdpa-2022), test F9b |
| 3 | `age` attribute | Wrong after a year | `date_of_birth DATE`; age computed | `users.date_of_birth` |
| 4 | `Schedules.stud_ID` | One schedule row per student per session | `timetable_slots` has no student; students reach slots through `enrolments` (stream + year); EXCLUDE constraints prevent teacher/room/stream clashes | `timetable_slots`, tests T01–T04 |
| 5 | DFD entity "Customer" | Not a school actor | **Student** (and Parent, Bank, Mobile Money, GePG, SMS Gateway, Gate Device added) | [03](03-context-dfd.md) |
| 6 | `Transaction(trans_name, stud_ID, trans_date)` | No amount, method, reference, status or recorder | `payments`: channel (GePG, M-Pesa, Mixx by Yas/Tigo Pesa, Airtel, HaloPesa, bank, cash), `external_ref` unique per school, `amount_tzs NUMERIC(14,2)`, status, `recorded_by`, allocations, receipts, double-entry ledger, reversals by two people | finance tables, tests F5–F6, I10 |
| 7 | Times and dates as strings | No validation or arithmetic | `DATE`, `TIME`, `TIMESTAMPTZ` (UTC), `timerange` for clashes, `NUMERIC` money | all tables |
| 8 | `Subjects.instructor`, `Subjects.schedule` strings; subject in one course | Not normalised | `teaching_assignments`, `timetable_slots`, `class_subjects`, `combination_subjects` (M:N) | [05](05-erd.md#52-academic-configuration-and-enrolment) |
| 9 | Unbalanced DFDs; entities writing directly to stores; Level 1 numbered 1.1–1.4 | Not valid DFDs | Level 0 = union of Level 1 flows with a balancing table; Level 1 numbered 1.0–10.0; Level 2 for 2.0, 4.0, 5.0 checked against their parents; flows only through processes; stores D1–D14 | [03](03-context-dfd.md#34-balancing-table--level-0--level-1) |
| 10 | NIDA required for every person | Minors usually have no NIDA; extra personal data | NIDA optional for students, encrypted where held | `students.nida_enc` (nullable) |
| 11 | Sequence lifelines "Student Information", "Successfully Enrolled"; every lifeline destroyed | Data drawn as objects; servers do not die after one enrolment | Real components (PWA, FastAPI, PostgreSQL, Celery, storage); no destruction | [09](09-sequence-diagrams.md#91-enrolment-corrected-from-the-baseline) |
| 12 | Activity: files saved before checking; all-or-nothing validity; endless loop | Weak validation, bad UX | Type/size/hash checks first; per-document validation with comments; only invalid files re-uploaded; school decides | [10](10-activity-diagrams.md#101-enrolment) |
| 13 | Use cases without «include»/«extend», no parent, no login | Incomplete | 27 use cases, 2 diagrams, include/extend, detailed descriptions | [04](04-use-cases.md) |
| 14 | Typos (Trasactions, Informtion, ChecksStudent, Inqure, Succesfully) | — | Corrected throughout | — |

## 17.2 Against version 1 (single-school design)

| Area | Version 1 | SSMS (version 2) | Why |
|---|---|---|---|
| Tenancy | One school | `school_id` everywhere, forced RLS, composite FKs, resolvers | Many schools on one platform without data leaks |
| Keys | BIGINT/INT identities | UUID (UUIDv7 from the API) | Offline creation, merge-safe, no guessable ids |
| Results | Score stored, grade derived in a view; no freeze | Draft `mark_entries` → firewall → frozen `published_results` and summaries, versioned amendments with maker-checker | Rule 5 (published results immutable); legal record |
| Assessment | Single score per assessment type | Configurable components with max score and weight (must total 100) | Rule in section 5: CA/exam weights must not be hard-coded |
| Grading | One global NECTA table | Versioned schemes per school, level and year; division rules data-driven | Regulations change; schools differ |
| Finance | Invoice balance view; transaction ledger table | Trigger-derived invoice totals, allocations, receipts, **double-entry journals** with deferred balance check, bank confirmations, reconciliation, student credit | Rule 3; auditors; overpayments |
| Payment idempotency | `UNIQUE (payment_method, reference_no)` global | `UNIQUE (school_id, channel, external_ref)` | Two schools may use the same receipt-book number |
| Personal data | Plain phone and NIDA columns | AES-GCM `*_enc` + HMAC blind index `*_hash` + `*_last4`; consent records; DSR table | Rule 9, PDPA 2022 |
| Auth | Password only | Password + parent phone OTP, multi-school selection, httpOnly refresh cookie | Parents on basic phones |
| Roles | 6 fixed roles in a CHECK | Role and permission catalogue, roles per school, generated RBAC matrix | Fine-grained permissions, rule 8 |
| Attendance | Per lesson only | Register (offline), gate RFID/QR devices, absence SMS once per day, chronic-absence view | Section 7.9 |
| Modules | Students, courses, schedules, enrolment, fees | + exams, hostel, transport, venues, discipline, clubs, library, health, announcements, SMS credit, bulk import, background jobs, compliance exports | Section 7 |
| Deletes | Mostly hard | Soft delete (`deleted_at`) with partial unique indexes; no DELETE grant for the runtime role | Recoverability and audit |
| DB roles | `sms_app`, `sms_reporting` (comments only) | `ssms_owner`, `ssms_app`, `ssms_resolver`, `ssms_platform`, `ssms_reporting` created and granted by the schema; tests run as `ssms_app` | Least privilege; RLS proven, not assumed |

## 17.3 Defects found and fixed during Phase 0

| # | Found by | Defect | Fix |
|---|---|---|---|
| D1 | Review (F1) | RLS cannot be proven when tests run as superuser | Five roles; objects owned by `ssms_owner`; tests start with `SET ROLE ssms_app` and assert NOSUPERUSER/NOBYPASSRLS (I01) |
| D2 | Review (F2) | Webhooks, devices, cookies and OTP arrive before the school is known, so RLS returns nothing | Six SECURITY DEFINER resolvers returning ids only, EXECUTE only for `ssms_app` (I11–I16) |
| D3 | Review (F3) | `UNIQUE (channel, external_ref)` was global | Per school; RFID token per school; global uniqueness kept only for GePG bill ref/control number, refresh-token and device-key hashes (documented) |
| D4 | Review (F6) | An invoice with payments could be cancelled, losing the money's link | `fn_invoices_derive` refuses; use a discount line or reversal (F6d) |
| D5 | Seed run | `fn_journal_balanced` referenced `NEW.journal_id` when fired on `journals` | Read the field generically via `to_jsonb(NEW)` |
| D6 | Seed run | The audit function draft wrote a garbled `VALUES` list | Rewritten; school, actor, request id and redaction verified (F9a, F9b) |
| D7 | Test runner | The first runner stripped the `-- TEST` comment marker, so every block failed | Runner fixed; failures are counted, not hidden (43/43 pass) |
| D8 | Diagram render | Semicolons inside Mermaid sequence messages broke parsing | Replaced with "·" |
| D9 | Data dictionary | Inline DDL comments that were only examples became descriptions | Generator prefixes the field name ("Admission no, e.g. TZ-2026-0001") |
| D10 | Real PG 16.9 via psql | A test file runs as one transaction in psql, so F4c's extra component leaked into F4e | Every `-- TEST` block wraps itself in `SAVEPOINT test_block … ROLLBACK TO SAVEPOINT test_block` |

## 17.4 Defects and decisions in Phase 1

| # | Found by | Issue | Resolution |
|---|---|---|---|
| D11 | pytest (OTP, two schools) | With `autoflush=False`, rows added under school A were flushed after the context switched to school B and RLS rejected them | `set_context()` flushes pending rows before switching school |
| D12 | Drift test | `student_status_history.old_status/new_status` had no CHECK | Migration 0002 adds both CHECKs |
| D13 | Design review | Every login updated `users` and wrote a row-audit UPDATE next to the LOGIN event | Migration 0002: `fn_audit_row` ignores `last_login_at`, `failed_login_count`, `locked_until` |
| D14 | Deployment review | Roles and permissions existed only in the demo seed | Migration 0003 inserts the reference data; the seed uses `ON CONFLICT DO NOTHING` |
| D15 | pytest (lists) | `lower()` sort keys had no SQL type, so cursors could not be decoded | Sort expressions are typed (`type_=String`); untyped keys fall back to text |
| C1 | Design | `perm_ver` JWT claim | Removed: permissions are loaded per request ([ADR 0011](adr/0011-permissions-per-request.md)) |
| C2 | Design | Onboarding as a background job | One transaction ([ADR 0012](adr/0012-synchronous-onboarding.md)) |
| C3 | Design | Admission number prefix was not configurable | `school_settings.admission_prefix` (migration 0002), default from the school code |
| C4 | Design | Student age rule 3–25 vs message 3–30 | Rule follows the message: 3–30 years |

## 17.5 Defects and decisions in Phase 2

| # | Found by | Issue | Resolution |
|---|---|---|---|
| D16 | Design review | A subject could never leave a combination (no `deleted_at`, no DELETE grant) | Migration 0004: soft delete on `combination_subjects`; `results_scope` ignores removed subjects |
| D17 | pytest (classes) | A class could be deleted while another class still promoted into it | Delete is blocked while any class points to it |
| D18 | pytest (report cards) | Results-SMS idempotency key (two dashed UUIDs) exceeded VARCHAR(80) | Compact hex UUIDs (73 characters) |
| D19 | Code review | The marks Excel upload saved the good rows when one row failed | `save_batch(all_or_nothing=True)` rolls back the whole batch |
| D20 | Visual check | Component headers overlapped on the report card | Short bilingual labels: CA(30) Kati(20) Muhula(50) |
| C5 | Design | Timetable generation as a job | Synchronous draft/save ([ADR 0015](adr/0015-timetable-generator.md)) |
| C6 | Design | Report card as a 307 signed URL to a stored PDF | PDF built on request from current results; class bundle by job ([ADR 0014](adr/0014-report-cards.md)) |
| C7 | Design | Application by "public + OTP-verified phone" | Parent signs in with the SMS code, then applies |
| C8 | Design | No period grid in the schema | Default bell schedule in code (**VERIFY**); a `bell_schedules` table is a Phase 6 candidate |
| C9 | Design | A-Level combination subjects and the generator | The generator schedules the class curriculum (`class_subjects`, compulsory or not); A-Level schools add combination subjects to the class with their periods |

## 17.6 Defects and decisions in Phase 3

| # | Found by | Issue | Resolution |
|---|---|---|---|
| D21 | pytest (cancel invoice) | `journals.source_type` VARCHAR(12) was shorter than `INVOICE_CANCEL` (14) | Migration 0005 widens it to VARCHAR(14) |
| D22 | pytest (reports) | Report amounts were serialised as floats (`0` instead of `"0.00"`) | `MoneyOut` and `fee_reports.money_json`: money is always a decimal string |
| D23 | pytest (fee structures) | Archiving a DRAFT violated the approval CHECK | Only APPROVED structures are archived; drafts are deleted |
| C10 | Design | No table for a reversal request waiting for approval | `payment_reversal_requests` (one PENDING per payment, `decided_by <> requested_by`, RLS, audit) |
| C11 | Design | Percent discounts on the whole invoice | Percent discounts apply to TUITION lines only |
| C12 | Design | Unallocated payments left for manual allocation | Every payment is allocated at once; the remainder becomes credit and pays the next invoice |
| C13 | Design | A GePG amount mismatch could be refused | Accepted, receipted and flagged (`amount_matches_bill=false`) for reconciliation |
| C14 | Design | Mobile-money callbacks per provider | One signed JSON format through an aggregator (**VERIFY**), [ADR 0016](adr/0016-payment-channels.md) |

## 17.7 Defects and decisions in Phase 4

| # | Found by | Issue | Resolution |
|---|---|---|---|
| D24 | pytest (feed) | The announcement feed compared `publish_at` with the database `now()`, which is fixed at transaction start | Compared with the application clock |
| D25 | Code review | The SMS balance view summed every school under the console role (BYPASSRLS) | `credits_left` and the credit report always filter by school |
| D26 | Design review | SMS delivery reports carry no school and could not be routed under RLS | Migration 0006: resolver `resolve_sms_message` + index on (provider, provider_message_id) |
| D27 | Design review | `sms_credit_transactions` could be updated by the runtime role | Migration 0006 revokes UPDATE (append-only); audit triggers added on devices, cards, announcements, templates |
| C15 | Design | Absence alert for "no PRESENT/LATE today" | Only on recorded evidence ([ADR 0017](adr/0017-absence-evidence.md)) |
| C16 | Design | LATE had no rule | Gate tap after the absence cut-off = LATE (**VERIFY** with schools) |
| C17 | Design | `/attendance/sessions/today` | `/attendance/register?stream_id&date` (offline phones sync earlier days, 7-day window) |
| C18 | Design | Devices managed by `attendance.device` only | Also `settings.update` (the school office) |
| C19 | Design | No credit rule for SMS | Debit, skip, essential messages, refund ([ADR 0018](adr/0018-sms-credit-ledger.md)); a REFUND row has no `sms_message_id` (CHECK `ck_sct_debit`), the message id is in `note` |
| C20 | Design | School-side `POST /sms/credit` | Top-up by the platform console |
| C21 | Design | Parent and student portal endpoints per child | `/me/*` plus the shared `/students/{id}/…` endpoints |

## 17.8 Defects and decisions in Phase 5

| # | Found by | Issue | Resolution |
|---|---|---|---|
| D28 | Playwright | The bed request could be sent before the terms had loaded (422 `term_id`) | Button disabled until a term is chosen |
| D29 | Playwright | Approving a request did not refresh the hostel's occupancy card | The page reloads occupancy after every decision |
| D30 | Playwright | The whole E2E suite exceeds the per-IP login limit (30/min) | E2E and CI run with `SSMS_LOGIN_ATTEMPTS_PER_MINUTE=60`; production keeps 10 |
| D31 | Design review | Capacity and overlap violations surfaced as `RULE_VIOLATION` with English database text | `crud.flush_checked` and the venue service map them to `FULL` / `VENUE_CLASH` / `DUPLICATE` with codes |
| C22 | Design | "assignment (+ fee line)" without a rule for invoices already issued | Charge added to the open term invoice with its journal, else at generation ([ADR 0019](adr/0019-facility-fees-on-the-term-invoice.md)) |
| C23 | Design | Boarding fee source not defined | Optional BOARDING line of the class fee structure, charged only to students with a room |
| C24 | Design | Club members managed by activities.manage only | The club's patron manages its members too |
| C25 | Design | Library overdue reminders undefined | Weekly SMS per overdue loan (students: primary guardian; staff: themselves) |
| C26 | Design | Health records: "consent" not specified | A guardian's HEALTH_DATA consent for the student (or all their children); reads audited VIEW_SENSITIVE |

## 17.9 Defects and decisions in Phase 6

| # | Found by | Issue | Resolution |
|---|---|---|---|
| D32 | EXPLAIN on synthetic data | The chronic-absence list (view `v_chronic_absence`) grouped the whole year before filtering one week; it grew through the year | `attendance.chronic` filters the week's dates first (49 → 8 ms at 102 schools) |
| D33 | Load test review | Webhooks were limited to 600 requests/min per IP; GePG and aggregators send bursts from few IPs | `SSMS_WEBHOOK_REQUESTS_PER_MINUTE`, default 6,000 |
| D34 | Deployment review | docker-compose had no Celery beat (no absence alerts, reminders or overdue SMS), no Phase 3–4 settings and no backups | `beat` and `backup` services, every setting in the shared API environment |
| D35 | Code review | Job files were always served as Excel | Type and extension follow the stored file (CSV, PDF, JSON) |
| D36 | Code review | Logs were plain text (NFR-13 asks JSON) | JSON in production (`SSMS_LOG_FORMAT`) |
| C27 | Design | `/dashboards/{role}` for every role | Office, bursar and teacher dashboards; parents and students have their own home screens |
| C28 | Design | Data deletion | Anonymisation that keeps legally required records ([ADR 0021](adr/0021-anonymise-not-delete.md)) |
| C29 | Design | Compliance templates "configurable" | Four built-in templates; layouts **VERIFY** with the ministry before relying on them |
| C30 | Design | 300 schools × 1,500 students measured | 102 schools measured locally (plans stay per-school); the full size and 500 req/s are **VERIFY** on staging |

## 17.10 Changes taken from the first design (2026-10-31)

| Topic | Decision |
|---|---|
| Page size | Maximum lowered from 200 to 50 at the owner's request. This replaces the 50/200 in master-prompt Rule 2. |
| Saturday | Timetable grid shows Saturday; registers open on Saturday only when the term has Saturday lessons. The generator stays Monday–Friday. |
| CA/exam split | New schools get CA 40 % + terminal 60 % per term and level. Existing schools keep their configuration. |
| Grades | The default O-Level scale already matched (A 75, B 65, C 45, D 30, F 0); now asserted by a test. NECTA check stays **VERIFY**. |
| Lockout | Already 5 failures / 15 minutes; no change. |
| Qualifications | New `staff_subjects`; existing teaching was backfilled so current timetables stay valid. Enforced on slots and the generator, not on teaching assignments. |
| Registrar | New role, §15. |
| Audit retention | At least 7 years, never purged earlier. |

Defects found while testing: the Results page could show the firewall answer of a previously selected term when replies
arrived out of order (fixed: only the newest selection may display); the register E2E skip check did not wait for the page.

## 17.11 Normalisation pass (2026-10-31)

Migration `0009_normalisation`. Every foreign-key path in the 102 tables was scanned for transitive dependencies; no drift
was found in the demo data, so these are preventive.

| Finding | Fix |
|---|---|
| `transport_assignments.route_id` determined by `stop_id` | Column removed |
| `reconciliation_runs.matched_count`, `exception_count` stored; determined by the items | Columns removed, counted on read |
| `attendance_sessions.stream_id` on LESSON rows determined by the slot | LESSON rows hold only the slot (none existed) |
| `enrolment_requirements` could hold a level and a class of another level | Check: one or the other |
| Enrolment/application, allocation/request, bank confirmation/payment, reversal request/reversal could disagree | Composite foreign keys |

Left as they are, with reasons in 06 §6.5. The two open points, region/district text and `rooms.equipment`, were closed
the same day: see §17.12.

## 17.12 Locations and room equipment (2026-10-31)

Migration `0010_locations_equipment`, at the owner's request.

- **Regions and districts:** 31 regions and 195 districts, from the 2022 census divisions published by citypopulation.de.
  **VERIFY** against the current PO-RALG list before launch; Wikipedia's page (about 184 councils, 2021) names and counts
  them differently. Names were tidied: parent notes removed, "Busekelo" on the source corrected to Busokelo, "Mwanza
  (Nyamagana Municipal)" stored as Mwanza City, "Tanganyika (Mpanda Rural)" as Tanganyika. A school whose old text matches no
  district stops the migration rather than being guessed. A new district is added by a migration; there is no screen.
- **Room equipment:** comma-separated text became rows, with a leading number read as the quantity ("45 desks" → Desks ×
  45). Items are per school, because schools name things differently. Text with no commas stays one item, so "desks and
  chairs" must be split by hand.
