# 2. Requirements

MoSCoW priority: **M** must · **S** should · **C** could. Each requirement has an acceptance criterion (AC) that [16-test-plan.md](16-test-plan.md) traces to a test. "DB" in an AC means the database enforces it, and a test in `sql/tests/` proves it.

## 2.1 Functional requirements

### Authentication and access (module 7.1)

| ID | Requirement | P | Acceptance criteria |
|---|---|---|---|
| FR-01 | Staff and students log in with school code + username + password. | M | Valid → 200 with a 15-minute access JWT and an httpOnly refresh cookie. Invalid → 401 with the same bilingual message whether the username exists or not. |
| FR-02 | Parents log in with phone + 6-digit SMS OTP. If the phone belongs to parents in several schools, they choose one. | M | OTP expires in 5 min, at most 5 attempts, at most 3 OTPs per 15 min per phone. The school list comes from `resolve_users_by_phone` (test I15). |
| FR-03 | Accounts lock for 15 minutes after 5 failed logins. | M | 6th attempt → 423 with unlock time. |
| FR-04 | Refresh tokens rotate on every use; reusing an old one ends every session in that chain. | M | Replayed token → 401, family revoked, audit `TOKEN_REUSE`. |
| FR-05 | Change password; admin reset with forced change at next login. | M | `must_change_password` honoured; all refresh tokens revoked. |
| FR-06 | Every action checks permission (`module.action`) in the backend; menus show only permitted items. | M | Missing permission → 403 `FORBIDDEN`. Matrix in [15-security.md](15-security.md#152-rbac). |
| FR-07 | Kiswahili is the default, with an English toggle saved per user. | M | All labels, messages, SMS and PDFs exist in `sw` and `en`. |

### School setup and onboarding (7.2)

| ID | Requirement | P | Acceptance criteria |
|---|---|---|---|
| FR-08 | `super_admin` creates a school (code, name, registration no., region, district, ownership). The onboarding checklist seeds default levels, grading schemes, ledger accounts, templates and holidays. | M | New school ACTIVE with defaults; a school code is unique platform-wide. |
| FR-09 | `school_admin` edits school information: logo, motto, address, medium, SMS sender ID, GePG SP code, absence cut-off, open for enrolment. | M | Changes audited; logo ≤ 500 KB PNG/JPG. |
| FR-10 | Configure levels, classes (Standard I–VII, Form I–VI) with promotion path, streams, subjects, A-Level combinations, rooms. | M | Duplicate codes → 409. A class in use cannot be deleted, only soft-deleted. |
| FR-11 | Configure grading schemes, grade bands, division rules and assessment components per level, year and term. | M | Overlapping bands → 409 (DB). Weights that do not total 100 block publishing (test F4c). |

### Bulk import (7.3)

| ID | Requirement | P | Acceptance criteria |
|---|---|---|---|
| FR-12 | Import students, guardians and staff from Excel/CSV using a downloadable template. | M | Runs in Celery; progress shown from `background_jobs`. |
| FR-13 | Every row is validated; any error means nothing is saved and the user downloads an error report. | M | Error file lists row, column, value and bilingual message. The commit is all-or-nothing. |
| FR-14 | Re-uploading the same file with the same `Idempotency-Key` does not create duplicates. | M | Second request returns the first job. |

### Students (7.4)

| ID | Requirement | P | Acceptance criteria |
|---|---|---|---|
| FR-15 | Register a student with person details, date of birth, birth certificate (RITA), optional NIDA and PReM, photo, guardians with SMS consent. | M | Admission no. `XX-YYYY-NNNN` gapless per school (DB `next_document_no`). Age is computed, never stored. |
| FR-16 | Search by name, admission no., class, stream, status. | M | < 500 ms for 5,000 students; cursor pagination, 50 by default. |
| FR-17 | Change status: suspend, transfer, graduate, drop out, re-admit, with reason and effective date. | M | Allowed transitions only; history row; guardian SMS. |
| FR-18 | Promote a whole class at year end (new enrolment to `next_class_id`; repeaters stay). | S | One Celery job; old enrolments closed `PROMOTED`/`REPEATED`; final class → `GRADUATED`. |
| FR-19 | Enable/disable a student's login. | M | `users.status`; refresh tokens revoked. |

### Enrolment (7.5, workflow 9.1)

| ID | Requirement | P | Acceptance criteria |
|---|---|---|---|
| FR-20 | Inquiry: list classes/combinations open for the coming year with places left. | M | Only `is_open_for_enrolment` schools; capacity from streams. |
| FR-21 | Apply for one class per year; requirements for that level are listed. | M | Second open application in the same year → 409 (DB). |
| FR-22 | Upload one document per requirement (PDF/JPG/PNG ≤ 5 MB). | M | Type checked from file bytes; SHA-256 stored. |
| FR-23 | A teacher validates each document (VALID / INVALID with comment). | M | INVALID without a comment → 422 (DB). |
| FR-24 | All required documents VALID → "Requirements completed"; otherwise the application goes back to `REQUIREMENTS_PENDING` with the list to fix. | M | Status derived; SMS to guardian. |
| FR-25 | `school_admin` approves (assigns stream, admission number, enrolment, SMS) or rejects/cancels with a reason. | M | One transaction; stream capacity enforced (DB). |

### Classes, rooms, subjects (7.6)

| ID | Requirement | P | Acceptance criteria |
|---|---|---|---|
| FR-26 | Every create, update and delete uses the pattern Add → Confirm → Save, Update → Confirm, Delete → Confirm with reason. | M | Confirmation dialog; audit row with reason. Delete is soft (`deleted_at`). |

### Staff and departments (7.7)

| ID | Requirement | P | Acceptance criteria |
|---|---|---|---|
| FR-27 | Register staff: staff no., check no., qualifications, designation, department, employment type and date, salary, weekly load. | M | Salary visible only with `payroll.read`. |
| FR-28 | Assign teachers to subject + stream per year, and a class teacher per stream per year. | M | One teacher per stream-subject-year (DB). |
| FR-29 | Departments with a head. | M | Head must be staff of the same school (DB composite FK). |

### Timetable (7.8, workflow 9.5)

| ID | Requirement | P | Acceptance criteria |
|---|---|---|---|
| FR-30 | Create timetable slots with no teacher, room or stream clash. | M | Clash → 409 naming the conflicting slot. DB EXCLUDE constraints (tests T01–T03); back-to-back allowed (T04). |
| FR-31 | Respect teacher weekly load and room type (labs for practical subjects). | M | 422 with reason. |
| FR-32 | Generate a draft term timetable automatically; the admin reviews it and publishes. | S | Draft has zero clashes; unplaced lessons listed. |
| FR-33 | Print timetables per stream, teacher and room. | M | PDF ≤ 5 s. |

### Attendance (7.9, workflow 9.4)

| ID | Requirement | P | Acceptance criteria |
|---|---|---|---|
| FR-34 | Teachers take the morning register on a phone, offline if needed; it syncs later. | M | Records carry `client_record_id` (idempotent, DB unique); badge Saved offline / Synced / Conflict. |
| FR-35 | Gate devices post RFID/QR taps with an API key. | M | `resolve_device` identifies the school; unknown card → 404 logged. |
| FR-36 | At the cut-off (default 08:30 EAT) on school days, guardians of absent students get one SMS. | M | Not on weekends or holidays. One SMS per student per day (DB, test T06). Guardian must have SMS consent. |
| FR-37 | Flag chronic absence (≥ 3 days in a week). | S | View `v_chronic_absence`; dashboard list. |
| FR-38 | Attendance reports per stream, student and date range. | M | Export PDF/Excel. |

### Exams (7.10)

| ID | Requirement | P | Acceptance criteria |
|---|---|---|---|
| FR-39 | Set exam sessions and papers (class, subject, date, time, venue). | M | No class or venue clash (DB EXCLUDE). |
| FR-40 | View the exam timetable by class, teacher and student. | M | |

### Marks and results (7.11, workflow 9.2)

| ID | Requirement | P | Acceptance criteria |
|---|---|---|---|
| FR-41 | Spreadsheet-style mark entry per stream, subject and component, with offline autosave. | M | Each cell saved with `version`. A stale version → 409 with the server value (conflict UI). |
| FR-42 | Upload marks from the Excel template. | S | Same validation as manual entry. |
| FR-43 | Scores above the component maximum are rejected. | M | DB trigger (test F4a). |
| FR-44 | **Validation firewall.** `POST /results/publish` returns 422 `INCOMPLETE_GRADES_BLOCK` listing every missing or out-of-range mark (admission no., name, subject, component, teacher) and every subject whose weights ≠ 100. | M | `results_firewall()` (tests F4c, F4d). Messages in sw + en. |
| FR-45 | **Publish** in one transaction: weighted totals, grades, points, best-n division, positions (ties share), frozen results, locked drafts. Then queue report-card PDFs and "results ready" SMS. | M | `publish_results()` (test F4e). Second publish → 422. |
| FR-46 | Published results are immutable. Corrections go through an amendment request approved by `school_admin` (maker ≠ checker). | M | DB triggers (F7a–F7c). |
| FR-47 | Report cards (PDF) with comments from the class teacher and head teacher. | M | WeasyPrint; one PDF per student; bulk ZIP per stream. |
| FR-48 | Analytics: subject averages, grade distribution, teacher performance, trends across terms. | S | Dashboard < 2 s from materialised summaries. |

### Fees and payments (7.12, workflow 9.3)

| ID | Requirement | P | Acceptance criteria |
|---|---|---|---|
| FR-49 | Fee items, fee structures per class and year (per term or annual), discounts, scholarships, sibling waivers. | M | Structure must be APPROVED before invoicing (DB check). |
| FR-50 | Generate term invoices with installments; request a GePG control number. | M | One open invoice per student and term (DB). Totals derived (test F6a). |
| FR-51 | Accept payment callbacks (GePG, M-Pesa, Mixx by Yas/Tigo Pesa, Airtel Money, HaloPesa) with signature/IP check, idempotency, invoice row lock, allocation oldest-due-first, ledger, receipt and SMS. Respond in < 2 s. | M | Same `external_ref` twice → one payment (DB unique per school, test I10). Heavy work in Celery. |
| FR-52 | Record cash and bank payments; the bank officer confirms bank deposits. | M | Cash/bank require `recorded_by` (DB). |
| FR-53 | Overpayment becomes student credit and is applied to the next invoice. | M | Ledger account 2100 (test F6e). |
| FR-54 | Reversals need two people (requester ≠ approver) and post a reversing journal. | M | DB check (test F6c). |
| FR-55 | Sequential receipts per school (PDF + SMS). | M | Gapless `RCT-YYYY-NNNNNN` (DB `next_document_no`). |
| FR-56 | Daily reconciliation per channel against provider statements. | M | `reconciliation_runs` BALANCED or EXCEPTIONS with items to resolve. |
| FR-57 | Reminders before and after due dates; defaulters and aging reports; transaction history. | M | Celery beat; `v_invoice_aging` buckets 1–30, 31–60, 61–90, 90+. |

### Hostel, transport, venues (7.13–7.15)

| ID | Requirement | P | Acceptance criteria |
|---|---|---|---|
| FR-58 | Students request accommodation; the hostel master allocates rooms. | S | Room capacity enforced (DB, test T07). |
| FR-59 | Buses, drivers, routes, stops; assign students; seat availability; transport fees per route. | S | Bus capacity enforced (DB). |
| FR-60 | Book venues (date, time, seats). | C | No overlap (DB, test T08); seats ≤ capacity. |

### Discipline, activities, library (7.16, 7.17, 7.19)

| ID | Requirement | P | Acceptance criteria |
|---|---|---|---|
| FR-61 | Record incidents, actions and resolutions; notify the parent. | S | RESOLVED requires a resolution (DB). |
| FR-62 | Clubs with patrons and members. | C | |
| FR-63 | Library books, loans, overdue reminders. | C | Copies ≥ active loans (DB). |

### Communication (7.18)

| ID | Requirement | P | Acceptance criteria |
|---|---|---|---|
| FR-64 | Send SMS through provider adapters (Beem, NextSMS) behind one interface; templates in sw and en. | M | Provider switch is a setting; idempotency key per message (DB). |
| FR-65 | Announcements to the school, staff, parents, a class, a stream or one person; optional SMS. | M | Audience consistency checked (DB). |
| FR-66 | Track SMS credit; alert when low (< 100 credits). | M | `v_sms_credit_balance`. |

### Reports and compliance (7.20, 7.21)

| ID | Requirement | P | Acceptance criteria |
|---|---|---|---|
| FR-67 | Reports: enrolment, attendance, results, fees, staff, student status, transaction history; dashboards per role. | M | PDF/Excel; large ones run in Celery. |
| FR-68 | End-of-year compliance exports (enrolment by sex/age/class, attendance, results, staff) with configurable templates. | S | Excel/CSV/PDF; export audited. |

### Privacy and audit (rules 4, 9)

| ID | Requirement | P | Acceptance criteria |
|---|---|---|---|
| FR-69 | Append-only audit of every change to students, marks, results, fees, payments, attendance, enrolment and roles. | M | Actor, action, entity, before/after (redacted), IP, request id (tests F9a–F9c). |
| FR-70 | Data-subject requests (export, correct, delete) tracked with due dates. | M | `data_subject_requests`. Delete = anonymise, while keeping ledgers and results required by law. |
| FR-71 | Record guardian consent (SMS, data processing, photos, health data). | M | `consent_records`. No SMS without consent. |

## 2.2 Non-functional requirements

| ID | Category | Requirement | P | Acceptance criteria |
|---|---|---|---|---|
| NFR-01 | Performance | Pages load in < 3 s on 3G (1.6 Mbps, 300 ms RTT) | M | Lighthouse throttled run on a Moto E-class device |
| NFR-02 | Performance | Initial JS < 200 KB gzipped; role modules lazy-loaded | M | Bundle report in CI |
| NFR-03 | Performance | API p95 < 300 ms reads, < 800 ms writes; payment callback < 2 s | M | k6 report |
| NFR-04 | Scalability | Results day: 5,000 concurrent parent logins, 500 req/s | M | k6 spike test; error rate < 0.5 % |
| NFR-05 | Scalability | Hundreds of schools, thousands of students each | M | Synthetic 300 schools × 1,500 students; queries stay index-only |
| NFR-06 | Availability | 99.5 % monthly; daily backups + WAL; tested restore (RPO 15 min, RTO 4 h) | M | Quarterly restore drill |
| NFR-07 | Offline | Marks and attendance survive app close and reboot; sync with backoff | M | Playwright offline test |
| NFR-08 | Security | Rules 1–9 of the Definition of Done; OWASP ASVS L2 | M | [15-security.md](15-security.md); ZAP scan |
| NFR-09 | Privacy | PDPA 2022 compliance | M | DPIA signed; consent and DSR flows tested |
| NFR-10 | Usability | Kiswahili default, simple language, consistent actions, 48 px tap targets, works at 360 px | M | UAT per role ([16-test-plan.md](16-test-plan.md#165-uat-checklist)) |
| NFR-11 | Maintainability | routers → services → repositories; no SQL in routers; ≥ 80 % service coverage; ADRs | M | CI gates |
| NFR-12 | Portability | Docker; any Linux host; last two versions of Chrome, Firefox, Edge, Safari; Android 8+ | M | Cross-browser smoke tests |
| NFR-13 | Observability | JSON logs with request id, Sentry, Prometheus/Grafana dashboards and alerts | M | Alert on 5xx > 1 %, queue > 1,000, callback latency > 2 s |
| NFR-14 | API | Responses < 100 KB; no `SELECT *`; cursor pagination (50 by default, 200 max); ETag on heavy GETs; gzip/brotli | M | Contract tests |
| NFR-15 | Data integrity | 3NF; money NUMERIC(14,2); real date/time types; frozen results; balanced ledger | M | DB tests ([sql/tests/](sql/tests/)) |
