# 16. Test Plan

## 16.1 Strategy

| Level | Tool | Scope | Gate |
|---|---|---|---|
| Database | SQL test files in [sql/tests/](sql/tests/), run **as `ssms_app`** | Tenant isolation, resolvers, every DB rule (F3–F9, clashes, capacity, audit) | 100 % pass on PostgreSQL 16 in CI |
| Unit | pytest + factory-boy | Services: grading maths, allocation order, scheduler, phone normalisation, encryption, templates | ≥ 80 % coverage on services |
| Integration / API | pytest + httpx AsyncClient against PostgreSQL 16 and Redis (testcontainers) | Every endpoint in [12-api-design.md](12-api-design.md): auth, permissions, tenancy, error format, idempotency | All pass; contract snapshot of OpenAPI |
| End-to-end | Playwright (Chromium + Android emulation, network throttled to 3G, offline mode) | Login, offline marks → sync, publish results, enrolment, pay fee | All pass on every merge to main |
| Load | k6 | Results-day spike (5,000 parents), payment callbacks (50/s), absence fan-out (300 schools) | p95 < 1 s, errors < 0.5 %, callback ACK < 2 s |
| Security | OWASP ZAP baseline, `pip-audit`/`npm audit`, Trivy; manual tests of IDOR across schools | No high findings |
| UAT | Checklists per role (16.5) in two pilot schools (one secondary, one primary) | Signed by the head teacher of each |

**Test data.** [sql/seed.sql](sql/seed.sql) holds two schools. School A, *Shule ya Sekondari Mfano*, has O-Level + PCM, 8 students, published Form II results, payments over five channels including a reversal and an overpayment, attendance with a chronic absentee, and an SMS log. School B, *Shule ya Msingi Upendo*, is a primary school. The schools share a username, a cash receipt number and a guardian phone on purpose. Every demo password is `Mfano@2026`.

## 16.2 Database test results (Phase 0)

Run with `psql -v ON_ERROR_STOP=1 -d ssms_test -f design/sql/tests/01_isolation.sql` (then `02_integrity.sql`) after the schema and seed. In this Phase 0 run they executed on **PGlite (PostgreSQL 18 WASM build)**, connected as `ssms_app` (NOSUPERUSER, NOBYPASSRLS). Each block ran in its own savepoint.

**Result: 43 passed / 0 failed.** Re-run on **real PostgreSQL 16.9** in Phase 1: first via psql (found D10, fixed), then from pytest after `alembic upgrade head` + seed (`tests/test_schema.py`): **43/43 PASS**. CI runs them on every push (`.github/workflows/ssms-ci.yml`).

| ID | Rule proven | Result |
|---|---|---|
| I01 | Tests run as `ssms_app`, not superuser, no BYPASSRLS | PASS |
| I02 | No `app.school_id` → 0 rows in all 95 RLS tables | PASS |
| I03 | School A context sees only school A rows in every table | PASS |
| I04 | School B rows invisible by id | PASS |
| I05 | Cross-school UPDATE affects 0 rows | PASS |
| I06 | Cross-school INSERT rejected (RLS WITH CHECK) | PASS |
| I07 | Composite FK blocks pointing an A row at a B row | PASS |
| I08 | No DELETE on business tables; no access to `platform_admins` | PASS |
| I09 | Same username in two schools resolves per school | PASS |
| I10 | F3: `external_ref` unique per school and channel (same ref in both schools) | PASS |
| I11 | `resolve_school_by_code` returns ids only, opens no table access | PASS |
| I12 | `resolve_device` | PASS |
| I13 | `resolve_gepg_bill` by control number and bill ref | PASS |
| I14 | `resolve_refresh_token` | PASS |
| I15 | `resolve_users_by_phone`: parent in 2 schools → 2 rows; staff phone → 0 | PASS |
| I16 | SECURITY DEFINER functions executable only by owner and `ssms_app` | PASS |
| T01–T03 | Teacher, room and stream double-booking rejected | PASS |
| T04 | Back-to-back periods allowed | PASS |
| T05 | One enrolment per student per year | PASS |
| T06 | One absence alert and one SMS per student per day | PASS |
| T07 | Hostel room capacity | PASS |
| T08 | Venue bookings cannot overlap | PASS |
| F4a | Score above component maximum rejected | PASS |
| F4b | Draft edit increments version; published marks locked | PASS |
| F4c | Firewall lists missing marks and weights ≠ 100 | PASS |
| F4d | Publishing an incomplete class → SQLSTATE `SS422` | PASS |
| F4e | Complete class publishes (division computed); second publish refused | PASS |
| F5a | Unbalanced journal rejected at commit | PASS |
| F5b | Balanced journal accepted; ledger append-only | PASS |
| F5c | All seeded journals balance | PASS |
| F6a | Invoice totals/paid/status derived; overwrite ignored | PASS |
| F6b | Over-allocation, pending payment, other student's invoice rejected | PASS |
| F6c | Reversal restores the balance; amount/status/delete/self-approval rejected | PASS |
| F6d | Paid invoice not cancellable; unpaid invoice cancellable | PASS |
| F6e | Overpayment held as student credit (view and ledger 2100) | PASS |
| F7a | Published results and summaries frozen | PASS |
| F7b | New version without an approved amendment rejected | PASS |
| F7c | Maker cannot approve; checker creates version 2; version 1 kept | PASS |
| F9a | Audit row has school, actor, request id, before/after | PASS |
| F9b | No `*_enc`, `*_hash` or `password_hash` keys in any audit row | PASS |
| F9c | `audit_logs` append-only | PASS |

## 16.3 Test cases per use case

Format: ID · input · expected output. "DB" = also covered by a database test above.

| ID | Use case | Input | Expected |
|---|---|---|---|
| TC-01-1 | UC-01 | mfano-sec / admin / correct password | 200; JWT `sch` = school A; cookie set; audit LOGIN |
| TC-01-2 | UC-01 | wrong password; unknown user | identical 401 bodies; failed count + 1 |
| TC-01-3 | UC-01 | 5 wrong then correct | 423 with `locked_until` |
| TC-01-4 | UC-01 | replay a rotated refresh token | 401; whole family revoked; audit TOKEN_REUSE |
| TC-01-5 | UC-01 | school A token, GET `/students/{B id}` | 404 (RLS) — DB I04 |
| TC-02-1 | UC-02 | phone 0754000021 | one SMS; two schools to choose; tokens for the chosen school |
| TC-02-2 | UC-02 | unknown phone | "code sent", no SMS, no row |
| TC-02-3 | UC-02 | 6 wrong codes | 5th attempt invalidates; 429 after 3 requests in 15 min |
| TC-03-1 | UC-03 | new school code | school + admin + defaults; code reuse → 409 |
| TC-04-1 | UC-04 | 500-row XLSX, 1 bad phone in row 37 | job FAILED; nothing saved; error report row 37 E03 |
| TC-04-2 | UC-04 | same file + same Idempotency-Key | same job returned |
| TC-05-1 | UC-05 | suspend ACTIVE student with reason | 200; history row; guardian SMS |
| TC-05-2 | UC-05 | GRADUATED → ACTIVE | 409 `NOT_ALLOWED` |
| TC-05-3 | UC-05 | promote Form II 2026 | new 2027 enrolments in Form III; repeaters stay |
| TC-06-1 | UC-06 | apply F1, upload .exe renamed .pdf | 422 E10 |
| TC-06-2 | UC-06 | second application same year | 409 |
| TC-06-3 | UC-06 | submit with a missing required document | 422 listing requirements |
| TC-07-1 | UC-07 | INVALID without comment | 422 (DB CHECK) |
| TC-07-2 | UC-07 | one INVALID | application → REQUIREMENTS_PENDING; SMS with comment |
| TC-08-1 | UC-08 | approve into a full stream | 409 E15 (DB capacity) |
| TC-08-2 | UC-08 | approve | admission no. gapless; ACTIVE; enrolment; invoice; SMS |
| TC-09-1 | UC-09 | teacher clash | 409 naming the slot — DB T01 |
| TC-09-2 | UC-09 | two admins save the same slot at the same time | one 201, one 409 (EXCLUDE) |
| TC-09-3 | UC-09 | auto-generate Form II | draft with zero clashes; unplaced list |
| TC-10-1 | UC-10 | register offline, close app, reopen online | records synced, none lost |
| TC-10-2 | UC-10 | same record from two phones | last `captured_at` wins; other shows Conflict |
| TC-11-1 | UC-11 | 08:30 on a school day; Baraka absent | one SMS — DB T06 |
| TC-11-2 | UC-11 | 08:30 on 26/04 (Union Day) | no SMS |
| TC-11-3 | UC-11 | tap with unknown device key | 401 |
| TC-12-1 | UC-12 | score 120 (max 100) | 422 E12 — DB F4a |
| TC-12-2 | UC-12 | stale version | 409 with server value |
| TC-13-1 | UC-13 | publish F5 with missing marks | 422 `INCOMPLETE_GRADES_BLOCK` with all 9 rows in sw/en — DB F4c/F4d |
| TC-13-2 | UC-13 | publish complete class | frozen results; positions with ties; PDFs job; SMS — DB F4e |
| TC-14-1 | UC-14 | requester approves own amendment | 403 — DB F7c |
| TC-14-2 | UC-14 | admin approves | version 2; report card shows "Imerekebishwa" |
| TC-15-1 | UC-15 | generate term invoices for Form II with sibling discount | totals = lines − discounts; journal balanced |
| TC-16-1 | UC-16 | GePG callback twice | one payment; both ACK — DB I10 |
| TC-16-2 | UC-16 | bad signature | 401 + alert; no row |
| TC-16-3 | UC-16 | callback ACK time under load | < 2 s p99 |
| TC-16-4 | UC-16 | payment > balance | allocation = balance; rest credit 2100 — DB F6e |
| TC-17-1 | UC-17 | cash with reused receipt-book no. | 409 E19 |
| TC-17-2 | UC-17 | bank officer confirms deposit | payment created, MATCHED, receipt |
| TC-18-1 | UC-18 | reversal requested and approved by the same user | 403 — DB F6c |
| TC-19-1 | UC-19 | statement with one missing payment | run EXCEPTIONS; item MISSING_IN_SYSTEM |
| TC-20-1 | UC-20 | announcement with SMS when credit is low | 422 "Salio la SMS halitoshi" |
| TC-21-1 | UC-21 | allocate 5th bed in a 4-bed room | 422 E15 — DB T07 |
| TC-22-1 | UC-22 | overlapping venue booking | 409 — DB T08 |
| TC-24-1 | UC-24 | parent opens another family's child | 404 |
| TC-25-1 | UC-25 | export enrolment report | job; file; audit EXPORT |
| TC-26-1 | UC-26 | DSR export for a guardian | ZIP of the guardian's and children's data within due date |

## 16.4 Automated suites (Phase 1+)

**Phase 1 results (2026-10-22, PostgreSQL 16.9, runtime role `ssms_app` via `SET ROLE` from a login without privileges):** pytest **96/96 pass**, coverage **93 %** (services 83–100 %, floor 80 % enforced). Playwright **6/6 pass** against uvicorn + `vite preview`.

| Suite | Tests | Proves |
|---|---|---|
| `ssms/api/tests/test_auth.py` | 21 | login, enumeration-safe errors, lockout, rate limits, refresh rotation + reuse detection, logout, password change, parent OTP (one and two schools), SMS task idempotency, audit events |
| `test_platform.py` | 8 | console TOTP, token audiences, school list cursor, onboarding defaults, suspension blocks users, isolation of new schools |
| `test_people.py` | 24 | cross-school 404, permissions, admission + enrolment + consent, guardian reuse and masking, validation codes, STREAM_FULL, status transitions, audited identifiers, users/roles, staff lifecycle, settings |
| `test_imports.py` | 10 | templates, upload checks, Idempotency-Key replay/mismatch, all-or-nothing with error report, capacity and duplicates, guardians and staff imports, rollback on write failure, job privacy, audit API |
| `test_core.py` | 24 | uuid7, phones, AES-GCM rotation + field binding, JWT types/audiences, Argon2id, cursor tampering, rate limits, i18n, storage key safety, headers, 500 format |
| `test_sms.py` | 4 | Beem/NextSMS payloads (mock HTTP), transient vs permanent failures |
| `test_schema.py` | 5 | models ↔ database drift, enums ↔ CHECK lists, `ssms_app` cannot see `platform_admins`, Phase 0 SQL suites |
| `ssms/web/e2e/phase1.spec.ts` | 6 | sw/en login, server error text, admit student, forced password change, failing then passing import, parent OTP login |

**Phase 2 results (2026-10-23, PostgreSQL 16.9, same rules):** pytest **131/131 pass**, coverage **93 %**
(floor 80 %), Ruff lint + format clean; Playwright **9/9** (6 Phase 1 + 3 Phase 2).

| Suite | Tests | Proves |
|---|---|---|
| `test_academics.py` | 11 | one current year, terms inside the year without overlap, promotion paths, stream capacity vs enrolled, curriculum replace, combinations (soft delete), grading-scheme versions and band gaps, component guards once marks are locked |
| `test_enrolment.py` | 5 | public offerings, full application → documents (type/size checks) → submit → validate → approve with STREAM_FULL rule and SMS, reject, parent applies and sees only own, promotion repeat/promote/graduate |
| `test_timetable.py` | 9 | teacher/room/stream clashes, assignment, curriculum, room type/capacity and teacher-load problems, ETag 304, generator draft of 64 lessons without clashes and saved, unplaced reasons, exams in session/term with clashes |
| `test_marks.py` | 3 | own-assignment sheet, versions/conflicts/locks/out-of-range per item, Excel template + all-or-nothing upload |
| `test_results.py` | 7 | bilingual firewall = 422 details, publish (idempotent), report-card job + consented SMS, class results paging, guardians see only their children, comments rules, maker-checker amendments and versions, analytics |
| `web/e2e/phase2.spec.ts` | 3 | marks typed offline sync when back online; firewall clear → publish → report-card PDF download; timetable grid + live check |

**Phase 3 results (2026-10-23, PostgreSQL 16.9, same rules):** pytest **150/150 pass**, coverage **93 %**
(finance services 81–96 %, floor 80 %), Ruff clean; Playwright **11/11** (6 + 3 + 2 Phase 3). After every money
test `tests/finance_helpers.assert_books_balance` checks that each journal balances and that, per student, account
1300 equals the open invoice balances and account 2100 equals the unallocated payments.

| Suite | Tests | Proves |
|---|---|---|
| `test_finance_seed.py` | 1 | the seed books already satisfy the ledger invariants |
| `test_finance.py` | 18 | fee items and structures (approve needs settings.update, approved is frozen, archive), discounts, Term Two generation with installments and credit, a class without an approved structure fails the run and bills nobody, cancel + PDF access, cash payment with receipt and SMS, duplicate reference 409, Idempotency-Key replay, reversal maker-checker, bank deposit confirm/reject, GePG signed bill response + payment (tampered body and DOCTYPE → 401, repeat → one payment), mobile callbacks (bad signature, unknown reference, duplicate), push, reconciliation (matched, mismatch, missing both ways, resolve), aging/defaulters/collections + XLSX, reminders once per installment, payments immutable in the database, amounts in words (sw/en), parent children |
| `web/e2e/phase3.spec.ts` | 2 | bursar records cash → receipt number + PDF, duplicate refused; parent (SMS code) sees the statement with that receipt, no reversal button, pay prompt offered |

**Phase 4 results (2026-10-23, PostgreSQL 16.9, same rules):** pytest **167/167 pass**, coverage **93 %**
(Phase 4 services 87–98 %, floor 80 %), Ruff clean; Playwright **14/14** (6 + 3 + 2 + 3 Phase 4).

| Suite | Tests | Proves |
|---|---|---|
| `test_attendance.py` | 6 | my streams, empty register, ETag 304, weekend; sync idempotent, later mark wins, older = conflict, close; per-item errors (not enrolled, forbidden stream, future, too old, Sunday) and 403 without attendance.take; stream report + XLSX + bad range, chronic list, parent sees only own child; gate taps present/late/duplicate/unknown/not school day/out of window, wrong key 401, school B key cannot reach school A cards; devices (key once, rotate, disable → 401), cards (replace, card_in_use 409, lost) |
| `test_sms_alerts.py` | 4 | DEBIT per segment, SKIPPED without credit, sign-in code never blocked; low-credit notice once, REFUND on permanent failure, credit rows cannot be updated; delivery reports (token, DELIVERED never undone); absence alerts (before cut-off nothing, register ABSENT, gate in use + no tap, never twice, after 12:00 nothing) |
| `test_communication.py` | 5 | stream announcement + SMS job (Idempotency-Key, replay, recipients, job counts), credit refused before saving, feed per audience (parents, other parents, staff, authors, future, delete), individual → inbox (read, not mine 404, read all), templates (placeholders, 3-SMS limit, fixed sign-in text), SMS log masked, credit, console top-up |
| `test_portal.py` | 2 | parent children with today's mark and gate time (< 5 KB), month attendance, other child 403; student home, timetable, own attendance only |
| `web/e2e/phase4.spec.ts` | 3 | class teacher marks the register offline (all present + one absent) → synced after reconnect → gate tap time shown → register closed; announcement to parents; parent (SMS code) sees today's mark, the month view and the announcement, no staff menu |

**Phase 5 results (2026-10-23, PostgreSQL 16.9, same rules):** pytest **175/175 pass**, coverage **93 %**
(Phase 5 services 87–100 %, floor 80 %), Ruff clean; Playwright **17/17** (6 + 3 + 2 + 3 + 3 Phase 5; the E2E API runs with
`SSMS_LOGIN_ATTEMPTS_PER_MINUTE=60` because the suite signs in more than 30 times a minute from one IP).

| Suite | Tests | Proves |
|---|---|---|
| `test_facilities.py` | 4 | hostel + room (duplicate name 409), guardian request for own child only, duplicate open request 409, student self-request, wrong gender 422, approval → room + BOARDING line on the invoice + balanced books, no invoice yet → billed later, room full 422, reject, occupancy, vacate; cancel and re-request; bus plate rule, duplicate plate, route with ordered stops, stop of another route 422, assignment → route fee on the invoice + balanced books, bus full 422, second assignment 409, seats, stops locked while used, end, manifest, 403; venue overlap 409, too many seats 422, back-to-back allowed, move into a clash 409, calendar, cancel, 403 |
| `test_student_life.py` | 4 | incident + guardian SMS (template, once), no-SMS option, resolution required, only recorder or office edits, RESOLVED final, history, 403; patron manages own club, duplicate member 409, other teacher 403, club creation needs activities.manage, student's clubs; loans by admission no., default due date, no copies 422, copies below loans 422, return, overdue list, weekly reminder once, borrower's loans; health records: consent, encryption round trip, VIEW_SENSITIVE audit per read, no consent 403, teacher 403 |
| `web/e2e/phase5.spec.ts` | 3 | student requests a bed → office creates a boys' hostel and room, approves → occupancy and the student's page show the room; librarian lends and takes back a book; teacher records and resolves an incident |

**Phase 6 results (2026-10-27, PostgreSQL 16.9, same rules):** pytest **183/183 pass**, coverage **93 %**
(Phase 6 code 86–99 %, floor 80 %), Ruff clean; Playwright **19/19** (Phases 1–6).

| Suite | Tests | Proves |
|---|---|---|
| `test_analytics.py` | 5 | report previews with filters and totals, results need a term, bad range 422, money/staff reports need finance/staff access; CSV and PDF exports through the job (idempotent, audited, right file type); dashboards per role and 403s; compliance workbook (one sheet per template, every student counted once, CSV with two templates 422); data-subject export JSON, anonymisation (identity, login and consents gone), active staff refused, CORRECT completed with a note, overdue flag |
| `test_observability.py` | 3 | `/metrics` labels by route template (never the raw id) and honours the token; JSON log lines; Sentry events lose bodies, cookies, query strings, auth and signature headers |
| `web/e2e/phase6.spec.ts` | 2 | head teacher dashboard → report preview → CSV export → download; privacy export → JSON download → audit log shows the EXPORT |

Examples planned for later phases:

**pytest:**

```python
# File: backend/tests/test_tenancy.py (Phase 1)
async def test_school_a_token_cannot_read_school_b_student(client, token_school_a, school_b_student_id):
    r = await client.get(f"/api/v1/students/{school_b_student_id}", headers=token_school_a)
    assert r.status_code == 404
    assert r.json()["error_code"] == "NOT_FOUND"

async def test_publish_blocked_lists_every_missing_mark(client, admin_a, term1, form5):
    r = await client.post("/api/v1/results/publish", json={"term_id": term1, "class_id": form5},
                          headers=admin_a | {"Idempotency-Key": "pub-f5-t1"})
    assert r.status_code == 422 and r.json()["error_code"] == "INCOMPLETE_GRADES_BLOCK"
    assert {d["problem"] for d in r.json()["details"]} >= {"MISSING_MARK"}
```

**Playwright scenarios** (Android emulation, 3G throttling):

| Scenario | Steps | Pass |
|---|---|---|
| E2E-1 Login | staff login, wrong password, lock, parent OTP with school choice | correct screens and messages in sw and en (**Phase 1: done**) |
| E2E-2 Offline marks | go offline → enter 20 marks → reload → go online | all 20 synced, badges correct (**Phase 2: one mark offline → online → synced**) |
| E2E-3 Publish results | firewall list → fix → publish → parent sees results + PDF | report card downloadable (**Phase 2: done**) |
| E2E-4 Enrolment | apply → upload → teacher invalidates one → re-upload → admin approves | admission number SMS logged |
| E2E-5 Pay fee | invoice with control number → simulated GePG callback → receipt | balance updated, receipt PDF (**Phase 3: bursar cash → receipt PDF; parent statement shows it; GePG callback covered by pytest**) |
| E2E-6 Register and alerts | teacher marks the register offline → online → synced; gate tap; parent home | register synced, gate time shown, parent sees today's mark (**Phase 4: done; absence SMS covered by pytest**) |
| E2E-7 Student life | student asks for a bed → office opens a hostel, adds a room, approves; library lend/return; discipline record → resolve | room shown to the student, copies and lists updated (**Phase 5: done**) |

| E2E-8 Reports and privacy | dashboard → report preview → CSV export → download; data-subject export → JSON; audit shows the export | files downloaded, request COMPLETED (**Phase 6: done**) |

**k6 load** (scripts in `ssms/loadtest/`, run against staging): results-day spike to 500 req/s (p95 < 300 ms, errors
< 0.5 %), signed payment-callback burst 100/s with repeats (p95 < 2 s, every repeat DUPLICATE), morning register
sync (p95 < 800 ms). **Phase 6 local run** (one Windows API process, `scripts/loadtest.py`): single read ≈ 40 ms;
20 concurrent readers 26 req/s, p95 1.4 s (queueing in one process); callbacks 15.7 req/s, p95 0.97 s. The 500 req/s
target is **VERIFY on Linux staging** with several workers and hosts ([18-operations.md](18-operations.md)).

**Query plans** (`scripts/synthetic.sql` + `scripts/explain.py`, as ssms_app under RLS): 102 schools, 150,000
students, 3,000,000 attendance records — the 14 hot queries take 0.1–43 ms warm, none scans a large table; the
chronic-absence list was rewritten to filter the week first (49 → 8 ms).

## 16.5 UAT checklist

Each item is done on the user's own phone or PC, once in Kiswahili and once in English, and ticked when it passes.

**School Admin**

- [ ] Update school information and logo
- [ ] Add a class, stream, subject and room using Add → Confirm; delete one with a reason
- [ ] Import 50 students from Excel; fix the error report and re-import
- [ ] Approve an enrolment; check the admission number and SMS
- [ ] Build one stream's timetable; see a clash message; auto-generate another stream
- [ ] Set mid-term exams without clashes
- [ ] Try to publish with missing marks; read the list; publish after fixing; open a report card
- [ ] Approve a teacher's amendment (and confirm you cannot approve your own)
- [ ] Read the audit log for one student

**Teacher**

- [ ] Take the morning register with the phone offline; sync later
- [ ] Enter marks in the grid; resolve a conflict; upload marks from Excel
- [ ] Validate three enrolment documents (one INVALID with a comment)
- [ ] Record a discipline incident; the parent receives an SMS

**Bursar**

- [ ] Approve a fee structure; generate invoices; see the control numbers
- [ ] Record a cash payment (and see the duplicate receipt-book number refused)
- [ ] Request a reversal; it waits for the head's approval
- [ ] Run reconciliation; resolve one exception; print the aging report

**Parent** (2G phone)

- [ ] Log in with phone + OTP; choose the child's school
- [ ] See today's attendance, results, report card PDF and invoice with control number
- [ ] Pay through M-Pesa (test environment) and receive the receipt SMS

**Student**

- [ ] See the timetable, results and fee balance; request a hostel place; change the password

**Gatekeeper / Bank officer**

- [ ] Card taps show the name; an unknown card is refused
- [ ] Confirm a bank deposit; the parent's balance updates

### Extension features (added 2026-11-12)

Run these in the same sessions, on a staging copy with the school's own data imported (never on the live system),
each person with their own account. Note anything unclear in Kiswahili or English as well as anything wrong.

**School Admin** (also)

- [ ] Open the public front page, then sign in from it; a parent card opens the SMS-code sign-in
- [ ] Choose last year in the year selector: lists show last year and every save is refused; switch back
- [ ] Write a leaving-certificate template, issue it to two students, print one, revoke the other with a reason
- [ ] Issue ID cards to one stream and to the staff; add a staff photo; print the cards (the QR code holds only the card number)
- [ ] Send an announcement by SMS and by email; see the email history; send yourself a test email
- [ ] Try to upload a file that is not a photo as a photo, and a photo over 300 KB: both refused with a clear message

**Teacher** (also)

- [ ] Set homework with an attachment; mark a student's submission
- [ ] Publish a study material as a file and as an https link (an http link is refused)
- [ ] Take a lesson register for one period; the office sees it on the monthly sheet

**Bursar / Accountant** (also)

- [ ] Record an expense with a receipt photo; ask to reverse it; the head teacher approves (not you)
- [ ] Read the income statement and the cash book for this month; the totals agree with the receipts
- [ ] Set the late fee and charge it on overdue invoices; it appears once per invoice

**Receptionist**

- [ ] Record an inquiry, follow it up, turn it into an application
- [ ] Add a school event to the calendar; it shows on the home page
- [ ] Print ID cards for a stream
- [ ] Confirm you see no fees, marks or health records in the menu

**Librarian**

- [ ] Add a category and a publisher; issue library cards to a stream and print them
- [ ] Lend a book by card number; take a late book back and see the fine on the student's invoice

**Student** (also)

- [ ] Hand in homework with a file; see the mark later
- [ ] Open progress by term and this month's attendance
- [ ] Download your ID card and your admit card

**Parent** (also)

- [ ] See each child's progress, homework not handed in and month attendance

**Platform operator** (the company running the service)

- [ ] Sign in to `/console` with password and authenticator code (without the code it is refused)
- [ ] Register a new school; its administrator signs in with the temporary password and must change it
- [ ] See the counts per school on the dashboard, and no student names anywhere

**Sign-off:** Head teacher ______ · ICT officer ______ · Date ______

## Design alignment tests (2026-10-31)

`tests/test_design_alignment.py` (page limit, Saturday rule, default CA/exam split and grades, qualified teachers, RLS on
`staff_subjects` as `ssms_app`, Registrar permissions) and `web/e2e/alignment.spec.ts`. The browser tests run on a fixed
school day (`api/scripts/e2e_api.py` and a pinned browser clock), so none depends on the real date.
