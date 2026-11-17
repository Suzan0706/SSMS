# SSMS — Progress

Read this first after any interruption. Version 1 (single school) lives in `docs/`, `backend/`, `db/` and is not touched.

Verification tooling (outside the repo): PGlite + mermaid-cli in the session scratchpad (`verify/v2_load.mjs` loads `design/sql/schema.sql` plus extra SQL files).

## Done
- [x] `design/sql/schema.sql` first draft: 99 tables, RLS forced on 95, 10 views, 1166 columns (2026-10-22)
- [x] Step 1 state check: schema reloads OK

- [x] Step 2: fixes applied in `schema.sql`, reload OK — 99 tables (95 RLS-forced), 10 views, 1166 columns;
      109 tables/views + 23 functions owned by `ssms_owner`, 6 SECURITY DEFINER resolvers owned by `ssms_resolver`
  - F1 roles `ssms_owner` / `ssms_app` / `ssms_resolver` / `ssms_platform` / `ssms_reporting` (section 0, 19); objects created under `SET ROLE ssms_owner`
  - F2 resolvers: `resolve_school_by_code`, `resolve_device`, `resolve_gepg_bill`, `resolve_refresh_token`, `resolve_users_by_phone`, `list_active_school_ids` (section 18), EXECUTE only for `ssms_app`
  - F3 `uq_payments_external_ref` = (school_id, channel, external_ref); `rfid_cards` token per school; `gepg_bills` bill_ref/control_number stay global (documented: needed to route callbacks)
  - F4 `fn_mark_entries_guard` (range, lock, version) + `results_firewall()` incl. `WEIGHTS_NOT_100`
  - F5 deferred balance triggers on journals/ledger_entries + append-only — unchanged, to be tested
  - F6 `fn_invoices_derive` + new rule: cannot cancel an invoice that has payments
  - F7 frozen triggers + `publish_results()` and `amend_result()` (maker-checker)
  - F8 seed design: `SET ROLE ssms_owner` + `SET LOCAL app.school_id` per school block
  - F9 `fn_audit_row` — to be tested

- [x] Step 3: `design/sql/seed.sql` loads (as `ssms_owner`, `SET LOCAL app.school_id` per school).
      Exercises `publish_results()` (Form II, 54 frozen results), `next_document_no()`, a maker-checker reversal,
      balanced journals at commit. Fix found: `fn_journal_balanced` read `NEW.journal_id` on `journals` rows.
      Checked as `ssms_app`: invoice totals/status, sibling discount, 20,000 student credit, chronic absence, installment cover,
      Form V firewall = 5 MISSING_MARK.

- [x] Step 4: `design/sql/tests/01_isolation.sql` (16) + `02_integrity.sql` (27) — **43 passed / 0 failed**, all as `ssms_app`
      (runner: scratchpad `verify/v2_tests.mjs`, each `-- TEST` block in its own savepoint).

- [x] Step 6 verification (final): 72 relative links/anchors OK, 35 Mermaid diagrams render, data dictionary 1166 rows =
      1166 live columns, schema + seed + tests: **43 passed / 0 failed** as `ssms_app` (PGlite / PostgreSQL 18 build —
      re-run on PostgreSQL 16 in CI). Version 1 folders (`docs/`, `db/`, `backend/`) unchanged.

**PHASE 0 COMPLETE.** Next: Phase 1 — Foundation (see README / 01-introduction §1.3).

## Done (step 5 detail)
- [x] Step 5: documents 01–17 + README
  - [x] 01-introduction, 02-requirements (71 FR, 15 NFR), 03-context-dfd (L0, L1 in 4 views + balancing table, L2 for 2.0/4.0/5.0), 04-use-cases
  - [x] 05-erd (7 area ERDs), 06-data-model, 07-data-dictionary (generated: 99 tables, 1166 rows = live column count;
        generator scratchpad `verify/v2_dictionary.mjs`)
  - [x] 08-class-diagram (3 diagrams), 09-sequence (6), 10-activity (4) — all render
  - [x] 11-architecture (4 diagrams), 12-api-design (all modules)
  - [x] 13-io-specifications (16 form groups + 8 outputs), 14-wireframes (all portals)
  - [x] 15-security (RBAC matrix generated from seed: 54 permissions × 11 roles), 16-test-plan
  - [x] 17-corrections, README

## Phase 1 — Foundation (started 2026-10-22)

Code lives in `ssms/` (`ssms/api` FastAPI, `ssms/web` React PWA, `ssms/docker-compose.yml`); CI in `.github/workflows/ssms-ci.yml`.
Test database: real **PostgreSQL 16.9** portable binaries (EDB zip) in the session scratchpad (`pg16/`), cluster started with trust auth on port 55433.

- [x] P1.1 PostgreSQL 16.9 local cluster (scratchpad `pgdata`, port 55433, start: `pg_ctl -D pgdata -o "-p 55433" start`).
      Phase 0 schema + seed + tests on **real PG 16.9 via psql: 43/43 PASS**. Found D10: in psql the test file is one
      transaction, so F4c's extra component leaked into F4e → every `-- TEST` block now wraps itself in
      `SAVEPOINT test_block … ROLLBACK TO SAVEPOINT test_block` (scratchpad `verify/wrap_tests.mjs`).
- [x] P1.2 API skeleton: config, errors (single format, sw/en, incl. 404/405/500), uuid7, crypto (AES-GCM + HMAC
      blind index), phone, security (Argon2id, JWT), rate limiter, pure-ASGI middleware (request id, language,
      security headers, access log), `app/main.py`, `/health/live|ready`. Smoke test OK.
- [x] P1.3 DB layer: async engines (app / platform), tenant context (SET LOCAL via after_begin), 37 models
      (`app/models/{platform,people,academic,system}.py`), Alembic `0001_baseline` (runs `design/sql/schema.sql`) +
      `0002_phase1` (`school_settings.admission_prefix`, CHECKs on `student_status_history`, `fn_audit_row` ignores
      login bookkeeping columns) + `0003_reference_data` (11 roles, 54 permissions, 90 role grants — production needs
      them without the demo seed; `seed.sql` now inserts the same rows with `ON CONFLICT DO NOTHING`).
      Fresh PG16 DB → `alembic upgrade head` → seed → Phase 0 SQL tests: **43/43 PASS**. Drift check models vs DB:
      0 problems, enum values = DB CHECK lists. Script: scratchpad `verify/fresh_db.sh <db> [--seed] [--tests]`.
- [x] P1.4 Auth (`app/services/auth.py`, `app/api/auth.py`, `app/api/deps.py`): login (school code + username,
      Argon2id, same answer for unknown school/user/wrong password), lockout 5 → 15 min (423), refresh rotation in
      token families with reuse detection (10 s grace for parallel tabs), logout, me, change password (signs out
      other sessions), parent OTP (keyed hash, 5 attempts, one SMS, code masked in `sms_messages`, school choice via
      selection token), rate limits, audit events. SMS: `app/services/sms.py` (console/Beem/NextSMS — VERIFY),
      Celery worker + dispatcher (`app/tasks/`). Test harness `tests/conftest.py` (superuser only creates DB +
      migrates + seeds; app = ssms_app; one rolled-back transaction per test). **21/21 auth tests pass.**
      Bug found and fixed: `set_context` now flushes pending rows before switching school (else RLS rejected them).
      Reset-password endpoint moves to P1.6 (`/users/{id}/reset-password`).
- [x] P1.5 RBAC (`require_permission`, permissions loaded per request) + console (`app/api/platform.py`,
      `app/services/platform.py`): login with TOTP (MFA_SETUP_REQUIRED in production without a secret), separate
      token audience, schools list (cursor pagination `app/core/pagination.py`), create school = school + settings +
      admin (temporary password, SMS) + defaults (`app/services/onboarding.py`: year, 2 terms, 11 fixed holidays,
      levels/classes/stream A, NECTA scales — VERIFY, departments, designations, 13 ledger accounts, 6 fee items,
      10 templates) in ONE transaction, status changes with transition rules + audit. Operator CLI `app/cli.py`.
      Test harness now logs in as `ssms_tester` (no privileges) and runs `SET LOCAL ROLE ssms_app` /
      `ssms_platform` per session. **29/29 tests pass.** Decision: onboarding is synchronous (≈100 rows, atomic)
      instead of the job in 12-api-design → record in 17-corrections (P1.10).
      Fix: ids are assigned at object construction (`IdMixin` init event) so related rows link before flush.
- [x] P1.6 People (`app/api/{school,users,staff,students}.py`, `app/services/{people,staff,students}.py`,
      `app/schemas/people.py`): school settings; read-only `/academic-years`, `/classes`, `/streams`; users list
      (role/q/status, cursor), enable/disable (signs out), reset password (temporary, SMS, forces change), role
      grant/revoke (cannot remove own school_admin); staff CRUD + account + qualifications, salary only with
      payroll.read, leavers disabled; departments/designations (cannot delete while in use); students admit
      (admission no `<prefix>-<year>-<seq>` from `next_document_no`, enrol into stream with STREAM_FULL, guardians
      reused by phone blind index, PDPA consents), list/search/cursor, update, status transitions (leaving ends the
      enrolment), identifiers via audited VIEW_SENSITIVE endpoint; guardian links (primary rule) and consents
      (withdrawing SMS consent stops SMS). Phones masked without guardians.manage / staff.manage; a phone that
      cannot be decrypted is shown masked, never a 500. **53/53 tests pass** (people: 24).
- [x] P1.7 Bulk import (`app/services/imports.py`, `app/api/imports.py`): XLSX templates with help sheet; upload
      XLSX/CSV (size limit 413, type sniffing, header check, ≤ 2000 rows) with required Idempotency-Key
      (`app/services/idempotency.py`: replay / IDEMPOTENCY_MISMATCH); Celery task `imports.run` validates every row
      first (field rules reused from the API schemas, classes/streams, duplicates in file and in school, stream
      capacity) → error report XLSX, else writes all rows in ONE transaction (rollback + report on any failure);
      result XLSX (admission numbers / usernames); account SMS dispatched only after commit. Jobs API (`/jobs`,
      `/jobs/{id}`, `/jobs/{id}/files/{errors|result}`, owner or users.manage), audit API (`/audit-logs`, newest
      first, cursor). Storage interface `app/core/storage.py` (local now). **63/63 tests pass** (imports: 10).
- [x] P1.8 Tests on real PG 16.9: **96/96 pass, coverage 93 % (services 83–100 %, floor 80 % in pyproject)**.
      Files: `test_auth` 21, `test_platform` 8, `test_people` 24, `test_imports` 10, `test_core` 24 (uuid7, phone,
      AES-GCM rotation + field binding, JWT types/audiences, Argon2, cursor tampering, rate limit, i18n, SMS
      segments, storage key safety, headers, 500 format), `test_sms` 4 (Beem/NextSMS over mocked HTTP, transient vs
      permanent), `test_schema` 5 (drift models↔DB, enum↔CHECK, ssms_app cannot see platform_admins, Phase 0 SQL
      suites 01/02 run from pytest via SET ROLE ssms_app: 16 + 27 PASS).
- [x] P1.9 Web `ssms/web` (Vite 5, React 18, TS strict, Tailwind 3, own sw/en dictionary, PWA manifest + service
      worker for the shell only): staff login, parent OTP + school choice, forced password change, app shell with
      permission-based menu, students (search, filter, cursor, admit, detail, status change), staff (list, add,
      temporary password once), bulk import (template, upload with Idempotency-Key, job polling, error/result
      download). Access token in memory only; refresh via httpOnly cookie. **Build 65 KB gz** (budget 200 KB,
      `npm run size`). **Playwright E2E 6/6 pass** (system Chrome) against uvicorn + PG16 (`ssms_e2e`, runtime role
      ssms_app). Added `SSMS_TASKS_INLINE` (dev/E2E without Redis; refused in production). Windows note: uvicorn must
      run on a SelectorEventLoop for async psycopg (production is Linux).
- [x] P1.10 `ssms/api/Dockerfile` (built from repo root, baseline copied in, non-root), `ssms/web/Dockerfile` +
      `nginx.conf` (same-origin /api proxy, CSP, caching), `ssms/docker-compose.yml` (db 16.9, redis, migrate →
      `alembic upgrade head` + `app.cli db-logins`, api, worker, web, demo seed profile), `ssms/.env.example`,
      `.github/workflows/ssms-ci.yml` (pytest on postgres:16.9, web build + size, Playwright E2E), `ssms/README.md`
      (run, test, env vars, examples, security). Docs: 13 ADRs in `design/adr/`; `perm_ver` removed (04, 09, 11, 15);
      12-api-design (onboarding, identifiers, jobs); 07 `admission_prefix`; 16-test-plan Phase 1 results;
      17-corrections D10–D15 + C1–C4; README. Links 83/83 OK, changed Mermaid diagrams render (10/10).
      NOT verified here: Docker is not installed on this machine, so images/compose were only parsed, not run.

**PHASE 1 COMPLETE (2026-10-22).** Next: Phase 2 — Academics (subjects, combinations, rooms, timetable, exams,
marks entry offline, results firewall + publish API, report cards). Read `design/adr/` first.

## Later
- [x] (done above) Phase 1 — Foundation: repo structure, docker-compose, config, async SQLAlchemy models from `schema.sql`,
      Alembic baseline, auth (JWT + OTP), RBAC, tenant dependency + RLS context, audit, schools, users, students,
      guardians, staff, departments, bulk import; run `design/sql/tests` in CI on PostgreSQL 16.

## Phase 2 — Academics (started 2026-10-22)

Scope (01-introduction §1.3, 12-api-design "School setup", "Enrolment", "Timetable and exams", "Marks and results").
The results pipeline already exists in the database (`results_scope`, `results_firewall`, `publish_results`,
`amend_result`, frozen tables, `fn_mark_entries_guard`); Phase 2 exposes it safely and adds the rest.

- [x] P2.1 (`app/models/curriculum.py`, `app/models/results.py`, 6 enums; drift test 5/5 incl. 20 new tables) Models for Phase 2 tables (subjects, combinations, class_subjects, rooms, class teachers, teaching
      assignments, assessment components, enrolment requirements/applications/documents, timetable, exams, marks,
      publications, results, summaries, amendments, comments) + drift test; SQLSTATE P0002 → 404
- [x] P2.2 (`app/api/academics.py`, `app/services/{academics,crud}.py`, `app/schemas/academics.py`; migration 0004 soft delete for combination_subjects + results_scope filter; 11 tests, suite 107/107) Academic configuration API: levels, years (one current), terms (inside year, no overlap), holidays,
      classes (+promotion path), streams (+class teacher), subjects, class subjects, combinations, rooms, grading
      schemes (new version on change, bands/divisions validated), assessment components (+weight check)
- [x] P2.3 (`app/api/enrolment.py`, `app/services/{enrolment,promotions}.py`, `app/core/files.py`; 5 tests, suite 112/112. Applicants are students with status APPLICANT and a reserved admission no.; documents served through the API, not signed URLs) Enrolment workflow: requirements, public offerings, applications (staff and parent), documents (magic
      bytes, ≤ 5 MB), submit, validate, approve (stream capacity, admission no.), reject, cancel; promotions job
- [x] P2.4 (`app/api/timetable.py`, `app/services/timetable.py`; default bell schedule Mon–Fri 9 × 40 min is VERIFY; generator is synchronous; 7 tests incl. a full 64-lesson draft for Form II A+B saved without clashes) Teaching assignments + timetable: slots CRUD, live check (clashes, assignment, room type/capacity,
      teacher load, free periods), generator (most-constrained-first greedy + one-step repair, draft/persist), ETag
- [x] P2.5 (same files; sessions inside the term, papers inside the session; 1 test) Exams: sessions and papers (class/room clash → 409)
- [x] P2.6 (`app/api/marks.py`, `app/services/marks.py`; per-item savepoints, same value with a stale version is not a conflict; upload uses all_or_nothing; 3 tests, suite 124/124) Marks: sheet (own assignment), batch upsert with optimistic versions (per-item ok/conflict/error),
      XLSX marks import job
- [x] P2.7 (`app/api/results.py`, `app/services/results.py`; firewall before publish_results gives the full bilingual list; approver = requester → 403; 7 tests) Results: firewall (bilingual problems), publish (Idempotency-Key, 422 INCOMPLETE_GRADES_BLOCK), class
      and student results, comments, amendments (maker-checker), basic analytics
- [x] P2.8 (`app/services/report_cards.py`, ReportLab; single card rendered on request from current results so never stale (no signed URL); class bundle + results SMS by job; checked visually sw/en; suite 131/131, 93 %) Report-card PDFs (job per publication, amended versions regenerate) + results SMS to consenting guardians
- [x] P2.9 (`ssms/web/src/pages/{Academics,Timetable,Exams,Marks,Results,StudentResults,Enrolment}.tsx`, `src/academic.ts`, `src/offline.ts` (device queue + versioned batch sync, conflict choice); lazy chunks; build ≈ 80 KB gz; API: `/teaching-assignments?mine=true`, `student_id` in class results) Web: academic setup, timetable grid + live check + generate, exams, offline marks grid, publish with
      firewall list, results + report card, enrolment review; bundle < 200 KB gz
- [x] P2.10 (pytest **131/131**, coverage 93 %: academics 11, enrolment 5, timetable 9, marks 3, results 7 + Phase 1 96; Playwright **9/9** incl. `e2e/phase2.spec.ts` offline marks → sync → publish → report card PDF, timetable live check; DB reset script now uses DROP … WITH (FORCE)) Tests (pytest PG16 as ssms_app, ≥ 80 % services; Playwright: offline marks → sync → publish → report card)
- [x] P2.11 Ruff (lint + format, line 120) on all API code and in CI; docs: 12-api-design §12.3 Phase 2
      implementation notes, 16-test-plan Phase 2 results, 17-corrections §17.5 (D16–D20, C5–C9), ADR 0014 report
      cards, ADR 0015 timetable generator, design/README, ssms/README. Links 87 + 15 OK. Final: pytest 131/131
      (93 %), Playwright 9/9, web ≈ 80 KB gz. Not run here: Docker (not installed).

**PHASE 2 COMPLETE (2026-10-23).** Next: Phase 3 — Finance (fee structures, invoices, GePG control numbers,
mobile money and bank callbacks, allocations, receipts, reconciliation, reminders). Read `design/adr/` and
`design/12-api-design.md` §12.3 first. VERIFY items open: NECTA scales, class structure, term dates, bell schedule,
GFS codes, Beem/NextSMS APIs, parent session length.

## Phase 3 — Finance (started 2026-10-23)

The database already enforces the money rules (derived invoice totals/status, allocation guard, immutable payments,
receipts, balanced journals at commit, reversals by two people). Phase 3 exposes them, posts every journal, and
connects GePG, mobile money and banks through adapters (provider message formats are **VERIFY**).

- [x] P3.1 (`app/models/finance.py` 18 models + 12 enums; drift 5/5; 43 SQL tests pass after 0005) Models for finance tables; migration 0005 `payment_reversal_requests` (request → approve/reject)
- [x] P3.2 (`app/api/fees.py`, `app/services/fees.py`) Fee setup: fee items, fee structures (DRAFT lines → approve by fees.configure + settings.update →
      ARCHIVED), discount rules, student discounts
- [x] P3.3 (`app/api/invoices.py`, `app/services/invoices.py`; percent discounts apply to TUITION) Invoicing: generate job (approved structure, year lines on the first term, discounts, installments,
      existing credit applied), invoice journal, list/detail/statement, cancel (no payments, reversing journal),
      invoice PDF
- [x] P3.4 (`app/services/{payments,ledger}.py`; amounts in words sw/en tested) Payment processing: allocate oldest due first (FOR UPDATE), journals (clearing / receivable / credit),
      gapless receipt, receipt PDF (amount in words), receipt SMS — idempotent
- [x] P3.5 (`app/services/{gepg,mobile}.py`, `app/api/webhooks.py`; RSA-SHA256 signed XML, DOCTYPE refused, HMAC JSON, ON CONFLICT DO NOTHING; formats VERIFY) Channels: cash/bank entry (Idempotency-Key), bank deposits (submit → bank officer confirms), GePG
      (control-number request, signed bill and payment callbacks, simulator), mobile-money webhooks (HMAC),
      parent push request (adapter)
- [x] P3.6 (`app/services/reconciliation.py`; D21 found: journals.source_type VARCHAR(12) < 'INVOICE_CANCEL' → migration 0005 widens it) Reversals (request → approve by another person → REVERSED + reversing journal), reconciliation runs
      (statement CSV → matched / missing / mismatch, resolve items)
- [x] P3.7 (`app/services/fee_reports.py`; money always "0.00" strings via MoneyOut; beat 09:00 EAT; tests: 17 finance + seed invariant, suite 149/149) Reports (aging, defaulters, collections; XLSX) and reminders (overdue installments, once per
      installment, consenting guardians; Celery beat fan-out)
- [x] P3.8 (`web/src/finance.tsx` shared StatementView + string-safe money(); pages Fees (6 permission-gated tabs), Bank, Children on parent home; `GET /me/children`; build 87.4 KB gz) Web: fee setup, invoices, record payment + receipt, reversals, bank confirmations, reconciliation,
      reports; parent statement and pay
- [x] P3.9 (pytest **150/150**, coverage 93 %, finance services 81–96 %, Ruff clean; Playwright **11/11** incl.
      `e2e/phase3.spec.ts` bursar cash → receipt PDF + duplicate refused, parent SMS login → statement with the
      receipt; docs: 12-api-design §12.4 Phase 3 notes (Example → §12.5), 16-test-plan Phase 3 results, 17-corrections
      §17.6 D21–D23 + C10–C14, ADR 0016 payment channels, ssms/README (scope, env vars, examples), design README;
      links 89 + 16 OK) Tests + Playwright; docs, ADRs, README

**PHASE 3 COMPLETE (2026-10-23).** Next: Phase 4 — Attendance and communication (per the master
prompt). Read `design/adr/` (0016 for money), `design/12-api-design.md` §12.3–12.4 first. VERIFY items open: GePG
SP specification (signature, ACK codes 7101, RemFlag partial payments, local times), mobile-money aggregator
format, GFS codes, NECTA scales, bell schedule, Beem/NextSMS APIs, parent session length.

## Phase 4 — Attendance and communication (started 2026-10-23)

Scope (master prompt): registers, RFID/QR devices, absence alerts, SMS adapters, templates, parent and student
portals. The schema already has every table (devices, rfid_cards, attendance_sessions/records, absence_alerts,
announcements, notifications, message_templates, sms_messages, sms_credit_transactions, v_chronic_absence,
v_sms_credit_balance, resolve_device). Provider message formats (Beem/NextSMS delivery reports, device firmware)
are **VERIFY**.

- [x] P4.1 (`app/models/attendance.py` 5 models, Announcement/Notification/SmsCreditTransaction in system.py, 9 enums; drift + enum tests 5/5) Models for attendance + communication tables; migration 0006: `resolve_sms_message` resolver (delivery
      reports arrive without a school), index on provider_message_id, audit on devices/rfid_cards/announcements
- [x] P4.2 (`app/services/{attendance,calendar}.py`, `app/api/attendance.py`; later captured_at wins, older edit = conflict; 7-day sync window; class teacher, stream teachers or office; 4 tests) Registers: today's session + class list (ETag) for the class teacher (or attendance.read admins), offline
      batch sync by client_record_id (synced / conflict), close; reports per stream/student/range (+ XLSX), chronic list
- [x] P4.3 (`app/services/devices.py`, `app/api/devices.py`; LATE = after absence cut-off (VERIFY); new card replaces the active one of its kind; office may also manage devices; 2 tests, suite file 6/6) Devices and cards: register device (API key shown once, SHA-256 stored), disable; issue/lose/revoke
      RFID/QR cards; `POST /devices/taps` with X-Device-Key → GATE session, PRESENT or LATE after cut-off, unknown cards
- [x] P4.4 (`app/services/{sms,alerts}.py`, `/webhooks/sms/{provider}?token`; advisory lock per school on credit; absent = register ABSENT, or no register + gate in use + no tap; window cut-off → 12:00 (VERIFY); 4 tests; suite 156 before) SMS core: credit check + DEBIT on queue (essential messages such as OTP never blocked), REFUND on
      permanent failure, low-credit notification (< 100), delivery-report webhook, absence-alert fan-out (every 5 min,
      school days only, after cut-off, one per student per day, consent)
- [x] P4.5 (`app/services/communication.py`, `app/api/communication.py`, console `POST /platform/schools/{id}/sms-credit`; credit always filtered by school (console bypasses RLS); feed compares publish_at with the app clock; 5 tests) Communication: announcements (audience rules, optional SMS as SMS_BATCH job, credit check 422), viewer
      feed, notifications inbox, message templates (placeholder validation, ≤ 3 segments), SMS log (masked), credit
      balance/history; top-up from the platform console
- [x] P4.6 (`app/api/portal.py`: /me/children + today_status/gate_in_at/stream_id, /me/student, /me/timetable; details reuse /students/{id}/attendance|results|statement; 2 tests) Portals: parent children with today's attendance, month attendance, announcements; student own
      timetable, attendance, results and fees
- [x] P4.7 (`web/src/registerQueue.ts` offline outbox; pages Attendance (register + reports), Devices, Announcements, Sms, Inbox (bell), StudentHome; Children: today + month + announcements; `dates.ts`; build 98.7 KB gz) Web: register (offline outbox), attendance reports, devices + cards, announcements, SMS (templates,
      log, credit), inbox; parent and student homes
- [x] P4.8 (pytest **167/167**, coverage 92.9 %, Phase 4 services 87–98 %; Ruff clean; Playwright **14/14** incl. `e2e/phase4.spec.ts`: offline register → sync, gate tap on the register, close; announcement; parent sees today + month + announcement. Absence SMS covered by pytest (beat not run in E2E)) Tests (pytest PG16 as ssms_app, ≥ 80 %) + Playwright (offline register → sync → absence SMS; gate tap;
      parent sees attendance and announcement)
- [x] P4.9 (12-api-design §12.5 Phase 4 notes (Example → §12.6), 16-test-plan Phase 4 results + E2E-6, 17-corrections §17.7 D24–D27 + C15–C21, ADR 0017 absence evidence, ADR 0018 SMS credit ledger, ssms/README (scope, env var, examples), .env.example (Phase 3 + 4 settings), design README; links 93 + 18 OK) Docs: 12-api-design §12.5 Phase 4 notes, 16-test-plan, 17-corrections §17.7, ADR(s), README, PROGRESS

**PHASE 4 COMPLETE (2026-10-23).** Next: Phase 5 — Facilities and student life (hostel, transport, venues,
discipline, clubs, library). Read `design/adr/` (0017–0018) and `design/12-api-design.md` §12.3–12.5 first. VERIFY
items open: GePG SP specification, mobile-money aggregator format, Beem/NextSMS send + delivery-report formats, gate
device firmware format, mobile-money push adapter (only console exists), LATE rule (cut-off vs start time), absence alert window (until 12:00), GFS codes, NECTA
scales, bell schedule, parent session length.

## Phase 5 — Facilities and student life (started 2026-10-23)

Scope (master prompt): hostel, transport, venues, discipline, clubs, library (+ health records from the design's
7.13–7.19 catalogue). The schema already enforces capacity (fn_capacity_guard: room, bus, venue seats, library copies),
venue overlap (EXCLUDE), one open accommodation request / allocation / transport assignment per student and term,
RESOLVED discipline needs a resolution, and health notes are encrypted. No seed user holds hostel_master,
transport_officer or librarian; school_admin holds every Phase 5 permission.

Decisions: transport and boarding fees reach the student's invoice — added as a CHARGE line (+ journal, last
installment grows) when the term's invoice already exists, otherwise picked up by invoice generation (route term fee;
optional BOARDING structure line for students with a room). Ending an assignment does not refund automatically.

- [x] P5.1 (`app/models/{facilities,student_life}.py` 16 models + 8 enums; migration 0007 audit on 14 tables + overdue index; full room/bus/copies and venue overlap mapped in services; templates now 16; drift 5/5) Models (16 tables) + enums; migration 0007: audit on accommodation requests, allocations, transport
      assignments, venue events, memberships, library books/loans; VENUE_CLASH error mapping; templates
      `discipline_notice`, `library_overdue`
- [x] P5.2 (`app/services/{hostel,facility_fees}.py`; gender rule; boarding = optional BOARDING structure line; `invoices.add_charges` grows the last installment) Hostel: hostels, rooms, accommodation requests (student or guardian), decide (approve → room, 422 full),
      vacate, occupancy; boarding charge
- [x] P5.3 (`app/services/transport.py`; stops replaced only when nobody rides; generation adds route fees) Transport: buses (plate check), routes + stops, assignments (bus full 422, route fee on the invoice), end,
      bus manifest
- [x] P5.4 (`app/services/venues.py`, `app/api/facilities.py` 18 routes; VENUE_CLASH 409, too_many_seats 422; tests 4/4) Venues and events: seats ≤ capacity, overlap 409, calendar
- [x] P5.5 (`app/services/student_life.py`, `app/api/student_life.py`; recorder or discipline.read updates; SMS key discipline:<id>) Discipline: record, update, resolve (resolution required), parent SMS (consent), student history
- [x] P5.6 (patron manages own club; /me/activities) Clubs: activities, patrons, memberships per year, student's own clubs
- [x] P5.7 (copies ≥ loans on update too; weekly key library:<loan>:<ISO week>; beat Mon–Fri 10:00; /me/loans) Library: books, loans (no copy 422), return, overdue list, overdue reminders (daily beat)
- [x] P5.8 (consent per student or all children; unreadable notes → null; tests 4/4; suite 175/175, 93 %) Health records: health.read/manage + HEALTH_DATA consent, encrypted notes, VIEW_SENSITIVE audit
- [x] P5.9 (`web/src/{StudentPicker,boarding}.tsx`; pages Hostel, Transport, Venues, Discipline, Clubs, Library, Health; student home: clubs, loans, boarding; parent: boarding per child; build 111.7 KB gz) Web: hostel, transport, venues, discipline, clubs, library; student/parent accommodation request, clubs
- [x] P5.10 (pytest **175/175**, coverage 93.1 %, Phase 5 services 87–100 %; Ruff clean; Playwright **17/17** incl. `e2e/phase5.spec.ts`: student asks for a bed → office opens a hostel, adds a room, approves → student sees the room; library lend/return; discipline record → resolve. Found: request button enabled before terms loaded (now disabled), occupancy not refreshed after a decision (fixed), the full E2E suite hits the per-IP login limit → E2E and CI run with SSMS_LOGIN_ATTEMPTS_PER_MINUTE=60) Tests (pytest PG16 as ssms_app, ≥ 80 %) + Playwright
- [x] P5.11 (12-api-design §12.6 Phase 5 notes (Example → §12.7), 16-test-plan Phase 5 results + E2E-7, 17-corrections §17.8 D28–D31 + C22–C26, ADR 0019 facility fees, ssms/README (scope, E2E login limit, counts), CI login limit, design README; links 95 + 19 OK) Docs: 12-api-design §12.6 Phase 5 notes, 16-test-plan, 17-corrections §17.8, ADR, README, PROGRESS

**PHASE 5 COMPLETE (2026-10-23).** Next: Phase 6 — Analytics, dashboards, compliance exports, performance tuning,
load test, deployment (master prompt). Read `design/adr/` (0019 for facility fees) and `design/12-api-design.md`
§12.3–12.6 first. VERIFY items open: GePG SP specification (and re-issuing a control number after a late facility
charge), mobile-money aggregator format and push adapter, Beem/NextSMS formats, gate device firmware, LATE rule,
absence alert window, GFS codes, NECTA scales, bell schedule, parent session length.

## Phase 6 — Analytics, compliance, performance, deployment (started 2026-10-23)

Scope (master prompt): analytics, dashboards, compliance exports, performance tuning, load test, deployment; plus
the 7.20–7.21 catalogue items still open (reports with export, data-subject requests). Docker is not installed on the
development machine: compose and images are validated statically, not run.

- [x] P6.1 (`app/services/reports.py`, `app/api/analytics.py`; money/staff reports also need finance/staff access; job file type by extension) Reports: `GET /reports/{type}` preview (enrolment, attendance, results, fees, staff, student-status,
      transactions; filters; ≤ 200 rows + total) and `POST /reports/{type}/export` (Idempotency-Key → EXPORT job,
      xlsx/csv/pdf, audited EXPORT)
- [x] P6.2 (`app/services/dashboards.py`, 60 s cache per school/role) Dashboards: `GET /dashboards/{admin|bursar|teacher}` KPI tiles + series (small, cached per school/minute)
- [x] P6.3 (`app/services/compliance.py`; one sheet per template; CSV/PDF one template) Compliance exports: `POST /compliance-exports` (templates enrolment by sex/age/class, attendance,
      results, staff — formats VERIFY with the ministry) → job, audited
- [x] P6.4 (`app/services/privacy.py` + DataSubjectRequest model; export JSON, anonymise keeps ledgers/results, active staff refused; tests 5/5) Privacy: data-subject requests (EXPORT → file of the subject's data; CORRECT; DELETE → anonymise while
      keeping ledgers/results), due dates (30 days VERIFY), overdue list
- [x] P6.5 (`scripts/synthetic.sql` 102 schools / 150k students / 3M attendance rows in 5 min; `scripts/explain.py` 14 hot queries as ssms_app under RLS: all < 50 ms warm, no large seq scans; chronic list rewritten to filter the week first (49 → 8 ms, and no longer grows through the year); no new index needed (user_id / supersedes_id already unique-indexed); suite 180/180, 93.2 %) Performance: synthetic multi-school data generator, EXPLAIN of hot queries, migration 0008 indexes, query
      count/size checks
- [x] P6.6 (`ssms/loadtest/{results_day,payment_burst,register_sync}.js` k6 with NFR thresholds; `scripts/loadtest.py` local runner. Local, one Windows API process: single read ≈ 40 ms; 20 concurrent readers 26 req/s p95 1.4 s (queueing in one process); signed callbacks 15.7 req/s p95 0.97 s (< 2 s met). Webhook limit now `SSMS_WEBHOOK_REQUESTS_PER_MINUTE` (600 → 6000: aggregators send bursts from few IPs). 500 req/s results day = VERIFY with k6 on Linux staging (workers × nodes)) Load test: k6 scripts (results-day spike, payment-callback burst, register sync) + a local runner; p95 report
- [x] P6.7 (`app/core/observability.py`: Prometheus per route template + multiprocess, Sentry with scrubbing, JSON logs; `/metrics` internal + token; compose: beat, backup, all settings, metrics dir; `ssms/ops/{prometheus,alerts}.yml`; `design/18-operations.md` runbook; 3 tests) Observability + deployment: /metrics (Prometheus), optional Sentry, compose (beat service, all settings,
      backups), runbook (TLS, backups + restore drill, upgrades, key rotation, alerts)
- [x] P6.8 (pages Dashboard (on Home; office/bursar/teacher, plain bars with values), Reports (preview, export job, compliance tab), Privacy (DSR list, export/anonymise/complete, new request via student + guardians), Audit (filters, cursor); build 119.2 KB gz) Web: role dashboards on Home, Reports (preview/export), Compliance, Privacy requests, Audit log
- [x] P6.9 (pytest **183/183**, coverage 93.1 %, Phase 6 services 86–99 %; Ruff clean; Playwright **19/19** incl. `e2e/phase6.spec.ts`: dashboard, report preview → CSV export job → download, DSR export → JSON download, audit shows the EXPORT) Tests (pytest PG16 as ssms_app, ≥ 80 %) + Playwright
- [x] P6.10 (12-api-design §12.7 Phase 6 notes (Example → §12.8), 16-test-plan Phase 6 results + E2E-8 + load/plan results, 17-corrections §17.9 D32–D36 + C27–C30, ADR 0020 observability, ADR 0021 anonymise, 18-operations runbook, ssms/README (scope, perf/load commands, env vars), design README; links 105 + 21 OK) Docs: 12-api-design §12.7, 16-test-plan, 17-corrections §17.9, ADRs, README, deployment guide, PROGRESS

**PHASE 6 COMPLETE (2026-10-27) — all six phases of the master prompt are built.** Final state: pytest 183/183
(93 %), Playwright 19/19, web 119 KB gz, 21 ADRs, design docs 01–18. Before go-live, close the VERIFY items: GePG SP
specification (signature, ACK codes, partial payments, re-issuing control numbers after late charges), mobile-money
aggregator contract and push adapter, Beem/NextSMS send and delivery-report formats, gate device firmware, ministry
compliance layouts, PDPA time limits (requests, breach notice), LATE rule and absence alert window, GFS codes, NECTA
scales, bell schedule, parent session length; and run the k6 staging tests (500 req/s results day) and the first
restore drill. Docker was not available on the development machine: build and start the stack once on Linux.

**Docker check (2026-10-27).** First real `docker compose` run (Docker Desktop 29.9, Compose v5): found and fixed
`migrations/sqlfile.py` crashing inside the image (source-checkout fallback used `parents[3]`, which `/app/migrations`
does not have). Local trial runs as project `ssms-local` with `ssms/.env.local` (development mode, demo seed, random
secrets) at http://localhost:8080. An older `ssms_db-data` volume from 2026-10-23 (unknown password) was left untouched.

**Design alignment (2026-10-31).** Eight changes from the first design doc, see 17-corrections §17.10; migration
`0008_design_alignment`. pytest 192/192 (93 %), Playwright 19 passed + 2 skipped (run on a Saturday, so the register and
parent tests skipped; re-run them on a weekday), web 120 KB gz. The scratch PostgreSQL in Temp was damaged during this work; tests now use
a throwaway container: `docker run -d --name ssms-test-pg --tmpfs /var/lib/postgresql/data -e POSTGRES_HOST_AUTH_METHOD=trust
-p 127.0.0.1:55433:5432 postgres:16.9-alpine` with `SSMS_TEST_ADMIN_URL=postgresql://postgres@127.0.0.1:55433/postgres`
(use 127.0.0.1, not localhost, or every connection stalls on IPv6).

**Normalisation pass (2026-10-31).** See 17-corrections §17.11 and ADR 0022; migration `0009_normalisation`. Redundant
columns removed, remaining copies tied with composite foreign keys, `tests/test_normalisation.py` now fails the build on new
redundancy. pytest 201/201 (93 %), Playwright 19 passed + 2 skipped (Saturday). Backup taken before migrating the local
stack: `ssms/backups/before-0009-2026-10-31.dump`.

**Locations and equipment (2026-10-31).** See 17-corrections §17.12; migration `0010_locations_equipment`. pytest 209/209
(93 %). Backup before migrating the local stack: `ssms/backups/before-0010-2026-10-31.dump`. Still to do before launch:
check the district list against PO-RALG.

**Browser tests date-independent (2026-10-31).** Start the API with `ssms/api/scripts/e2e_api.py` (fixed day 2026-10-21; CI
updated). Playwright 22/22, no skips, run on a Saturday.

**Frontend redesign (2026-10-31).** New look across all pages through the shared layer: `web/tailwind.config.js` (forest green, ochre, warm neutrals), `web/src/index.css` (controls, tables, empty lists), `web/src/ui.tsx`, `web/src/Shell.tsx` (grouped menu with `web/src/icons.tsx`), Login, Home, Dashboard. Fonts Figtree and Instrument Serif are self-hosted. Playwright 22/22, web 128 KB gz. Not done: dark mode; status words still show in English in the Kiswahili interface; wide tables scroll sideways on phones.

**Module layout (2026-10-31).** Ideas taken from the reference product at theschool-management.com/demo (studied from its public screenshots): one page per module (`web/src/pages/ModuleHub.tsx`, routes `/m/:key`) with a card and Open button per screen; the menu groups now fold, start open, and are remembered on the device (`web/src/nav.ts` drives the menu, the module pages and the title bar); a module launcher on Home; a title bar on every page with the module name, a short description and a Print button; the current academic year in the top bar; a letterhead and print rules so any page prints on A4 with the school name, year and date; a quick filter with a row count on the invoice list, class results and attendance report (`TableTools` in `web/src/ui.tsx`). Service worker cache v3. Playwright 22/22 on a freshly seeded database, web 131.9 KB gz. Not done: column sorting and paging inside tables, printable student ID cards, dark mode.

**Brief "Complete School Management System", Phases 1–2 (2026-10-31).** Reference: Weblizar School Management
(documentation, public demo signed in as Super Admin, Teacher, Accountant and Librarian, view only). Phase 1:
`design/19-reference-analysis.md` — role menus, gap analysis (about 70 % of the brief already built), 10 decisions where
the brief and SSMS differ (indigo theme adopted; Axios inside `api.ts`; Recharts lazy-loaded; no repository layer; GePG kept,
card gateways out of scope; super admin stays in the console), FR-72 to FR-99, NFR-16 to NFR-18. Phase 2:
`design/20-extension-architecture.md` and `design/sql/extension.sql` — 23 new tables (RLS forced, composite tenant keys,
audit), receptionist role, 18 permissions, API and web design, migrations 0011–0018 planned. Verified on PostgreSQL 16.9
(migrations to head + seed + extension), tests as `ssms_app`: 01_isolation 16/16, 02_integrity 27/27, new
`extension_tests.sql` 11/11; 4 Mermaid diagrams render. No application code changed. VERIFY: NECTA A-Level GPA,
card payments, virus scanner, NECTA centre-number format, PDPA 2022 on photos and ID cards.
Next: brief Phase 3 (environment additions) — see 20 §20.7.

**Extension Phase 3 — environment (2026-10-31).** Migration `0011_files` (`stored_files`: RLS forced, audit, random
storage key, size ≤ 20 MB); `/files` upload, read and discard (`app/api/files.py`, `app/services/files.py`): type read
from the content (PDF, JPEG, PNG, DOCX, PPTX, XLSX, MP3, MP4; Office files with macros refused), limit and upload
permission per purpose, readers = uploader or the purpose's read permission, 404 to everyone else and to other schools.
Web: Axios inside `api.ts` (same functions for every page), indigo theme (`#4F46E5`, sidebar `#1E1B4B`, background
`#F8FAFC`; chart pair `#4F46E5`/`#D97706` passes the palette validator), headings in Figtree (serif font removed),
`web/src/widgets.tsx` (`DataTable` with server pages and per-page sorting, used by the student list; `Modal`;
`useConfirm`, replacing `window.confirm` in Privacy). `design/sql/tests/03_extension.sql` moved to
`design/sql/extension_tests.sql` (the tests folder runs against the migrated database). Results: pytest 216/216
(93 %), ruff clean, Playwright 25/25 on a fresh seed, web 146.5 KB gz. Local stack migrated to 0011 after backup
`ssms/backups/before-0011-2026-10-31.dump`; service worker cache v4. Not done here (planned): email settings (phase 11),
S3 storage and virus scanner (phase 13, uploads are marked SKIPPED until then), `FileUpload` component (phase 5).
Next: Phase 4 — receptionist role, new permissions, session selector, dashboards per role.

**Extension Phase 4 — roles and session (2026-10-31).** Migration `0012_roles_extension`: `receptionist` role,
`bursar` shown as "Accountant (bursar)", 18 permissions granted as in design/20 §20.2 (taken unchanged from
`design/sql/extension.sql` §11, now removed there). Session selector (FR-72): the web sends `X-Academic-Year`
(`web/src/year.ts`, remembered per person on the device); `api.deps.apply_viewing_year` checks it belongs to the school
(another school's year → 422) and refuses every write with 409 `YEAR_READ_ONLY` while a non-current year is shown
(sign-in, password and inbox stay writable); `services/years.viewing_year` drives the student list, office dashboard
chart, receptionist dashboard and report defaults; the 12 pages using `useCurrentTerm` follow the chosen year; a banner
offers the way back. Dashboards (FR-73): librarian (stock, loans, overdue list) and receptionist (applications of the
year, admissions this month), chosen by permission; dashboard cache now keyed by year. Bug found by Playwright and
fixed: the page remounted when the year list loaded (key now follows the person's choice only). Results: pytest
223/223 (93 %), ruff clean, database tests incl. new `tests/03_roles.sql` R01–R03, Playwright 27/27 on a fresh seed,
web 148.1 KB gz. Local stack migrated to 0012 after backup `ssms/backups/before-0012-2026-10-31.dump`; service worker
cache v5. Open: create buttons stay visible while viewing another year (the server refuses the save with a clear
message); on phones the top-bar page name is cut short next to the year picker; upcoming exams, recent activity and
announcements on dashboards (FR-74) not yet done.
Next: Phase 5 — inquiries, calendar, staff attendance, leave, photos, CSV export.

**Extension Phase 5 — core administration (2026-10-31).** Migration `0013_front_office_staff` (admission_inquiries,
school_events, staff_attendance, leave_types, leave_requests; taken unchanged from `design/sql/extension.sql`, now
removed there; their database tests X02–X05 moved to `design/sql/tests/04_front_office.sql`). API:
`app/api/front_office.py` (inquiries with follow-up and convert-to-application, events by audience, staff register by
day and month, leave types, leave requests with yearly limits, decisions by another person, overlap → 409
`LEAVE_OVERLAP`), `app/api/exports.py` (students, staff, invoices, attendance as CSV; never encrypted or health fields;
audited `EXPORT`; formula cells prefixed), student photo routes (`PUT/GET/DELETE /students/{id}/photo`, PHOTO uploads
only). The normalisation guard flagged `admission_inquiries.class_id`; allowed with the reason "class first asked
about; the application may be for another". Web: pages Inquiries, Calendar, StaffAttendance ("Daftari la
wafanyakazi", so it does not collide with the student "Mahudhurio" link), Leave; `FileUpload` (photos shrunk in the
browser to 600 px JPEG) and `Tabs` in `widgets.tsx`; photo panel on the student profile; CSV buttons on Students,
Staff, Fees and attendance reports; upcoming events on every home page. Results: pytest 234/234 (93 %), ruff clean,
Playwright 31/31 on a fresh seed (one Phase 4 test made independent of row order), web 158.6 KB gz. Local stack
migrated to 0013 after backup `ssms/backups/before-0013-2026-10-31.dump`; service worker cache v6. Not done:
student leave is recorded and decided but does not yet pre-fill the class register; staff photos (no column yet, needed
for staff ID cards in phase 11); cancelling leave after it is approved.
Next: Phase 6 — study materials, homework, period attendance, monthly attendance sheet.

**Extension Phase 6 — academic (2026-11-01).** Migration `0014_teaching` (study_materials, study_material_streams,
homework, homework_streams, homework_submissions, from `design/sql/extension.sql`; test X09 moved to
`design/sql/tests/05_teaching.sql`). `period_attendance` dropped from the design: lesson attendance uses the existing
`attendance_sessions` of kind LESSON (stream taken from the slot, as migration 0009 requires). API `app/api/teaching.py`:
materials and homework limited to the teacher's teaching assignments (the office may target any stream); students and
parents see only their own; files served through the record that uses them; homework SMS to the primary guardian
(idempotency key shortened to fit VARCHAR(80), found by the tests); lesson register (slot teacher, slot weekday, inside
the term, not future, not a closed day); monthly sheet from the class register. Normalisation guard: two justified
entries for homework_submissions (the answer file, the marker). Web: pages Teaching ("Kazi na nyenzo"), Lessons
("Daftari la vipindi"), Learning ("Masomo yangu" for students and parents), monthly sheet tab on Attendance. Bugs found
by Playwright and fixed: a slower reply for an earlier date overwrote the staff register (now ignored), and saving a
lesson cleared the chosen lesson. Results: pytest 242/242 (93 %), ruff clean, Playwright 33/33 on a fresh seed, web
167.0 KB gz. Local stack migrated to 0014 after backup `ssms/backups/before-0014-2026-11-01.dump`; cache v7.
Not done: lesson registers do not raise parent absence SMS (only the morning register does); materials cannot be
re-targeted after publishing (delete and publish again).
Next: Phase 7 — candidate numbers, admit cards, exam timetable PDF, subject ranking, GPA (VERIFY).

**Extension Phase 7 — exams (2026-11-01).** Migration `0015_exams_extension` (exam_candidates; test X06 moved to
`design/sql/tests/06_exams.sql`). `app/api/exam_docs.py` + `app/services/exam_docs.py`: candidate numbering (class,
stream, name order; existing numbers kept), admit cards PDF (two per A4 page, with each class's papers, dates, times
and rooms), exam timetable PDF, `GET /portal/exam-sessions` and `/portal/admit-card.pdf` for students, subject
ranking by term and class from the current (unamended or amended) published results. Subject positions were
already computed at publishing; GPA is not computed until the NECTA A-Level rule is confirmed (VERIFY, design/19 D9).
Web: documents bar and a term picker on Exams (past terms' sessions were unreachable before), admit-card tab in
"Masomo yangu", subject ranking under class results. Results: pytest 248/248 (94 %) (one auth test failed only when
run with the browser-test login limit loaded in the shell; passes in a clean environment), ruff clean, Playwright 35/35
on a fresh seed, web 168.2 KB gz. Local stack migrated to 0015 after backup `ssms/backups/before-0015-2026-11-01.dump`;
cache v8. Next: Phase 8 — income and expenses, income statement, cash book, fines.

**Extension Phase 8 — accounting (2026-11-01).** Migration `0016_accounts`: finance_categories, cash_entries (guard
trigger: never edited or deleted), fine_rules, journal sources CASH_ENTRY/CASH_REVERSE, document type CASH_ENTRY, fee
item code FINE, and for every school the accounts 4060, 4800, 4810, 5000–5900 with seven default categories and the
FINE fee item (onboarding and `seed.sql` do the same; `pg_temp.finance_defaults` in the seed). Test X07 moved to
`design/sql/tests/07_accounts.sql`. API `app/api/accounts.py`: categories (account of the same kind), entries
posting balanced journals, reversal asked by the recorder and approved by someone else (mirror journal), income
statement (all income and expense accounts, fees included), cash book (cash, bank, mobile money; opening and running
balance), late fee rule and "charge now" (once per overdue invoice, through `invoices.add_charges`). Found by the tests
and fixed before release: the FINE fee code was not allowed by `ck_fee_items_code` (would have broken the live
migration; the test database had no schools at migration time, so the backfill did nothing there), and onboarding
runs as `ssms_platform`, which needed INSERT on finance_categories. Web: "Mapato na matumizi" page (entries,
income statement, cash book, fines). Results: pytest 254/254 (94 %), ruff clean, Playwright 37/37 on a fresh seed
(a 3.5-hour run was interrupted by the computer sleeping and was repeated), web 172.5 KB gz. Local stack migrated to
0016 after backup `ssms/backups/before-0016-2026-11-01.dump` (the first rebuild failed while offline; nothing changed
until the second succeeded); cache v9. Not done: waiving a fine.
Next: Phase 9 — library categories, publishers, cards and fines; driver details; printable transport and hostel reports.

**Extension Phase 9 — library, transport, hostel (2026-11-01).** Migration `0017_library_extension`
(library_categories, library_publishers, library_books.category_id/publisher_id, library_cards; document type
LIBRARY_CARD). Database tests L01–L02 in `design/sql/tests/08_library.sql`; the ID-card half of X10 stays in
`design/sql/extension_tests.sql` (restored after a script of mine dropped it while moving the library half).
API `app/api/library.py` + `app/services/library.py`: categories, publishers, card issuing (a stream or chosen
people, only those without a live card), revoking, cards PDF; lending accepts a card number; the return route fines a
late student return at the LIBRARY_DAY rate (after grace days) on their most recent invoice; `/fine-rules/{kind}`
now covers late-fee and library-day. Bus list carries the driver's name and phone (from the staff record). Web: Library
page (categories, publishers, cards, fine notice on return), Transport manifest filter by route and driver on each
bus, a library-fine form under Fines. Results: pytest 260/260 (94 %), ruff clean, Playwright 38/38 on a fresh seed.
Local stack migrated to 0017 after backup `ssms/backups/before-0017-2026-11-01.dump`; cache v10.
Not done: waiving a library fine (as for late fees); a separate printed hostel report (the occupancy page prints).
Next: Phase 10 — parent and student portals (homework, materials, events, admit and ID cards).

**Extension Phase 10 — portals (2026-11-01).** No migration. `GET /students/{id}/progress` (current term summaries:
average, points, division, class position out of the class; same audience as the results). Web: `pages/Progress.tsx`
(Progress, HomeworkDue); the parent page now shows each child's results (with report card), progress, homework not
handed in and month attendance; the student home adds homework due, progress and their own month attendance (the
`MonthView` of the parent page is reused). Test fix: the student-table browser test read the loading placeholders on a
slow run; it now waits for real rows (a front-desk test also timed out once in that run and passed alone and in the
repeat). Results: pytest 262/262 (94 %), ruff clean, Playwright 40/40 on a fresh seed. Deployed: the first rebuild
failed while offline; building the API image goes through the `migrate` service, and the web container had to be
restarted to reach the recreated API (502 until then); cache v11.
Next: Phase 11 — email channel, certificates, student and staff ID cards (staff photos), platform dashboard.

**Extension Phase 11 — email, certificates, ID cards, platform dashboard (2026-11-02).** Migration
`0018_documents_email` (certificate_templates, certificates with a trigger that freezes issued text, identity_cards,
email_messages, staff.photo_file_key; document types CERTIFICATE and ID_CARD; RLS on all new tables). Database tests
X08 and X10 in `design/sql/tests/09_documents.sql`. API `app/api/documents.py` with `app/services/documents.py` and
`app/services/email.py`: certificate templates with placeholders (an unknown placeholder is refused), certificates
numbered `CT-YYYY-nnnnnn`, revoked once with a reason and printed with a REVOKED mark; ID cards `ID-YYYY-nnnnnn` for a
stream (valid to the year end) or the staff (one year), eight per A4 page with photo and a QR holding only the card
number; staff photographs; `GET /portal/id-card.pdf` for students; email through a console or SMTP adapter, queued only
for users with an address, sent once by the `email.send` task, with history and a test message; announcements take
`send_email`; `GET /platform/dashboard` returns counts only. Web: "Nyaraka" page (certificates, ID cards, staff photo
upload), email option and email history on Announcements, "Kitambulisho changu" on the student home, `/console` page
for platform operators (own sign-in, token kept in memory). Design alignment asked for by the user
(https://wpschool.weblizar.com/): a public front page at `/` following the reference's front-page structure (hero
with glow, stats bar, module tabs, role cards) in our own words and colours; it shows no demo passwords. Sign-in moved
to `/login` (any signed-out deep link still shows it; `?as=parent` opens the parent tab), and the shared tabs became the
reference's segmented control. Found by the tests: selects inside their label need an aria-label (as before). My e2e
runner script first started the API on the wrong port and without `E2E_API_LOG`; fixed, not a product fault.
Results: pytest 268/268 (94 %), ruff clean, Playwright 45/45 on a fresh seed, web 185.1 KB gz. Local stack migrated to
0018 after backup `ssms/backups/before-0018-2026-11-02.dump`; cache v12; new routes checked live.
Not done: the web page has no upload for a certificate background (the API accepts one); real SMTP needs the
school's mail settings (`SSMS_EMAIL_PROVIDER=smtp`, `SSMS_SMTP_*`).
Next: Phase 12 — full regression, security review of uploads and exports, load test of the results day.

**Extension Phase 12 — testing, security and bug fixing (2026-11-02).** No migration. Security review in
`design/21-security-review.md`: each item of the brief's §8 traced to its control and a test; missing tests written
first in `tests/test_security_review.py` (10: every route needs a sign-in, swept over the whole OpenAPI document; no
response schema carries a secret; CORS; SQL injection through search; spreadsheets; files in use; Phase 11 cross-school;
https-only links; the production settings guard; email off in production without SMTP). Fixed: F1 formula injection in
report CSV/XLSX, import and compliance workbooks (`app/core/sheets.py` now used by every spreadsheet); F2 discarding a
file still used by a photo, homework, material, receipt or certificate background (409 FILE_IN_USE); F3 console email
marked SENT in production (email now off unless SMTP; SMTP without host stops the start); F4 axios 1.7.9 → 1.20.0;
F5 react-router-dom 6.28.0 → 6.30.6 (two moderate advisories left, fixed only in v7, not reachable here); F6 build
contexts limited by `api/Dockerfile.dockerignore` (allowlist) and `web/.dockerignore`. pip-audit of the API image: no
known vulnerabilities. My own slips caught on the way: the first route sweep passed while checking nothing (FastAPI
0.162 keeps included routers unflattened; the sweep now reads the OpenAPI paths and asserts it checked > 300), and a
variable named `sheets` in compliance.py hid the new module (ruff and the existing compliance test caught it).
Load test: new `results-day` scenario in `scripts/loadtest.py`; inside the Docker network, 2 API workers, 20/50/100
students: 70/64/63 req/s, p95 0.56/1.23/2.15 s, no errors. From Windows the port forwarding halved throughput; 4
workers did not help on one laptop; drawing report cards in a thread made no difference and was not kept.
Results: pytest 278/278 (94 %), ruff clean, Playwright 45/45 on a fresh seed, web 190.1 KB gz (newer axios and router). Deployed (no migration), cache v13.
Not done (design/21 §21.4): virus scanning of uploads; k6 results-day run on staging (VERIFY); react-router 7; UAT per
role with school staff.
Next: Phase 13 — Docker configuration and deployment.

**Extension Phase 13 — Docker configuration and deployment (2026-11-02).** No migration. API: `S3Storage` beside
local storage (`app/core/storage.py`, boto3); ClamAV scan before an upload is stored (`app/core/scanner.py`: infected
refused, scanner down refuses the upload; production needs a scanner or `SSMS_ALLOW_UNSCANNED_UPLOADS=true`); `python -m
app.cli deploy-check`. Compose: restart policies, log rotation, health checks that fit each service, email/storage/
scanner settings, profiles `edge` (Caddy HTTPS), `antivirus` (ClamAV), `objects` (SeaweedFS; MinIO no longer publishes
free images). Scripts: `ops/gen-secrets.sh`, `ops/restore-drill.sh`, `ops/install-drill.py`. CI: S3 store for the storage
tests and an `images` job (compose, Caddyfile, scripts, builds, non-root, security headers). Runbook design/18 updated
(new section 18.10). A production-mode install drill from empty volumes found F7-F11 (design/21), all fixed: forged client
address; no CSP or framing headers on pages (a Phase 12 claim corrected); console lost its database role after a
rollback; backups slipped and the first one was empty; nginx kept the API's old address, and uploads over 11 MB failed.
Results: pytest 285/285 with live S3 (94 %), ruff clean, Playwright 45/45 run alone on a fresh seed, install drill 12/12,
restore drill passed in 54 s, browser walk under the CSP clean, web 190.1 KB gz. Local stack redeployed; no cache bump (the
app bundle did not change). Two earlier browser runs do not count: one competed with pytest (my scheduling), during the
other the computer slept and Docker Desktop stopped.
Not verified: real Let's Encrypt certificate (the drill used Caddy's internal CA), real GePG, SMS and SMTP (placeholders
or console), the new CI jobs (no git remote has run them; their steps were run by hand except the live header step's
container form), k6 on server hardware. Not done: off-host backup copies, backup of uploaded files, react-router 7, UAT per
role with school staff.
All 13 phases of the brief are complete.

**Go-live preparation (2026-11-02 to 2026-11-12).** Asked to finish the open items of Phase 13. Done and tested:
off-site backups (profile `offsite`, `ops/offsite.sh`, rclone 1.75.2: daily, encrypted contents and names, verified
with cryptcheck, files never deleted off-site, dumps kept 90 days; restore gave a byte-identical dump read by
pg_restore, byte-identical files from the volume and from an S3 store, ciphertext only in the store, nothing with a
wrong passphrase); react-router 7.18.4 (`npm audit`: 0); the CI header step run as the runner does (it was flaky as
written: `head` and `grep -q` in pipes under pipefail; fixed, 5/5 passes and a clean failure without the headers);
email against a real SMTP server (Mailpit, STARTTLS and implicit TLS) after fixing F12 (certificate not verified,
no Date/Message-ID, password possible without TLS), live tests also in CI; F13 password hashing moved off the event
loop (measured before/after); k6 results-day script updated (progress, report-card PDF, settings, no sign-in retry
storm) and run against the local stack; UAT checklist extended for the extension roles (design/16), each item
checked against the code (two wrong items removed: there is no visitor log, and the receptionist cannot mark the
staff register); go-live checklist design/18 §18.11. Results: pytest 289/289 with live S3 and SMTP (94 %), ruff
clean, Playwright 45/45 run alone, CSP walk clean, restore drill passed on the day's backup, web 195.6 KB gz,
cache v14. Interruptions: the computer was off between sessions (Docker Desktop restarted; the stack came back by
itself) and the scratchpad was cleared, so the test environment was rebuilt.
Not possible from here and listed in §18.11: a real certificate (needs a domain and server), live SMS and GePG
(accounts and the providers' specifications: VERIFY items), a run of CI on GitHub (no repository), the k6 run on
server hardware, UAT with school staff.

**Role cards lead to each role's own pages (2026-11-12).** Reported: choosing "Mkutubi" (or staff, parent) on the
front page and signing in always showed the administrator's pages. Cause: the demo data had no librarian,
receptionist or parent account that could sign in, so every card ended in `admin`; and the cards all went to the
same sign-in without saying which role was meant. Fixed: demo accounts `librarian`, `reception`, `mzazi` in
`design/sql/seed.sql` (and created on the local stack through the staff API); each card opens the sign-in with
"Unaingia kama: <role>"; after sign-in that role's dashboard is shown first, and if the account lacks the role the
home page says so with a button to sign in with another account (`web/src/chosenRole.ts`); the parent tab offers
username and password sign-in. Test `e2e/rolecards.spec.ts` (8): every card lands on its role's home page, and the
mismatch notice; passed on a fresh seed and on the local stack through nginx. Full browser suite 53: 52 passed in the
run where one new test failed on a test mistake (an English-speaking teacher account); that test was fixed and the
role-card file re-run (8/8). pytest 285 passed (4 live tests skipped: test servers off). Cache v15.
**Own database on Windows; library copies connected (2026-11-17).** Asked to connect the app to a database made in
pgAdmin (`smart_school_db`, PostgreSQL 18 on Windows) so everything is recorded there without losing data, and to fix
parts that did not work together. Added `ssms/api/scripts/setup_database.py` (refuses a database holding another
program's tables, pg_dump backup before upgrading existing SSMS data, `.env` secrets written once and kept, migrations,
`db-logins`, check as `ssms_app`), `scripts/run_api.py` (selector loop for Windows), `ssms/windows/setup.bat` and
`start.bat`, and `ssms/CONNECT-DATABASE.md`; the root README now points to `ssms/` (the `backend/`, `db/`, `docs/`
version 1 has a different schema). Found by the full suite and a frontend-to-route cross-check (every web call
matches a route): migration 0019 added library copies but the API still lent by book, so books added later had no
copies, new loans no copy, and a loan's copy could belong to another book (`test_normalisation` failed). Migration
0020 adds the composite key (copy of the loan's book), keeps copies in step with a book's count (surplus marked
WITHDRAWN, never deleted), gives each new loan a free copy, and back-fills: on the seeded database the book went from
0 copies to 3 and its loan got a copy, other counts unchanged. Tests `test_library_copies.py` (3). Results on
PostgreSQL 16.15 (18 not installable here; schema checked for 18 differences, none found): pytest all passed
(4 live tests skipped), web typecheck and build clean; setup script run on an empty, a foreign and an existing
database; API started with the written `.env`, sign-in, book and loan through the API and the web proxy, rows
checked in the database.
