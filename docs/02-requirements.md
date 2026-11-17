# 2. Requirements

Priority uses MoSCoW: **M** = must, **S** = should, **C** = could. Every requirement has an acceptance criterion (AC) that the test plan ([section 15](15-test-plan.md)) verifies.

## 2.1 Functional requirements

### Authentication and accounts

| ID | Requirement | P | Acceptance criteria |
|---|---|---|---|
| FR-01 | Users log in with username (or email) and password and receive a JWT access token and a refresh token. | M | Valid credentials → `200` with tokens; invalid → `401` with a generic bilingual message that does not say which field was wrong. |
| FR-02 | An account locks for 15 minutes after 5 consecutive failed logins. | M | The 6th attempt within the lock window → `423 Locked`, even with the correct password; the lock clears after 15 minutes. |
| FR-03 | Users change their own password; admins reset other users' passwords. | M | New password must meet the policy (≥10 chars, letters + digits); all refresh tokens of that user are revoked. |
| FR-04 | Every endpoint enforces role-based access (see [section 12](12-security.md) for the matrix). | M | A user calling an endpoint outside their role → `403`; parents see only their linked children (`404` for other students). |
| FR-05 | Users choose Kiswahili or English; the choice persists. | M | `preferred_language` is saved; all labels, messages and PDFs render in the chosen language. |

### Students (UC1)

| ID | Requirement | P | Acceptance criteria |
|---|---|---|---|
| FR-06 | Registrar registers a student with personal details, date of birth, guardians and an auto-generated admission number. | M | Admission number format `S{YYYY}-{NNNN}`, unique; age is computed from `date_of_birth`, never typed in. |
| FR-07 | Registrar searches students by name, admission number, NECTA index number, level, stream or status. | M | Search returns in < 1 s for 5,000 students; results are paged (default 25). |
| FR-08 | Registrar updates student details; every change is audited. | M | `audit_logs` row with old and new values, actor, time and IP for each update. |
| FR-09 | Registrar changes a student's status (ACTIVE, SUSPENDED, TRANSFERRED, DROPPED_OUT, GRADUATED) with a mandatory reason and effective date. | M | Only allowed transitions succeed (see [UC-02](05-use-cases.md#uc-02-manage-student-info-and-status)); `student_status_history` row created; guardian receives an SMS. |
| FR-10 | Students and parents view the student's profile, status history, timetable, results and invoices. | M | Student sees only self; parent sees only linked children. |
| FR-11 | Registrar links one or more guardians to a student and marks one as primary. | M | Exactly zero or one primary guardian per student (DB-enforced). |

### Courses and subjects (UC2)

| ID | Requirement | P | Acceptance criteria |
|---|---|---|---|
| FR-12 | Admin creates, updates and deactivates courses (programmes/combinations) and subjects with Kiswahili and English names. | M | Duplicate codes → `409`; a course in use cannot be deleted, only deactivated. |
| FR-13 | Admin defines which subjects a course has at each level, compulsory flag and periods per week. | M | `course_subjects` rows; periods per week 1–12. |
| FR-14 | Admin opens a course offering for an academic year and level with a capacity. | M | One offering per course+year+level; enrolment stops when confirmed enrolments reach capacity. |

### Instructors (UC3)

| ID | Requirement | P | Acceptance criteria |
|---|---|---|---|
| FR-15 | Admin registers instructors with department, qualification, employee number and the subjects they can teach. | M | Unique employee number; only qualified subjects can be scheduled for the instructor. |
| FR-16 | Admin assigns yearly designations (Class Teacher of Form II A, HOD, Academic Master …). | M | Duplicate designation for the same year/class → `409`; history kept per year. |
| FR-17 | Instructors view their timetable and class lists ("List of Students"). | M | Class list shows only confirmed students of that session. |

### Scheduling (UC5)

| ID | Requirement | P | Acceptance criteria |
|---|---|---|---|
| FR-18 | Admin creates a class session: offering, stream, term, subject, instructor, room, day, start and end time. | M | Session saved only if there is no instructor, room, class-stream or student clash; clash → `409` naming the conflicting session. |
| FR-19 | The system checks room capacity, room type (laboratory subjects) and instructor weekly load. | M | Capacity < class size, wrong room type or load above `max_periods_per_week` → `422` with reason. |
| FR-20 | Admin auto-generates a draft timetable for a term (`schedulingAlgo`). | S | Generated draft has zero clashes; unplaced periods are listed for manual placement. |
| FR-21 | Timetables print per class, instructor and room. | M | PDF in the user's language within 5 s. |

### Enrolment (UC6, UC7)

| ID | Requirement | P | Acceptance criteria |
|---|---|---|---|
| FR-22 | Students browse open course offerings with subjects and requirements. | M | Only `is_open` offerings of the enrolment year are shown. |
| FR-23 | A student applies to one offering per academic year. | M | A second active application in the same year → `409` (DB-enforced). |
| FR-24 | A student uploads one file per requirement (PDF/JPG/PNG, ≤ 5 MB). | M | Wrong type/size → `422`; file stored with SHA-256 checksum. |
| FR-25 | Instructors (faculty) mark each document VALID or INVALID with remarks. | M | INVALID requires remarks; the student is notified per document. |
| FR-26 | The enrolment becomes VALIDATED only when every mandatory requirement has a VALID document. | M | Status changes automatically; otherwise INVALID with the list of documents to fix. |
| FR-27 | Registrar confirms or cancels a validated enrolment; confirming assigns a stream, links the student to the stream's class sessions, sets the student ACTIVE and raises the term invoice. | M | All of these happen in one database transaction; the student receives "Enrolment complete / Usajili umekamilika". |
| FR-28 | A student or registrar cancels an enrolment before confirmation with a reason. | M | Status CANCELLED; the student may apply again. |

### Transactions and fees (UC8)

| ID | Requirement | P | Acceptance criteria |
|---|---|---|---|
| FR-29 | Bursar defines fee structures per term, level and (optionally) course in TZS. | M | Amounts ≥ 0, two decimal places. |
| FR-30 | The system issues invoices and requests a GePG control number. | M | 12-digit control number saved; parent receives SMS with control number and amount. |
| FR-31 | Bursar records manual payments (cash, bank, M-Pesa, Tigo Pesa, Airtel Money) with reference number. | M | Duplicate method+reference → `409`; non-cash payments need a reference. |
| FR-32 | The system accepts signed GePG / mobile-money payment callbacks idempotently. | M | Replaying the same callback creates no second transaction; invalid signature → `401`. |
| FR-33 | Transactions can never be edited or deleted; corrections are REVERSAL entries. | M | UPDATE/DELETE blocked by DB trigger; reversal links to the original. |
| FR-34 | Students and parents view invoices, payments and balance. | M | Balance = Σ invoice items − Σ completed credits (from `v_invoice_balances`). |

### Results and attendance

| ID | Requirement | P | Acceptance criteria |
|---|---|---|---|
| FR-35 | Instructors enter scores (0–100) for their subject sessions per term and assessment type. | M | Only the instructor of that subject/class (or Academic Master) may enter; grade is derived from the NECTA scale of the level. |
| FR-36 | Academic Master publishes results; only published results are visible to students/parents. | M | Unpublished results hidden from STUDENT/PARENT roles. |
| FR-37 | Instructors take attendance per session per date. | S | One record per student/session/date; only students in that session. |

### Reports and audit (UC9)

| ID | Requirement | P | Acceptance criteria |
|---|---|---|---|
| FR-38 | The system generates: student list, class schedule, enrolment report, transaction history, student status report and report card. | M | Each report is filterable, exportable as PDF and Excel/CSV, and bilingual. |
| FR-39 | Large reports run in the background and are downloadable when ready. | S | Requests > 2,000 rows return `202` with a job id; the file appears under "My reports". |
| FR-40 | Admins search the audit trail by user, entity, action and date. | M | Audit entries are read-only to everyone, including admins. |
| FR-41 | The system sends SMS for: enrolment status, invoice/control number, payment receipt, status change, results published. | S | Message sent in the recipient's language; failures retried 3 times. |

## 2.2 Non-functional requirements

| ID | Category | Requirement | Acceptance criteria |
|---|---|---|---|
| NFR-01 | Security | Passwords hashed with **Argon2id** (m=64 MiB, t=3, p=4); no plaintext passwords anywhere. | `users.password_hash` starts with `$argon2id$`; code review and DB scan find no plaintext. |
| NFR-02 | Security | All traffic over HTTPS (TLS 1.2+), HSTS enabled. | SSL Labs grade A; HTTP redirects to HTTPS. |
| NFR-03 | Security | Short-lived JWT access tokens (15 min) and rotating refresh tokens (7 days) with reuse detection. | Reusing a rotated refresh token revokes the whole token family. |
| NFR-04 | Security | Every create/update/delete of records, transactions and status, and every login, is written to an append-only audit log. | Attempts to UPDATE/DELETE `audit_logs` fail at DB level. |
| NFR-05 | Security / Privacy | Comply with the Personal Data Protection Act, 2022: purpose limitation, consent for minors via guardians, access logs, breach notification. | Data-protection checklist signed off; personal-data exports audited (`EXPORT`). |
| NFR-06 | Performance | p95 API latency < 300 ms for reads and < 800 ms for writes at 200 concurrent users. | Load test (Locust) report. |
| NFR-07 | Performance | Report card PDF for a class of 60 generated in < 30 s (background job). | Celery task timing in logs. |
| NFR-08 | Usability | All screens bilingual (Kiswahili/English), usable on a 5-inch phone, WCAG 2.1 AA contrast. | UAT with registrar, teacher, parent; Lighthouse accessibility ≥ 90. |
| NFR-09 | Usability | A new registrar can register a student in < 3 minutes after 30 minutes of training. | Timed UAT task. |
| NFR-10 | Availability | 99.5 % monthly availability during the school term (07:00–20:00 EAT). | Uptime monitor. |
| NFR-11 | Availability | Daily encrypted backups plus WAL archiving; RPO ≤ 15 min, RTO ≤ 4 h. | Quarterly restore drill succeeds. |
| NFR-12 | Availability | The PWA shows cached timetable, results and invoices when offline. | Airplane-mode test on Android Chrome. |
| NFR-13 | Maintainability | Layered code (routers → services → repositories/models); ≥ 80 % test coverage on services. | `pytest --cov` report in CI. |
| NFR-14 | Maintainability | Schema changes only through Alembic migrations; API versioned under `/api/v1`. | CI fails if models and migrations differ. |
| NFR-15 | Portability | Runs in Docker containers on any Linux host (local server or cloud) with PostgreSQL 16+. | `docker compose up` on a clean Ubuntu 24.04 VM. |
| NFR-16 | Portability | Client works on Chrome/Edge/Firefox (last 2 versions) and Android 9+. | Cross-browser smoke test. |
| NFR-17 | Scalability | Supports 5,000 students, 300 staff, 10 years of history without redesign. | Seeded load test with 10 years of synthetic data. |
| NFR-18 | Localisation | Money shown as `TZS 1,250,000`; dates `dd/mm/yyyy`; phones `+255 754 000 001`. | UI snapshot tests. |
