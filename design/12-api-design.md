# 12. API Design

## 12.1 Conventions

| Topic | Rule |
|---|---|
| Base path | `/api/v1`; plural kebab-case resources (`/enrolment-applications`) |
| Docs | OpenAPI/Swagger at `/docs` with request and response examples on every endpoint |
| Auth | `Authorization: Bearer <JWT>` (15 min); refresh token in `HttpOnly; Secure; SameSite=Strict` cookie `ssms_rt`, path `/api/v1/auth` |
| Tenant | From the JWT claim `sch`, never from the URL or body. Pre-login endpoints resolve the school via the school code (sub-domain or `school_code` field). |
| Permissions | `require_permission("module.action")` on every route (matrix in [15-security.md](15-security.md#152-rbac)); ownership checks for parents and students |
| Errors | `{"error_code": "...", "message": "<sw or en, per Accept-Language / user preference>", "details": [...]}`: 422 validation, 409 conflict, 403 forbidden, 401 unauthenticated, 404 not found or not yours, 423 locked, 429 rate-limited |
| Pagination | Cursor: `?limit=50&cursor=<opaque>` (max 50) → `{"items": [...], "next_cursor": "..."}` |
| Idempotency | `Idempotency-Key` header required on payments, imports, invoice runs, publish, bulk SMS; stored 24 h in `idempotency_keys`; same key + different body → 422 `IDEMPOTENCY_MISMATCH` |
| Caching | `ETag` / `If-None-Match` on heavy GETs (class lists, timetables, results, reference data) → 304 |
| Size | Responses < 100 KB; explicit fields only; gzip/brotli at Nginx |
| Money and time | Money as decimal strings `"680000.00"` (TZS); timestamps ISO 8601 UTC; dates `YYYY-MM-DD` |
| Phones | Accepted as `07XXXXXXXX`, `+2557…` or `2557…`; returned masked (`****0021`) unless `guardians.manage` is held |

**Database errors are mapped to API errors:**

| SQLSTATE | HTTP | `error_code` |
|---|---|---|
| `23505` | 409 | `DUPLICATE` |
| `23P01` | 409 | `TIMETABLE_CLASH` / `BOOKING_OVERLAP` |
| `23503` | 422 | `INVALID_REFERENCE` |
| `23514` | 422 | `RULE_VIOLATION` (capacity, score max…) |
| `42501` (RLS) | 404 | `NOT_FOUND` |
| `SS422` | 422 | `INCOMPLETE_GRADES_BLOCK` |
| `P0001` | 409 | `NOT_ALLOWED` |

**Sample error:**

```json
HTTP/1.1 422 Unprocessable Entity
{
  "error_code": "INCOMPLETE_GRADES_BLOCK",
  "message": "Matokeo hayawezi kutolewa: alama 9 hazipo au si sahihi.",
  "details": [
    {"problem": "MISSING_MARK", "admission_no": "MF-2026-0003", "student": "Emmanuel Lyimo",
     "subject": "PHY-A", "component": "TERMINAL", "teacher": "Peter Kimaro",
     "message_sw": "Alama haijaingizwa", "message_en": "No mark entered"},
    {"problem": "WEIGHTS_NOT_100", "subject": "GS", "message_en": "Component weights total 110, must be 100"}
  ]
}
```

## 12.2 Endpoint catalogue

Column **Perm** = required permission, `public` = no token, `self` = own record or own child, `device` = device API key, `signed` = provider signature.

### Platform (super admin console, separate deployment, role `ssms_platform`)

| Method | Path | Perm | Request | Response | Codes |
|---|---|---|---|---|---|
| POST | `/platform/auth/login` | public | email, password, TOTP | tokens | 200, 401, 423 |
| GET | `/platform/schools` | super_admin | `?status&cursor` | page of schools | 200 |
| POST | `/platform/schools` | super_admin | code, name, registration_no, ownership, region, district, admin {names, phone, email} | school + admin temporary password (once) + default counts; one transaction, [ADR 0012](adr/0012-synchronous-onboarding.md) | 201, 409, 422 |
| PATCH | `/platform/schools/{id}` | super_admin | status (SUSPENDED/ACTIVE/CLOSED), reason | school | 200, 404 |

### Authentication (7.1)

| Method | Path | Perm | Request | Response | Codes |
|---|---|---|---|---|---|
| POST | `/auth/login` | public | school_code, username, password | access_token, expires_in, user, permissions + refresh cookie | 200, 401, 423, 429 |
| POST | `/auth/otp/request` | public | phone | `{sent: true}` (always the same) | 200, 429 |
| POST | `/auth/otp/verify` | public | phone, code | tokens, or `{choose: [schools], selection_token}` | 200, 401, 429 |
| POST | `/auth/select-school` | public | selection_token, school_id | tokens | 200, 401 |
| POST | `/auth/refresh` | cookie | — | new access token, rotated cookie | 200, 401 |
| POST | `/auth/logout` | any | — | — | 204 |
| GET | `/auth/me` | any | — | profile, roles, permissions, language, school | 200 |
| POST | `/auth/change-password` | any | current_password, new_password | — | 204, 401, 422 |
| POST | `/users/{id}/reset-password` | users.manage | — | `{temporary_password}` once + SMS | 200, 404 |

### School setup and configuration (7.2, 7.6)

| Method | Path | Perm | Request | Response | Codes |
|---|---|---|---|---|---|
| GET / PATCH | `/school` | any / settings.update | motto, addresses, phone, email, medium, sender_id, gepg_sp_code, absence_cutoff, open_for_enrolment | school + settings | 200, 422 |
| PUT | `/school/logo` | settings.update | multipart PNG/JPG ≤ 500 KB | logo URL | 200, 422 |
| GET / POST | `/education-levels` | any / academics.configure | code, names, sort | list / item | 200, 201, 409 |
| GET / POST / PATCH / DELETE | `/academic-years[/{id}]` | academics.configure | name, start, end, is_current | item | 200, 201, 409, 422 |
| GET / POST / PATCH / DELETE | `/terms[/{id}]` | academics.configure | year, term_no, names, dates | item | 201, 409 (overlap) |
| GET / POST / DELETE | `/public-holidays[/{id}]` | academics.configure | date, names, kind | item | 201, 409 |
| GET / POST / PATCH / DELETE | `/classes[/{id}]` | academics.configure | level, code, names, sort, next_class_id | item | 201, 409 |
| GET / POST / PATCH / DELETE | `/streams[/{id}]` | academics.configure | class, name, capacity, home_room | item | 201, 409 |
| PUT | `/streams/{id}/class-teacher` | academics.configure | academic_year_id, staff_id | assignment | 200, 409 |
| GET / POST / PATCH / DELETE | `/subjects[/{id}]` | academics.configure | code, necta_code, names, department, room_type | item | 201, 409 |
| PUT | `/classes/{id}/subjects` | academics.configure | [{subject_id, compulsory, periods}] | list | 200 |
| GET / POST / PATCH / DELETE | `/combinations[/{id}]` | academics.configure | code, names, subject_ids | item | 201, 409 |
| GET / POST / PATCH / DELETE | `/rooms[/{id}]` | academics.configure | code, name, type, capacity, equipment | item | 201, 409 |
| GET / POST / PATCH | `/grading-schemes[/{id}]` | academics.configure | level, year, name, best_n, bands[], divisions[] | scheme (new version on change) | 201, 409 (overlapping bands) |
| GET / POST / PATCH / DELETE | `/assessment-components[/{id}]` | academics.configure | term, level, subject?, code, names, max_score, weight | item + weight totals | 201, 409 |
| GET | `/assessment-components/weight-check?term_id` | academics.configure | — | totals per level/subject (`v_component_weight_totals`) | 200 |

Every DELETE is a soft delete: it requires `?reason=`, a confirmation in the UI, and writes an audit row (Add → Confirm → Update → Delete pattern).

### Users, roles, staff, departments (7.1, 7.7)

| Method | Path | Perm | Request | Response | Codes |
|---|---|---|---|---|---|
| GET | `/users` | users.read | `?role&q&cursor` | page | 200 |
| PATCH | `/users/{id}` | users.manage | status (ACTIVE/DISABLED), language | user | 200 |
| POST / DELETE | `/users/{id}/roles[/{role}]` | roles.assign | role_code | roles | 201, 204, 409 |
| GET / POST / PATCH / DELETE | `/staff[/{id}]` | staff.read / staff.manage | person, staff_no, check_no, department, designation, type, date, salary (payroll.read to see), max_periods | staff | 201, 409, 422 |
| POST / DELETE | `/staff/{id}/qualifications[/{qid}]` | staff.manage | level, title, institution, year | item | 201 |
| GET / POST / PATCH / DELETE | `/departments[/{id}]` | staff.manage | code, names, head_staff_id | item | 201, 409 |
| GET / POST / DELETE | `/designations[/{id}]` | staff.manage | code, names | item | 201 |
| GET / PUT | `/teaching-assignments?year&stream` | staff.read / staff.manage | [{stream, subject, staff}] | list | 200, 409 |

### Students, guardians, import (7.3, 7.4)

| Method | Path | Perm | Request | Response | Codes |
|---|---|---|---|---|---|
| GET | `/students` | students.read | `?q&class&stream&status&cursor` | page (masked ids) | 200 |
| POST | `/students` | students.create | person, dob, birth_cert_no, nida?, prem?, guardians[{names, phone, relationship, is_primary, sms_consent}] | student + admission_no | 201, 409, 422 |
| GET / PATCH | `/students/{id}` | students.read / students.update | partial | student | 200, 404 |
| POST | `/students/{id}/status` | students.status | new_status, reason, effective_date | history row | 200, 409 (transition), 422 |
| PUT | `/students/{id}/photo` | students.update | JPG/PNG ≤ 1 MB | URL | 200 |
| GET | `/students/{id}/identifiers` | students.update | — | birth certificate and NIDA in clear; audited `VIEW_SENSITIVE` | 200, 404 |
| GET / POST / DELETE | `/students/{id}/guardians[/{gid}]` | guardians.manage | guardian, relationship, primary, receives_sms | links | 201, 409 |
| POST | `/guardians/{id}/consents` | guardians.manage | purpose, granted, channel | record | 201 |
| POST | `/promotions` (Idempotency-Key) | students.status | academic_year_from, to, class_id?, repeaters[] | job | 202 |
| GET | `/imports/templates/{kind}` | students.import | `kind = students\|guardians\|staff\|marks` | XLSX | 200 |
| POST | `/imports/{kind}` (Idempotency-Key) | students.import | multipart file | job | 202, 422 |
| GET | `/jobs` | any | `?cursor` | my jobs, newest first | 200 |
| GET | `/jobs/{id}` | owner or admin | — | status, progress %, counts, result/error file URLs | 200, 404 |
| GET | `/jobs/{id}/files/{errors\|result}` | owner or admin | — | XLSX | 200, 404 |

### Enrolment (7.5)

| Method | Path | Perm | Request | Response | Codes |
|---|---|---|---|---|---|
| GET | `/enrolment/offerings?year` | public (school code) | — | classes, combinations, places left, requirements | 200 |
| POST | `/enrolment-applications` | public + OTP-verified phone, or enrolment.manage | class, combination?, year, applicant, guardians, consent | application (REQUIREMENTS_PENDING) | 201, 409, 422 |
| GET | `/enrolment-applications` | enrolment.manage, enrolment.validate | `?status&class&cursor` | page | 200 |
| GET | `/enrolment-applications/{id}` | self or staff | — | application + documents | 200, 404 |
| POST | `/enrolment-applications/{id}/documents` | self or enrolment.manage | multipart requirement_id, file | document | 201, 409, 422 |
| POST | `/enrolment-applications/{id}/submit` | self or enrolment.manage | — | UNDER_REVIEW | 200, 422 (missing) |
| PATCH | `/enrolment-documents/{id}` | enrolment.validate | status VALID/INVALID, comment | application status | 200, 422 |
| GET | `/enrolment-documents/{id}/download` | enrolment.validate or self | — | 307 signed URL (5 min) | 307 |
| POST | `/enrolment-applications/{id}/approve` | enrolment.decide | stream_id, combination_id? | enrolment + admission_no | 200, 409 (full) |
| POST | `/enrolment-applications/{id}/reject` · `/cancel` | enrolment.decide / self (cancel) | reason | application | 200, 409 |

### Timetable and exams (7.8, 7.10)

| Method | Path | Perm | Request | Response | Codes |
|---|---|---|---|---|---|
| GET | `/timetable?term&stream\|staff\|room` | timetable.read (self for students/parents) | — | slots (ETag) | 200, 304 |
| POST | `/timetable/check` | timetable.manage | slot | ok, conflicts[], problems[], free_slots[] | 200 |
| POST | `/timetable/slots` | timetable.manage | term, stream, subject, staff, room, day, start, end | slot | 201, 409, 422 |
| PATCH / DELETE | `/timetable/slots/{id}` | timetable.manage | partial / reason | slot | 200, 204, 409 |
| POST | `/timetable/generate` (Idempotency-Key) | timetable.manage | term, stream_ids, persist | draft or job | 200, 202 |
| GET | `/timetable/print?…` | timetable.read | — | PDF | 200 |
| GET / POST / PATCH / DELETE | `/exam-sessions[/{id}]` | exams.manage | term, names, kind, dates | item | 201, 422 |
| GET / POST / PATCH / DELETE | `/exams[/{id}]` | exams.read / exams.manage | session, class, subject, date, start, end, room | paper | 201, 409 (clash) |

### Marks and results (7.11)

| Method | Path | Perm | Request | Response | Codes |
|---|---|---|---|---|---|
| GET | `/marks/sheet?term&stream&subject` | marks.enter (own assignment) | — | students × components with score, version (ETag) | 200, 403 |
| PUT | `/marks/batch` | marks.enter | [{enrolment_id, subject_id, component_id, score, is_absent, version, client_updated_at}] | per item: ok / conflict (server value) / error | 200 (per-item results), 422 |
| POST | `/marks/upload` (Idempotency-Key) | marks.enter | XLSX template | job | 202 |
| GET | `/results/firewall?term&class` | results.publish | — | problems[] (same as 422 details) | 200 |
| POST | `/results/publish` (Idempotency-Key) | results.publish | term_id, class_id | publication_id, report-card job | 201, 422 `INCOMPLETE_GRADES_BLOCK` |
| GET | `/results?term&class\|stream` | results.read | — | current results + summaries | 200 |
| GET | `/students/{id}/results?term` | results.read or self | — | subjects, grades, division, positions, amended flags | 200, 404 |
| GET | `/students/{id}/report-card?publication` | results.read or self | — | 307 signed PDF URL | 307, 404 |
| PUT | `/publications/{id}/comments/{enrolment}` | marks.enter (class teacher), results.publish (head) | class_teacher_comment / head_teacher_comment | comments | 200 |
| POST | `/published-results/{id}/amendments` | results.amend_request | new_score, reason | amendment PENDING | 201, 409 (superseded) |
| POST | `/amendments/{id}/approve` · `/reject` | results.amend_approve | note | new version / rejected | 200, 403 (maker = checker), 409 |
| GET | `/analytics/results?term&class` | results.read | — | subject averages, grade distribution, teacher performance, trends | 200 |

### Attendance and devices (7.9)

| Method | Path | Perm | Request | Response | Codes |
|---|---|---|---|---|---|
| GET | `/attendance/sessions/today?stream` | attendance.take | — | session + class list (ETag) | 200 |
| POST | `/attendance/sync` | attendance.take | [{client_record_id, session {date, kind, stream}, student_id, status, captured_at}] | per item: synced / conflict | 200 |
| GET | `/attendance/reports?stream\|student&from&to` | attendance.read or self | — | summary + daily rows | 200 |
| GET | `/attendance/chronic?week` | attendance.read | — | `v_chronic_absence` rows | 200 |
| POST | `/devices/taps` | device (`X-Device-Key`) | [{token, captured_at, client_record_id}] | per tap: student name / unknown | 200, 401 |
| GET / POST / PATCH | `/devices[/{id}]` | attendance.device | name, kind, location → API key shown once | device | 201 |
| POST / PATCH | `/rfid-cards[/{id}]` | attendance.device | student, token, kind / status LOST | card | 201, 409 |

### Fees and payments (7.12)

| Method | Path | Perm | Request | Response | Codes |
|---|---|---|---|---|---|
| GET / POST / PATCH | `/fee-items[/{id}]` | fees.configure | code, names, gfs_code, income_account | item | 201, 409 |
| GET / POST / PATCH | `/fee-structures[/{id}]` | fees.configure | year, class, name, lines[{item, term?, amount, optional}] | structure (DRAFT) | 201, 409 |
| POST | `/fee-structures/{id}/approve` | fees.configure + settings.update | — | APPROVED | 200, 409 |
| GET / POST | `/discount-rules`, `/students/{id}/discounts` | fees.configure | rule / {rule, year, reason} | item | 201, 409 |
| POST | `/invoices/generate` (Idempotency-Key) | invoices.manage | term_id, class_ids, installments[] | job | 202 |
| GET | `/invoices?status&class&due_before&cursor` | finance.read | — | page | 200 |
| GET | `/invoices/{id}` | finance.read or self | — | invoice, lines, installments, allocations, control number | 200, 404 |
| POST | `/invoices/{id}/cancel` | invoices.manage | reason | CANCELLED | 200, 409 (has payments) |
| POST | `/invoices/{id}/control-number` | invoices.manage | — | GePG bill (REQUESTED) | 202 |
| POST | `/payments` (Idempotency-Key) | payments.record | student, channel CASH/BANK, external_ref, amount, payer, received_at | payment, allocations, receipt | 201, 409 (duplicate ref), 422 |
| POST | `/payments/{id}/reversal-requests` | payments.reverse_request | reason | request | 201, 409 |
| POST | `/reversal-requests/{id}/approve` | payments.reverse_approve | — | reversal + journal | 200, 403 (same person) |
| POST | `/payments/push` | portal.parent | invoice_id, phone, channel | `{status: SENT}` (USSD prompt on the phone) | 202, 422 |
| GET | `/students/{id}/statement` | finance.read or self | — | invoices, payments, credit, balance | 200, 404 |
| POST | `/bank-deposits` | payments.record or portal.parent | bank_reference, date, amount, student | SUBMITTED | 201, 409 |
| GET | `/bank-deposits?status=SUBMITTED` | payments.confirm_bank | — | page | 200 |
| POST | `/bank-deposits/{id}/confirm` · `/reject` | payments.confirm_bank | note | payment created / rejected | 200, 409 |
| GET / POST | `/reconciliation-runs[/{id}]` | reconciliation.run | date, channel, statement file | run + items | 201, 202 |
| PATCH | `/reconciliation-items/{id}` | reconciliation.run | resolution note, payment_id? | item | 200 |
| GET | `/reports/fees/aging`, `/defaulters`, `/collections?from&to` | finance.read | filters | rows / XLSX / PDF | 200, 202 |

### Webhooks (no JWT; signature + IP allow-list; idempotent)

| Method | Path | Perm | Request | Response | Codes |
|---|---|---|---|---|---|
| POST | `/webhooks/gepg/bill` | signed | control-number response XML | signed ACK XML | 200, 401 |
| POST | `/webhooks/gepg/payment` | signed | payment notification XML | signed ACK (`TrxStsCode` 7101 — **VERIFY**) | 200, 401 |
| POST | `/webhooks/mpesa` · `/tigopesa` · `/airtel` · `/halopesa` | signed | provider JSON | provider ACK | 200, 401 |
| POST | `/webhooks/sms/{provider}` | signed | delivery report | 204 | 204, 401 |

### Facilities and student life (7.13–7.17, 7.19)

| Method | Path | Perm | Request | Response | Codes |
|---|---|---|---|---|---|
| GET / POST / PATCH | `/hostels[/{id}]`, `/hostel-rooms[/{id}]` | hostel.manage | names, gender, warden / room, capacity | item | 201 |
| POST | `/accommodation-requests` | portal.student, portal.parent | term, preferred_hostel | PENDING | 201, 409 |
| POST | `/accommodation-requests/{id}/decide` | hostel.manage | APPROVED/REJECTED, room_id | allocation | 200, 422 (room full) |
| GET | `/hostels/{id}/occupancy?term` | hostel.manage | — | rooms × beds | 200 |
| GET / POST / PATCH | `/buses`, `/routes`, `/routes/{id}/stops` | transport.manage | bus_no, capacity, driver / name, fee / seq, name, time | item | 201, 422 |
| POST / DELETE | `/transport-assignments[/{id}]` | transport.manage | student, route, bus, stop, term | assignment (+ fee line) | 201, 422 (bus full) |
| GET / POST / PATCH / DELETE | `/venues`, `/venue-events` | venues.manage | name, seats / venue, date, times, seats | item | 201, 409 (overlap) |
| GET / POST / PATCH | `/discipline-records[/{id}]` | discipline.read / discipline.manage | student, date, category, description, action, resolution | record (+ parent SMS) | 201, 422 |
| GET / POST / PATCH | `/activities`, `/activities/{id}/members` | activities.manage | name, kind, patron / student, role | item | 201, 409 |
| GET / POST | `/library/books`, `/library/loans`, `/library/loans/{id}/return` | library.manage | book / borrower, due / — | item | 201, 422 (no copies) |
| GET / POST | `/students/{id}/health-records` | health.read / health.manage + consent | date, kind, notes | records (audit VIEW_SENSITIVE) | 200, 201, 403 |

### Communication (7.18)

| Method | Path | Perm | Request | Response | Codes |
|---|---|---|---|---|---|
| GET / POST | `/announcements` | any / announcements.send | title, body, language, audience, class/stream/user, send_sms, publish_at (Idempotency-Key when SMS) | item + SMS job | 201, 422 (credit) |
| GET | `/notifications` · POST `/notifications/{id}/read` | self | — | inbox | 200, 204 |
| GET / PUT | `/message-templates[/{key}/{lang}]` | sms.manage | body with `{placeholders}` (validated) | template | 200, 422 |
| GET | `/sms?status&from&to` | sms.manage | — | SMS log (masked numbers) | 200 |
| GET / POST | `/sms/credit` | sms.manage | top-up note (platform-confirmed) | balance, history | 200, 201 |

### Parent and student portals (read models)

| Method | Path | Perm | Response |
|---|---|---|---|
| GET | `/parent/children` | portal.parent | children with class, today's attendance, balance (< 5 KB, ETag) |
| GET | `/parent/children/{id}/attendance?month` | portal.parent | days and status |
| GET | `/parent/children/{id}/results` | portal.parent | published results, report-card links |
| GET | `/parent/children/{id}/invoices` | portal.parent | invoices, control numbers, receipts |
| GET | `/student/me/timetable` · `/results` · `/fees` | portal.student | own data |

### Reports, compliance, privacy, audit (7.20, 7.21)

| Method | Path | Perm | Request | Response | Codes |
|---|---|---|---|---|---|
| GET | `/dashboards/{role}` | role | — | KPI tiles + charts data | 200 |
| GET | `/reports/{type}` | reports.read | `type = enrolment\|attendance\|results\|fees\|staff\|student-status\|transactions`, filters | preview rows | 200 |
| POST | `/reports/{type}/export` (Idempotency-Key) | reports.export | filters, format pdf/xlsx/csv, lang | job | 202 |
| POST | `/compliance-exports` | reports.export | template, year | job (audit EXPORT) | 202 |
| GET / POST / PATCH | `/data-subject-requests[/{id}]` | privacy.manage | subject, type, details / status, result | request | 201, 200 |
| GET | `/audit-logs?entity&entity_id&actor&from&to&cursor` | audit.read | — | page (redacted JSON) | 200 |

## 12.3 Phase 2 implementation notes

What the built API does where it differs from, or adds to, the catalogue above (OpenAPI at `/docs` is authoritative):

| Area | As built | Why |
|---|---|---|
| Timetable generation | `POST /timetable/generate` answers in the same request: `persist=false` returns a draft `{placed, unplaced}`, `persist=true` saves it (optionally `replace`) in one transaction | A few streams take well under a second; no job needed ([ADR 0015](adr/0015-timetable-generator.md)) |
| Bell schedule | Default grid Monday–Friday, nine 40-minute periods, tea 10:40–11:00, lunch 13:00–14:00 — **VERIFY** per school; manual slots may use any times | No period table yet |
| Teaching assignments | `GET /teaching-assignments?academic_year_id&stream_id\|staff_id\|mine=true`; `PUT …?academic_year_id&stream_id` replaces one stream | Teachers find their own classes without knowing their staff id |
| Marks sync | `PUT /marks/batch` → per item `ok` (new version), `conflict` (with the server value) or `error` (`locked`, `out_of_range`, `forbidden`, `not_applicable`, `invalid_reference`); the same value sent with an old version counts as `ok` | Offline devices resolve conflicts without losing work |
| Marks upload | `GET /marks/template` + `POST /marks/upload` (multipart term, stream, subject, file; Idempotency-Key) → all-or-nothing job | Same rules as the API batch |
| Report cards | `GET /students/{id}/report-card?term_id&lang` returns the PDF directly, always built from the current (amended) results; `GET /results/report-cards?term_id&class_id` returns the class bundle made by the job | Never stale; local storage has no signed URLs ([ADR 0014](adr/0014-report-cards.md)) |
| Amendments | `GET /amendments?status` added (approvers see all, requesters their own); approve/reject return 403 `maker_checker` when the approver is the requester | Approval queue |
| Results | `GET /results` pages students by class position; rows carry `student_id` for the report card | Responses stay < 100 KB |
| Enrolment | Families apply from a signed-in parent session (SMS-code login) instead of a separate "OTP-verified phone" step; `GET/POST/DELETE /enrolment-requirements` added; documents are streamed by `GET /enrolment-documents/{id}/download` | One login flow for parents |
| Promotions | `POST /promotions` (Idempotency-Key) → `PROMOTION` job: promote, repeat or graduate every active enrolment of a year, all-or-nothing | |
| Exams | Sessions must lie inside the term (`outside_term`), papers inside the session (`outside_session`); clashes → 409 | |

## 12.4 Phase 3 implementation notes

What the built finance API does where it differs from, or adds to, the catalogue above:

| Area | As built | Why |
|---|---|---|
| Fee structures | `GET/POST/PATCH /fee-structures`, `POST …/approve` (fees.configure **and** settings.update), `POST …/archive` (APPROVED only), `DELETE` (DRAFT only); totals are returned per term id or `yearly` | An approved structure is never edited, only archived |
| Discounts | A percent rule applies to the TUITION lines; a fixed amount is one DISCOUNT line | Siblings and staff children get tuition relief, not a share of meals or exams |
| Invoice generation | `POST /invoices/generate` (Idempotency-Key) → `INVOICE_RUN` job, one transaction for all classes; a class without an approved structure is a `no_fee_structure` problem and nothing is billed; yearly lines go on the first term only; optional lines are excluded; students already billed for the term are skipped; existing credit is applied at once (ADJUSTMENT journal) | All-or-nothing, safe to repeat |
| Installments | `installments[{due_date, percent}]`, percents sum to 100, the last installment takes the rounding remainder | Totals always equal the invoice |
| Cash and bank slips | `POST /payments` (CASH/BANK only, Idempotency-Key) answers synchronously with the allocations and the receipt number | The bursar hands the receipt over at the counter |
| Allocation | Every confirmed payment is allocated at once: the invoice of the control number first, then oldest due; any remainder is the student's credit (account 2100) and pays the next invoice | No "unallocated" queue to clear by hand |
| Amount mismatch | A GePG payment that differs from the bill amount is still accepted, allocated and receipted; `raw_payload.amount_matches_bill=false` flags it and reconciliation reports it | Money already taken must not bounce |
| Reversals | `POST /payments/{id}/reversal-requests` writes a `payment_reversal_requests` row (one PENDING per payment); `GET /reversal-requests?status`; approve/reject by another person (`403 maker_checker`) | The original design had no place to keep a request before approval |
| Bank deposits | `GET /bank-deposits?status=PENDING` (the catalogue said SUBMITTED); confirm creates the BANK payment and receipt | Status names follow the schema |
| Control numbers | `POST /invoices/{id}/control-number` → `gepg.submit` task; `409 open_bill` while a bill is open; simulator mode (`SSMS_GEPG_MODE=simulator`) answers with a `99…` number at once | Development and E2E without GePG |
| GePG messages | XML `<Gepg><inner/><gepgSignature/></Gepg>`, RSA PKCS#1 v1.5 SHA-256 over the exact inner bytes, DOCTYPE/ENTITY refused, 64 KB body limit, ACK `TrxStsCode` 7101 — **VERIFY** all with the GePG SP specification | Signature and codes are not public |
| Mobile money | `POST /webhooks/{mpesa,tigopesa,airtel,halopesa}` JSON `{transaction_id, reference, amount, msisdn, payer_name, timestamp}` with `X-SSMS-Signature: sha256=<HMAC>`; reference = 12-digit control number or `<school code>.<admission no>`; answers `ACCEPTED`, `DUPLICATE` or `REJECTED` — **VERIFY** with the chosen aggregator | One adapter for all wallets ([ADR 0016](adr/0016-payment-channels.md)) |
| Push prompt | `POST /payments/push` is allowed to the guardian of the invoice's student or to `payments.record`; provider `console` in development | |
| Parent portal | `GET /me/children` returns each child with class, stream, outstanding and credit | One call for the parent home screen |
| Reports | `/reports/fees/aging`, `/defaulters`, `/collections?from&to`; `format=xlsx` gives Excel; money is always a decimal string (`"0.00"`) | No float rounding in clients |
| Reminders | `POST /fees/reminders/run` and the daily 09:00 EAT beat send one SMS per overdue installment (idempotency key `reminder:{invoice}:{seq}`) | Never twice for the same installment |

## 12.5 Phase 4 implementation notes

What the built attendance and communication API does where it differs from, or adds to, the catalogue above:

| Area | As built | Why |
|---|---|---|
| Register | `GET /attendance/register?stream_id&date` (default today in EAT; ETag) replaces `/attendance/sessions/today`; `GET /attendance/my-streams`; `POST /attendance/sessions/{id}/close` | A phone that was offline needs the register of the day it marked |
| Who takes it | The stream's class teacher, any teacher of the stream (cover), or the school office (`settings.update`); readers (`attendance.read`) see every register | Teachers cover absent colleagues |
| Offline sync | `POST /attendance/sync` items carry `client_record_id` and `captured_at`; per item `synced`, `conflict` (another phone marked later: the server value is returned) or `error` (`not_enrolled`, `forbidden`, `not_school_day`, `future_date`, `too_old` beyond 7 days) | Later mark wins; nothing is lost silently |
| School days | Weekends, `public_holidays` (national or school closure) and days outside a term are refused for registers and taps | One rule for registers, taps and alerts |
| Reports | `GET /attendance/reports?stream_id&from&to[&format=xlsx]` (≤ 366 days), `GET /attendance/chronic?week`, `GET /students/{id}/attendance?from&to` (staff, the student's guardians or the student) | One per-student endpoint serves staff, parents and students |
| Devices | `/devices` and `/rfid-cards` need `attendance.device` **or** `settings.update` (the school office can register the gate reader); `POST /devices/{id}/rotate-key`; a new card replaces the active card of the same kind (old one REVOKED) | The seed gives school_admin no `attendance.device` |
| Gate taps | `POST /devices/taps` (X-Device-Key, 600 taps/min per device): `present`, `late` (after the absence cut-off — **VERIFY** whether schools want a separate start time), `duplicate` (first tap of the day counts), `unknown_card`, `not_school_day`, `out_of_window`; device firmware format **VERIFY** | No school start time in the schema |
| Absence alerts | Beat every 5 min, Mon–Fri 08:00–12:59; each school acts between its cut-off and 12:00 (**VERIFY**). Absent = register says ABSENT, or no register for the stream while the gate is in use and the student has no tap; a tap or PRESENT/LATE/EXCUSED always wins | A school that records nothing must never alarm every parent ([ADR 0017](adr/0017-absence-evidence.md)) |
| SMS credit | Each message DEBITs its segments when queued; without credit it is stored SKIPPED (`no_credit`); sign-in codes and new-account passwords are never blocked; a permanent provider failure adds a REFUND; below 100 credits users with `sms.manage` get an in-app notice; rows are append-only | [ADR 0018](adr/0018-sms-credit-ledger.md) |
| Top-up | `POST /platform/schools/{id}/sms-credit` (console) instead of a school-side POST; schools read `GET /sms/credit` (balance, low flag, top-ups and refunds) | Credit is bought from the platform |
| Delivery reports | `POST /webhooks/sms/{beem\|nextsms}?token=<SSMS_SMS_WEBHOOK_SECRET>`; routed by the new resolver `resolve_sms_message`; DELIVERED is never undone by a later report; formats **VERIFY** | Providers do not sign reports |
| Announcements | `POST /announcements` with `send_sms` needs an Idempotency-Key and checks credit first (`422 NO_SMS_CREDIT`, nothing saved); SMS go to guardians who receive SMS (consent) of actively enrolled students in the audience and to active staff, by an `SMS_BATCH` job; `INDIVIDUAL` also lands in the inbox; `DELETE /announcements/{id}` | Never half-send an announcement |
| Inbox | `GET /notifications` → `{unread, items}`; `POST /notifications/{id}/read`, `POST /notifications/read-all` | |
| Templates | `GET /message-templates` lists the 6 keys × 2 languages with defaults; `PUT /message-templates/{key}/{lang}` allows only the key's own placeholders and at most 3 SMS with a 40-character school name | Sign-in code text stays fixed |
| Portals | `GET /me/children` adds `today_status`, `gate_in_at`, `stream_id`; `GET /me/student`, `GET /me/timetable`; details reuse `/students/{id}/attendance`, `/results`, `/report-card`, `/statement`, `/announcements` instead of `/parent/children/{id}/…` | Same access checks, fewer endpoints |

## 12.6 Phase 5 implementation notes

What the built facilities and student-life API does where it differs from, or adds to, the catalogue above:

| Area | As built | Why |
|---|---|---|
| Errors | A full room, bus or book → `422 FULL` with `room_full`, `bus_full`, `no_copies`; too many seats → `422 FULL too_many_seats`; venue overlap → `409 VENUE_CLASH`; second open request/assignment/loan of a kind → `409 DUPLICATE` | The database guards (fn_capacity_guard, EXCLUDE, partial unique indexes) are the rule; the API only names them |
| Accommodation | `POST /accommodation-requests`: a student for themselves, a guardian for their own child (`403 not_own_child`), the hostel office for anyone; `GET` shows each caller only theirs; `POST /{id}/cancel` while pending; `POST /hostel-allocations/{id}/vacate`; a single-gender hostel refuses the other gender (`wrong_gender`) | Families apply from the portal |
| Facility fees | Approving a room adds the class structure's optional BOARDING line, and assigning transport adds the route's term fee, to the student's open invoice for the term (journal posted, last installment grows, credit used); without an invoice, generation adds them; ending/vacating never refunds automatically | One invoice per term ([ADR 0019](adr/0019-facility-fees-on-the-term-invoice.md)) |
| Transport | `GET /buses?term_id` returns seats used/free; `PATCH /routes/{id}` with `stops` replaces all stops, refused while anyone rides the route; the stop must belong to the route and the bus be ACTIVE | |
| Venues | `GET /venue-events?venue_id&from&to` (default next 90 days) for any signed-in user; `DELETE` soft-cancels | Everyone can see the hall calendar |
| Discipline | Teachers record (`discipline.manage`); the recorder or a `discipline.read` holder updates; `resolve=true` needs a resolution (`422 required`); RESOLVED is final; the primary guardian who receives SMS is told once (`discipline_notice`) | Matches the wireframe "Mzazi atajulishwa kwa SMS" |
| Clubs | Memberships are for the current year; `activities.manage` **or the club's patron** adds and removes members; `GET /me/activities` for students | Patrons are teachers without activities.manage |
| Library | Loans to any user, or to a student by `admission_no`; due in 14 days by default; copies cannot drop below books on loan; `POST /library/reminders/run` and a weekday 10:00 job send one `library_overdue` SMS per loan per week (students: primary guardian; staff: themselves); `GET /me/loans` | FR-63 overdue reminders |
| Health | `GET/POST /students/{id}/health-records` need `health.read`/`health.manage` **and** a guardian's HEALTH_DATA consent (`403 no_consent`); notes encrypted (`health_records.notes`); every list is audited `VIEW_SENSITIVE`; unreadable notes come back `null` | PDPA |

## 12.7 Phase 6 implementation notes

| Area | As built | Why |
|---|---|---|
| Reports | `GET /reports/{enrolment\|attendance\|results\|fees\|staff\|student-status\|transactions}` with `academic_year_id, term_id, class_id, stream_id, date_from, date_to, status` returns `{columns, rows (first 200, as text), total}`; `results` needs `term_id`; ranges ≤ 400 days. `fees`/`transactions` also need `finance.read`, `staff` needs `staff.read`/`staff.manage` | One query per report serves preview and export |
| Export | `POST /reports/{type}/export` (Idempotency-Key, `format` xlsx/csv/pdf) → EXPORT job, audited `EXPORT`; the file comes from `GET /jobs/{id}/files/result` with the right type and extension (CSV has a BOM for Excel) | Large reports never block a request |
| Dashboards | `GET /dashboards/{admin\|bursar\|teacher}` needs `settings.update` / `finance.read` / `attendance.take`; tiles + small series, cached 60 s per school and role (per user for teachers) | A busy morning does not recompute them per view |
| Compliance | `POST /compliance-exports` `{templates: [ENROLMENT, ATTENDANCE, RESULTS, STAFF], academic_year_id, format}` → COMPLIANCE_EXPORT job; Excel has one sheet per template, CSV/PDF take one template; layouts **VERIFY** with the ministry | FR-68 |
| Data-subject requests | `GET/POST /data-subject-requests`, `PATCH /{id}` (IN_PROGRESS, COMPLETED for CORRECT only, REJECTED, with a note), `POST /{id}/export` (JSON of everything held, completes it), `POST /{id}/anonymise` (DELETE: removes identity, contacts, identifiers, login, consents, health notes; keeps ledgers, receipts, published results; refused for active staff and oneself), `GET /{id}/file`; due 30 days (**VERIFY**), `overdue` flag | PDPA 2022 ([ADR 0021](adr/0021-anonymise-not-delete.md)) |
| Operations | `GET /metrics` (Prometheus; internal, optional bearer token), JSON logs, optional Sentry; `SSMS_WEBHOOK_REQUESTS_PER_MINUTE` (default 6,000 per IP) | NFR-13 ([ADR 0020](adr/0020-observability.md)) |

## 12.8 Example

```http
PUT /api/v1/marks/batch
Authorization: Bearer eyJ...
Content-Type: application/json

[{"enrolment_id":"00000018-…-000000000011","subject_id":"0000000f-…-000000000009",
  "component_id":"…","score":"78.50","is_absent":false,"version":3,"client_updated_at":"2026-05-28T12:00:01Z"}]
```

```json
HTTP/1.1 200 OK
{"results":[{"key":"…","status":"CONFLICT","server_score":"74.00","server_version":4,
             "message":"Alama imebadilishwa na mtumiaji mwingine. Chagua thamani sahihi."}]}
```

## Design alignment changes (2026-10-31)

- Paged lists return at most 50 rows (`limit` above 50 → 422); report previews show the first 50 rows and the total.
  The web client follows `next_cursor` where it needs a whole list. Short reference lists (subjects, classes) are not paged.
- `GET /staff/{id}/subjects`, `PUT /staff/{id}/subjects` `{subject_ids}`: the subjects a teacher is qualified to teach.
  Timetable slots report the problem `not_qualified` (422); the generator reports it under `unplaced`.

## Normalisation changes (2026-10-31)

- `POST /transport-assignments` no longer takes `route_id`: the stop decides the route. Responses and the `route_id`
  filter on `GET` are unchanged.
- `POST /enrolment-requirements` refuses `education_level_id` and `class_id` together (422).
- `matched_count` and `exception_count` on reconciliation runs are unchanged for clients, but now counted from the items.

## Locations and room equipment (2026-10-31)

- `GET /platform/regions`: regions with their districts. `POST /platform/schools` takes `district_id` instead of `region`
  and `district` text (unknown id → 422). School responses still show `region` and `district` as names.
- `GET /rooms?equipment_id=<id>`: rooms that have it; repeat the parameter to need all of them.
- `equipment` on rooms is now a list of `{name, quantity}` on input and `{equipment_id, name, quantity}` on output. On
  `PATCH /rooms/{id}` it replaces the whole list; leaving it out changes nothing. A new name creates the item.
- `GET /equipment-items` (with `rooms`, how many rooms have it), `PATCH /equipment-items/{id}` (rename),
  `DELETE /equipment-items/{id}` (409 while a room has it).
