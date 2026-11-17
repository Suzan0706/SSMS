# 15. Test Plan

## 15.1 Strategy

| Level | Tool | Scope | When |
|---|---|---|---|
| Database | `psql -f db/tests/test_constraints.sql` | 16 integrity rules: clashes, ledger, audit, FKs, CHECKs, derived views | Every migration, in CI |
| Unit | pytest | Pure functions: timetable generator, phone normalisation, grading lookup | Every commit |
| API / integration | pytest + FastAPI `TestClient` on a real PostgreSQL 16 | Every use case through HTTP, roles, error codes, DB side-effects | Every commit (CI) |
| Schema drift | `alembic check` | ORM models vs migrated database | Every commit (CI) |
| Security | `pip-audit`, `npm audit`, OWASP ZAP baseline scan | Dependencies, headers, common web flaws | Weekly + before release |
| Performance | Locust | NFR-06/07 (200 users, p95 < 300 ms reads) | Before each term opens |
| UAT | Checklist 15.6 with registrar, bursar, teacher, parent, student | Real tasks in Kiswahili and English on phones and office PCs | Before go-live and each release |

**Test data.** [db/seed.sql](../db/seed.sql) (*Shule ya Sekondari Mfano*). Every account's password is `Mfano@2026`. The API tests load the schema and seed once and roll back each test, so tests are independent.

**Results of this design's verification run.** These were run against the PostgreSQL engine (PGlite, PostgreSQL 18 wire-compatible build) on Python 3.14:

| Check | Result |
|---|---|
| Database tests | 16/16 passed |
| API tests | **43 passed, 0 failed** |
| `alembic check` | No differences |
| Mermaid diagrams | All render |
| Report queries in section 13 | All 10 execute |

Re-run them on PostgreSQL 16 in CI before go-live.

## 15.2 Test cases per use case

The **Auto** column names the automated test that covers the case; `—` means manual or UAT.

### UC-01 Login

| ID | Input | Expected output | Auto |
|---|---|---|---|
| TC-01-01 | `registrar` / `Mfano@2026` (username in any case) | 200, access + refresh token, `/auth/me` role REGISTRAR, no `password_hash` in body | `test_login_returns_tokens_and_profile` |
| TC-01-02 | Wrong password; unknown username | Both 401 with identical body "Jina la mtumiaji au nenosiri si sahihi" | `test_wrong_password_and_unknown_user_give_the_same_generic_401` |
| TC-01-03 | 5 wrong passwords, then correct password | 6th attempt 423 with `locked_until` | `test_account_locks_after_five_failures` |
| TC-01-04 | Refresh with R1, then replay R1 | First 200 (R2); replay 401; R2 also revoked → 401 | `test_refresh_rotates_and_reuse_revokes_the_family` |
| TC-01-05 | Call protected endpoint without token | 401 | `test_missing_token_is_401` |
| TC-01-06 | One failed then one successful login | `audit_logs` has LOGIN_FAILED and LOGIN for the user | `test_login_and_failure_are_audited` |
| TC-01-07 | Wait 16 min after lock, correct password | 200 | — |

### UC-02 Manage Student Info & Status

| ID | Input | Expected output | Auto |
|---|---|---|---|
| TC-02-01 | Registrar posts Neema Mollel, DOB 10/02/2013, guardian phone `0754 111 222` | 201, admission no `S2026-NNNN`, age computed, Argon2id hash stored, guardian PARENT account with phone `255754111222` | `test_registrar_registers_student_with_guardian` |
| TC-02-02 | Guardian phone `12345` | 422 | `test_invalid_phone_is_rejected` |
| TC-02-03 | Search `q=massawe` | Exactly S2025-0014 | `test_search_by_name` |
| TC-02-04 | ACTIVE → SUSPENDED with reason | 200; history row; audit row with actor 2 / REGISTRAR and new status | `test_status_change_writes_history_and_audit` |
| TC-02-05 | APPLICANT → ACTIVE manually; APPLICANT → GRADUATED | 422 both | `test_disallowed_transitions_are_rejected` |
| TC-02-06 | ACTIVE → TRANSFERRED, then student logs in | 200, then login 401 (account deactivated) | `test_transfer_disables_student_login` |
| TC-02-07 | Parent p.massawe opens student 1 and student 2 | 200 and 404 | `test_parent_sees_only_own_child` |
| TC-02-08 | Student 5-inch phone: profile screen in Kiswahili | All labels Kiswahili, no horizontal scroll | — |

### UC-03 Manage Courses & Subjects

| ID | Input | Expected output | Auto |
|---|---|---|---|
| TC-03-01 | Admin creates subject `GEO-A` with names sw/en | 201 | — (CRUD) |
| TC-03-02 | Create subject with existing code `PHY` | 409 DUPLICATE | — |
| TC-03-03 | PUT PCM F5 subjects with periods 13 | 422 (1–12) | — |
| TC-03-04 | Create second offering PCM 2026 F5 | 409 | — |
| TC-03-05 | Registrar tries POST /courses | 403 | — |

### UC-04 Manage Instructors & Designation

| ID | Input | Expected output | Auto |
|---|---|---|---|
| TC-04-01 | Admin registers instructor with subjects [5, 4] | 201, account `tch.<employee_no>`, SMS logged | — |
| TC-04-02 | Duplicate employee number | 409 | — |
| TC-04-03 | Assign Class Teacher F2 A 2026 twice | Second → 409 | — |
| TC-04-04 | Class Teacher with `level_id` but no `stream` | 422 | — |
| TC-04-05 | Instructor reads another instructor's timetable | 403 | — |

### UC-05 Schedule Classes

| ID | Input | Expected output | Auto |
|---|---|---|---|
| TC-05-01 | Mwita Mon 08:20–09:00 (already 08:00–08:40) | 409, conflict INSTRUCTOR with schedule 1 | `test_instructor_clash_is_409_and_names_the_session` |
| TC-05-02 | Mwita Wed 08:40–09:20 after 08:00–08:40 | 201 (half-open periods) | `test_back_to_back_periods_do_not_clash` |
| TC-05-03 | `/schedules/check` in room F2A Mon 08:10 | `ok=false`, ROOM conflict | `test_room_clash_reported_by_check` |
| TC-05-04 | Salma assigned to Physics | 422 "Instructor is not qualified for this subject" | `test_unqualified_instructor_is_422` |
| TC-05-05 | Physics in a classroom | 422 "…needs a LABORATORY room" | `test_laboratory_subject_needs_a_laboratory` |
| TC-05-06 | Chemistry for Form II A in LAB-CHEM | 201; both confirmed students linked | `test_new_session_links_the_streams_confirmed_students` |
| TC-05-07 | Registrar posts a schedule | 403 | `test_only_admin_schedules` |
| TC-05-08 | Student linked to two overlapping sessions | DB rejects (23P01) | DB test T5 |
| TC-05-09 | Generator: 2 classes, shared teachers, 1 lab | All blocks placed, no overlaps, doubles never span a break | `test_generator_places_everything_without_clashes` |
| TC-05-10 | Generator: 6 maths periods | On 5 different days | `test_generator_spreads_a_subject_over_the_week` |
| TC-05-11 | Generator: no laboratory exists | Lab blocks reported unplaced, nothing forced | `test_generator_reports_what_cannot_be_placed` |
| TC-05-12 | `/schedules/generate` Form I A draft | 200, one lesson per class per period, not persisted | `test_generate_endpoint_returns_a_clash_free_draft` |
| TC-05-13 | Two admins save the same free slot at the same moment | One 201, one 409 (EXCLUDE constraint) | — (concurrency script) |

### UC-06 Enrol Student

| ID | Input | Expected output | Auto |
|---|---|---|---|
| TC-06-01 | Registrar applies new student to OLG F1 | 201; requirements include BIRTH_CERT, PSLE_RESULTS, exclude CSEE_RESULTS | `test_application_upload_and_submit_rules` |
| TC-06-02 | Upload a file starting `MZ` named `.pdf` | 422 (type from bytes) | same |
| TC-06-03 | Submit with 3 mandatory documents missing | 422 `missing = [PASSPORT_PHOTO, MEDICAL_FORM, PSLE_RESULTS]` | same |
| TC-06-04 | Cancel, then apply again | CANCELLED, then 201 | same |
| TC-06-05 | Apply student 1 (already confirmed 2026) | 409 DUPLICATE | `test_one_active_enrolment_per_year` |
| TC-06-06 | Confirm while SUBMITTED | 409 | `test_confirm_requires_validated` |
| TC-06-07 | Validate remaining documents, confirm stream A | CONFIRMED; 2 sessions linked; student ACTIVE; invoice TZS 790,000 | `test_full_enrolment_flow` |
| TC-06-08 | Student opens another student's enrolment | 404 | `test_student_cannot_see_another_students_enrolment` |
| TC-06-09 | Offering at capacity | 409 "Nafasi zimejaa" | — |

### UC-07 Validate Requirements

| ID | Input | Expected output | Auto |
|---|---|---|---|
| TC-07-01 | Mark doc 3 VALID while doc 4 pending | Enrolment stays SUBMITTED | `test_full_enrolment_flow` |
| TC-07-02 | Mark INVALID without remarks | 422 | `test_invalid_without_remarks_is_rejected` |
| TC-07-03 | INVALID → student re-uploads → submit → VALID | INVALID → SUBMITTED → VALIDATED | `test_invalid_document_is_resubmitted` |
| TC-07-04 | Validate a document of a PENDING (not submitted) enrolment | 409 | — |

### UC-08 Record Transaction

| ID | Input | Expected output | Auto |
|---|---|---|---|
| TC-08-01 | Bursar: TZS 100,000 M-Pesa `RKT55XQ1ZP` on INV-2026-000002 | 201; phone normalised; balance 380,000 PARTIALLY_PAID | `test_manual_payment_updates_balance` |
| TC-08-02 | Reference `QKJ7H2LM9P` again | 409 `uq_trans_reference` | `test_same_reference_cannot_be_posted_twice` |
| TC-08-03 | Student 1 paying student 2's invoice | 422 | `test_payment_against_another_students_invoice_is_rejected` |
| TC-08-04 | BANK payment without reference | 422 | `test_non_cash_payment_needs_reference` |
| TC-08-05 | Admin reverses TXN 3, then again | 201 REVERSAL, balance back to 680,000; second 409 | `test_reversal_restores_balance_once` |
| TC-08-06 | Bursar tries to reverse | 403 | `test_bursar_cannot_reverse` |
| TC-08-07 | UPDATE / DELETE a completed transaction in SQL | Rejected by trigger | `test_ledger_rows_cannot_be_edited_or_deleted`, DB T8–T9 |
| TC-08-08 | Same GePG notification posted twice | Both acknowledged `7101`; one transaction, source GEPG | `test_gepg_callback_is_idempotent` |
| TC-08-09 | GePG notification with bad signature | 401 | `test_gepg_callback_with_bad_signature_is_401` |
| TC-08-10 | Parent p.hassan statement for child / other child | 200 with balance 480,000 / 404 | `test_parent_statement_only_for_own_child` |
| TC-08-11 | Pay with GePG control number on M-Pesa sandbox | Receipt SMS within 1 min, invoice PAID | — (GePG test environment) |

### UC-09 Generate Reports

| ID | Input | Expected output | Auto |
|---|---|---|---|
| TC-09-01 | Student list, Form II A, Kiswahili | 2 rows, Kiswahili headings, guardian phones | SQL verified (section 13) |
| TC-09-02 | Timetable Form II A Term One PDF | 5 sessions in grid, break row shown | SQL verified |
| TC-09-03 | Transaction history Jan 2026 | 4 rows; totals CASH 200,000 · GEPG 280,000 · MPESA 400,000 · total 880,000 (FAILED excluded) | SQL verified |
| TC-09-04 | Report card Form II A mid-term | Positions 1–2, averages 69.38 / 58.13, division INC (only 4 subjects) | SQL verified |
| TC-09-05 | Instructor requests transaction report | 403 | — |
| TC-09-06 | Export 3,000-row student list | 202 + job id; file appears in "My reports"; EXPORT audit row | — |

### Audit and data integrity

| ID | Input | Expected output | Auto |
|---|---|---|---|
| TC-AU-01 | UPDATE audit_logs | Rejected "append-only" | `test_audit_log_cannot_be_changed`, DB T12 |
| TC-AU-02 | Any change to users | No `password_hash` in audit JSON | DB T15 |

## 15.3 API test code (pytest)

Full suite: [backend/tests/](../backend/tests/). The fixtures and one test from each area are shown here:

```python
# File: backend/tests/conftest.py (excerpt)
@pytest.fixture(scope="session")
def connection():
    engine = create_engine(TEST_DB)
    with engine.connect() as conn:
        raw = conn.connection.dbapi_connection
        with raw.cursor() as cur:
            cur.execute("DROP SCHEMA IF EXISTS public CASCADE; CREATE SCHEMA public;")
            cur.execute((ROOT / "db" / "schema.sql").read_text(encoding="utf-8"))
            cur.execute((ROOT / "db" / "seed.sql").read_text(encoding="utf-8"))
        raw.commit()
        yield conn
    engine.dispose()


@pytest.fixture
def db(connection):
    outer = connection.begin()
    session = Session(bind=connection, join_transaction_mode="create_savepoint",
                      autoflush=False, expire_on_commit=False)
    yield session
    session.close()
    outer.rollback()                      # every test starts from the seed
```

```python
# File: backend/tests/test_schedules.py (excerpt)
def test_instructor_clash_is_409_and_names_the_session(client, as_admin):
    r = client.post(f"{API}/schedules", headers=as_admin, json=BASE)
    assert r.status_code == 409, r.text
    conflicts = r.json()["detail"]["conflicts"]
    assert {"kind": "INSTRUCTOR", "schedule_id": 1, "message": "Instructor already teaching"} in conflicts
```

```python
# File: backend/tests/test_transactions.py (excerpt)
def test_gepg_callback_is_idempotent(client, db, monkeypatch):
    monkeypatch.setattr(gepg, "verify_signature", lambda signed, signature: None)
    for _ in range(2):                                    # GePG retries the same notification
        r = client.post(f"{API}/payments/gepg/callback", content=GEPG_XML,
                        headers={"Content-Type": "application/xml"})
        assert r.status_code == 200
        assert b"<TrxStsCode>7101</TrxStsCode>" in r.content
    rows = db.scalar(select(func.count()).select_from(Transaction).where(Transaction.reference_no == "PSP-88812"))
    assert rows == 1
```

**Run:**

```bash
cd backend
TEST_DATABASE_URL=postgresql+psycopg://postgres:postgres@localhost:5432/sms_test pytest --cov=app
psql -v ON_ERROR_STOP=1 -d sms_test -f ../db/tests/test_constraints.sql
alembic check
```

## 15.4 Database constraint tests

[db/tests/test_constraints.sql](../db/tests/test_constraints.sql) contains T1–T16. Each test attempts one violation inside a `DO` block and expects a specific SQLSTATE. If the violation is accepted, the block raises `TF001`, which stops the script. The whole script runs in one transaction that is rolled back.

| Test | Rule | Expected |
|---|---|---|
| T1–T3 | Instructor / room / class-stream double booking | `exclusion_violation` |
| T4 | Back-to-back periods | accepted |
| T5 | Student in two overlapping sessions | `exclusion_violation` (trigger) |
| T6 | Second active enrolment in a year | `unique_violation` (trigger) |
| T7 | Phone not `255XXXXXXXXX` | `check_violation` |
| T8–T9 | Edit / delete completed transaction | `raise_exception` (trigger) |
| T10 | Same method + reference twice | `unique_violation` |
| T11 | Payment on another student's invoice | `foreign_key_violation` |
| T12 | Edit audit log | `raise_exception` |
| T13 | Attendance for a student not in the session | `foreign_key_violation` |
| T14 | INVALID document without remarks | `check_violation` |
| T15 | Audit row has actor; no password hash in audit | assertion |
| T16 | Derived invoice balances | assertion |

## 15.5 Non-functional tests

| ID | Requirement | Method | Pass criterion |
|---|---|---|---|
| NT-01 | NFR-06 | Locust: 200 virtual users, mix of 70 % reads / 30 % writes for 15 min | p95 read < 300 ms, write < 800 ms, 0 % 5xx |
| NT-02 | NFR-07 | Generate report cards for a class of 60 | < 30 s |
| NT-03 | NFR-02 | SSL Labs scan | Grade A |
| NT-04 | NFR-11 | Restore last night's backup + WAL to a new server | Data within 15 min of failure, done in < 4 h |
| NT-05 | NFR-12 | Android Chrome, open timetable, enable airplane mode, reload | Cached timetable shown with "offline" banner |
| NT-06 | NFR-08 | Lighthouse accessibility on 9 main screens | ≥ 90 each |
| NT-07 | NFR-01 | `SELECT count(*) FROM users WHERE password_hash NOT LIKE '$argon2id$%'` | 0 |

## 15.6 UAT checklist

Each item is performed by the named user on their own device, once in Kiswahili and once in English. Tick ✔ when passed, and note the defect id when it fails.

**Registrar (Msajili)**

- [ ] Log in, change the temporary password, log out and in again.
- [ ] Register a new Form I student with two guardians in under 3 minutes; print the login slip.
- [ ] Find a student by part of the surname and by NECTA index number.
- [ ] Suspend a student with a reason; guardian receives the SMS in their language.
- [ ] Confirm a validated enrolment into stream B; check the timetable and invoice appear.
- [ ] Cancel an application with a reason; the student receives the SMS.
- [ ] Print the student list and the enrolment report as PDF; the totals are correct.

**Admin / Academic Master (Mwalimu wa Taaluma)**

- [ ] Open the 2026 offerings for Form I and Form V with capacities.
- [ ] Add a subject to PCM Form V with 6 periods per week.
- [ ] Place a lesson that clashes; the message names the clashing lesson and suggests a free slot.
- [ ] Auto-generate a Form I timetable; review unplaced lessons; publish.
- [ ] Assign a Class Teacher for Form II A.
- [ ] Publish mid-term results; parents can now see them.
- [ ] Reverse a wrongly recorded payment; the original stays visible.
- [ ] Search the audit log for all changes to one student.

**Bursar (Mhasibu)**

- [ ] Record a cash payment and print a receipt.
- [ ] Record an M-Pesa payment; entering the same reference again is refused.
- [ ] Check an invoice's GePG control number; a test payment in the GePG test environment appears automatically.
- [ ] Print the transaction history for one month with totals per method.

**Instructor (Mwalimu)**

- [ ] See my teaching timetable and the class list for one session.
- [ ] Validate three requirement documents; mark one INVALID with a remark.
- [ ] Enter mid-term scores for a class; grades appear automatically.
- [ ] Take attendance for today's lesson on a phone.

**Student (Mwanafunzi)**

- [ ] Browse open courses, choose one, answer "Pursue the course?" with No, then with Yes.
- [ ] Upload all requirements from a phone camera (JPG) and submit.
- [ ] Re-upload a document marked invalid.
- [ ] See my timetable offline after one online visit.

**Parent (Mzazi)**

- [ ] See only my own children.
- [ ] See the invoice, control number and balance; pay with M-Pesa; receive the receipt SMS.
- [ ] Download the report card PDF.

**Sign-off.** Head of School ______ · ICT Officer ______ · Date ______
