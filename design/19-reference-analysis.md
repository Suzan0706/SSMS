# 19. Reference analysis and extended requirements (Phase 1)

This phase compares SSMS with the Weblizar *School Management* product and adds the requirements needed to cover
its major features. SSMS is already built (documents 01–18, migrations 0001–0010, 179 API routes, 99 tables).
This is a **gap analysis and extension**, not a new design: nothing that works is replaced.

Sources studied on 2026-10-31:

| Source | What it gave |
|---|---|
| weblizar.com/documentation/school-management | Module list, field lists, workflows (admission, promotion, invoices, exams, library cards) |
| demo.weblizar.com/school-management | The 8 demo roles; signed in with the vendor's public demo accounts (view only) for Super Admin, Teacher, Accountant and Librarian, and recorded each role's menu and dashboard. School Admin and Receptionist sign-ins failed. |
| theschool-management.com/screenshort | Screenshots of the module dashboards, attendance sheet, invoice, report card, ID card and admit card |

The reference is a WordPress plugin (PHP). Only behaviour and workflows are taken from it: no code, text or images.

## 19.1 What the reference is

### Roles and menus

| Reference role | Menus seen in the demo | SSMS today |
|---|---|---|
| Super Admin | All 18 menus: School, Academic, Student, Administrator, Accounting, Examination, Library, Lessons, Transport, Hostel, Tickets, Stationary, Activities, Gate Pass, Reports, Chat, Login Security | Platform admin in a separate console (`platform_admins`, password + TOTP, `/platform/*`) |
| School Admin | One school, all modules, creates roles and staff | `school_admin` |
| Teacher | Academic (subjects, timetables, attendance, study materials, homework, notices, events, holidays, live classes), Examination (all), Lessons, own leave and attendance | `teacher`, `department_head` |
| Accountant | In the demo: notices, inquiries, admissions, students, ID cards, certificates (the demo account has no Accounting menu) | `bursar` |
| Receptionist | Not seen (sign-in failed) | none |
| Librarian | Library (books, issued books, library cards), notices, lessons | `librarian` |
| Student | Front-end dashboard: notices, ID card, attendance, exam timetable, admit card, study materials, homework, invoices, online payment, payment history | `student` |
| Parent | Listed on the demo page; the documentation describes parents only as SMS recipients | `parent` (phone + SMS code) |

### The 13 dashboard tiles (School Dashboard, per current session)

Active inquiries, active students, total classes, total staff, total income, fees collected, pending dues, unpaid
invoices, total expenses, total books, pending student leaves, pending staff leaves; plus a school calendar
(exam / event / holiday), the last 10 inquiries and the last 15 admissions.

### Interface patterns worth adopting

1. A **current session selector** at the top of every page: all lists and totals follow the selected session.
2. A **dashboard per module** (adopted on 2026-10-31: `/m/:key` pages).
3. **Print views** with a school letterhead for every document: ID card, attendance sheet, invoice, receipt,
   exam timetable, admit card, result, certificate.
4. **Bulk actions**: bulk admission (CSV), bulk invoices, bulk print of admit cards, results and invoices.
5. Tables with search, sorting and paging (*"Showing 1 to 5 of 5 records"*).

### Weaknesses not to copy

- Generic WordPress admin pages; inconsistent styles between modules.
- The parent role is barely developed.
- Demo data is shared between visitors: the teacher dashboard showed other visitors' names, phone numbers and emails.
  SSMS keeps per-school isolation in the database (RLS, ADR 0001), and parents only ever see their own children.
- Card payments only (Stripe, PayPal, Razorpay, Pesapal, Paystack). Tanzanian schools need GePG control numbers and
  mobile money (ADR 0016).

## 19.2 Gap analysis against the brief

The brief is the "Complete School Management System" brief of 2026-10-31. Status: **H** = have (built and tested),
**P** = partly built, **M** = missing. "Where" points to the existing code or design.

### A. Dashboard

| Feature | Status | Where / what is missing |
|---|---|---|
| Totals: students, teachers, staff | H | `GET /analytics/dashboard` |
| Total schools | P | Platform console lists schools; no platform dashboard tiles |
| Attendance statistics | H | Dashboard "attendance today", chronic absence |
| Fee collection, pending payments | H | Collected, outstanding, collection rate |
| Upcoming exams | M | `exams` has dates but the dashboard does not show them |
| Recent activities | P | `audit_logs` exists; no dashboard feed |
| Academic performance charts | P | Students by class only; no mean score per class or subject |
| Announcements | H | Announcements page; not on the dashboard |
| One dashboard per role | P | Staff dashboard, parent and student homes; no teacher, librarian or receptionist dashboard |

### B. Multi-school management

| Feature | Status | Where / what is missing |
|---|---|---|
| Register and edit schools | H | `POST/PATCH /platform/schools`, FR-08/09 |
| Assign administrators | H | Onboarding creates the first `school_admin`; school admins create staff |
| School settings | H | `school_settings` |
| Statistics per school | M | Console has no per-school figures |
| One person working in several schools | H | Parents already choose a school; staff accounts are per school by design (ADR 0001) |

### C. Academic sessions

| Feature | Status | Where |
|---|---|---|
| Create sessions, dates, set current | H | `academic_years`, `terms` (one current year, DB-enforced) |
| History kept | H | Enrolments and frozen results per year (ADR 0005) |
| Promotion between sessions | H | `services/promotions.py` |
| Session selector in the interface | M | Top bar shows the current year only |

### D. Classes and sections

| Feature | Status | Where |
|---|---|---|
| Classes and sections | H | `classes` and `streams` (a stream is a section) |
| Class teacher, subject teachers | H | `stream_class_teachers`, `teaching_assignments` |
| Subjects per class | H | `class_subjects`, A-Level `combinations` |
| Capacity | H | `streams.capacity` |

### E. Students

| Feature | Status | Where / what is missing |
|---|---|---|
| Registration, admission number | H | `students.admission_no` from `document_sequences` |
| Enrolment number per session | P | `enrolments` row per year; no printed enrolment number |
| Profiles, guardians | H | `students`, `guardians`, `student_guardians` |
| Photograph | P | Column and privacy rules exist; no upload screen |
| Medical information | H | `health_records` (consent-gated, encrypted) |
| ID card | M | — |
| Promotion, transfer | H | Promotion service; transfer out with status history |
| CSV import / export | P | Import done (ADR 0013); export missing |

### F. Teachers and staff

| Feature | Status | Where / what is missing |
|---|---|---|
| Registration, profile, departments, qualifications, employment | H | `staff`, `departments`, `designations`, `staff_qualifications` |
| Teacher–class assignment | H | `teaching_assignments` |
| Staff attendance | M | Gate devices record students only |
| Leave management | M | Neither staff nor student leave |
| Staff permissions | H | Roles and permissions (ADR 0011) |

### G. Attendance

| Feature | Status | Where / what is missing |
|---|---|---|
| Daily class register, present/absent/late/excused | H | `attendance_sessions`, `attendance_records`, offline (ADR 0008) |
| Subject (period) attendance | M | — |
| Teacher and staff attendance | M | — |
| Reports, monthly statistics | P | Rates per student per period; no monthly grid (days × students) |
| Parent alert on absence | H | `absence_alerts` and SMS (ADR 0017) |

### H. Examinations

| Feature | Status | Where / what is missing |
|---|---|---|
| Exams, types, schedule | H | `exam_sessions` (kind: monthly, midterm, terminal, annual, mock); `exams` = one paper with date, start and end time |
| Papers, rooms, centres | P | Each paper has a room; class and room clashes are refused by the database. Missing: a printable exam timetable and the NECTA centre number |
| Mark entry, grading, totals | H | `mark_entries`, `grading_schemes`, `grade_bands` |
| GPA | P | Grade points exist; division for O-Level. GPA for A-Level — **VERIFY** the NECTA A-Level GPA rule before building |
| Class and stream position | H | `student_term_summaries` |
| Subject ranking | M | — |
| Report cards, PDF, publishing | H | ADR 0014, `publish_results()` with maker-checker |
| Admit cards | M | — |

### I. Fees and accounting

| Feature | Status | Where / what is missing |
|---|---|---|
| Fee items, structures, invoices, bulk invoices | H | `fee_items`, `fee_structures`, `invoices` (background job) |
| Partial and full payments, history, balances | H | `payments`, `payment_allocations`, installments |
| Discounts | H | `discount_rules`, `student_discounts` |
| Fines | M | No late-payment or library fines |
| Receipts | H | `receipts`, PDF |
| Income and expenses | M | The double-entry ledger exists (ADR 0006) but has no screens or categories for other income or expenses |
| Financial reports | P | Aging, collections, reconciliation; no income statement |
| Online payment | H | GePG control numbers and mobile money (ADR 0016). Card gateways are out of scope |

### J. Library

| Feature | Status | Where / what is missing |
|---|---|---|
| Books, ISBN, authors, availability, lending, returns | H | `library_books`, `library_loans` |
| Categories, publishers | M | — |
| Overdue list | H | Overdue loans query |
| Library cards | M | — |
| Fines, reports | M | — |

### K. Homework and study materials — all missing

Assign homework, deadlines, student submissions, teacher feedback, uploaded materials, materials per class.

### L. Timetable

| Feature | Status | Where |
|---|---|---|
| Class and teacher timetables, subjects, rooms | H | `timetable_slots`, generator (ADR 0015) |
| Conflict detection | H | Teacher, stream and room clashes are refused by the database |

### M. Transport

| Feature | Status | Where / what is missing |
|---|---|---|
| Vehicles, routes, stops, assignments | H | `buses`, `routes`, `route_stops`, `transport_assignments` |
| Drivers | P | Driver name and phone on the bus; no driver records |
| Route fees | H | Facility fees on the term invoice (ADR 0019) |
| Transport report | P | List per route; no printable report |

### N. Hostel — built

Hostels, rooms, allocation, requests and approval, hostel fees on the term invoice (ADR 0019). Missing: printable
hostel report.

### O. Certificates and ID cards — all missing

Student and staff ID cards, academic certificates, transfer certificates, templates, PDF.

### P. Communication

| Feature | Status | Where / what is missing |
|---|---|---|
| Announcements, noticeboard | H | `announcements` |
| SMS, parent and student notifications, history | H | `sms_messages`, `notifications`, `message_templates` |
| Email | M | Only the platform console has email addresses; no email channel |

### Q. Parent portal

| Feature | Status | Where / what is missing |
|---|---|---|
| Children, attendance, results, report cards, balances, payment history, announcements | H | `/portal/*` |
| Homework | M | Depends on K |

### R. Student portal

| Feature | Status | Where / what is missing |
|---|---|---|
| Profile, attendance, results, report card, timetable, balance, payments, announcements | H | `/portal/*`, StudentHome, StudentResults |
| Study materials, homework | M | Depends on K |
| Admit card, ID card | M | Depends on H and O |

### Roles (brief §3)

| Brief role | SSMS role | Change |
|---|---|---|
| Super Administrator | Platform admin (console) | Add a console dashboard with per-school figures |
| School Administrator | `school_admin` | none |
| Teacher | `teacher` (+ `department_head`) | Teacher dashboard |
| Accountant | `bursar` | Show the name "Accountant / Mhasibu"; the code stays `bursar` |
| Receptionist | — | **New role** `receptionist`: inquiries, admissions desk, ID-card printing, announcements |
| Librarian | `librarian` | Librarian dashboard |
| Student, Parent | `student`, `parent` | none |

Summary: about **70 %** of the brief is already built and tested. The missing parts are homework and study
materials, certificates and ID cards, staff attendance and leave, income and expenses, admit cards and a printable
exam timetable, subject attendance and ranking, email, library categories, cards and fines, inquiries, the receptionist
role, per-role and platform dashboards, and the session selector.

## 19.3 Where the brief and SSMS disagree

Decisions taken in this phase. Each one keeps working, tested code and records why.

| # | Brief says | SSMS has | Decision |
|---|---|---|---|
| D1 | Indigo theme: `#4F46E5`, sidebar `#1E1B4B`, background `#F8FAFC` | Forest green and ochre (2026-10-31 redesign) | **Follow the brief.** Colours are tokens in `web/tailwind.config.js`, so the switch is one file plus a contrast check. Done in the UI phase. |
| D2 | Axios | `api.ts` fetch wrapper with token refresh, offline queue and idempotency keys (ADR 0008) | Use Axios as the transport **inside** `api.ts`, keeping its interface. The offline queue and refresh logic stay. |
| D3 | Recharts | Hand-built CSS charts (no library) | Add Recharts **only in lazy-loaded chunks** (dashboards, reports), so the first load stays under the 200 KB budget (NFR). |
| D4 | React Hook Form | Controlled inputs with server-side validation messages | Use React Hook Form for new forms and when a form is rewritten. Server validation stays the authority. |
| D5 | "Repositories" layer | Routes → services → SQLAlchemy models; RLS in the database | Keep it. A separate repository layer would duplicate SQLAlchemy without adding safety. Shared query helpers stay in `services/crud.py`. |
| D6 | Card payment gateways (by implication from the reference) | GePG and mobile money (ADR 0016) | Out of scope. Tanzanian government schools must use GePG. **VERIFY** whether the private schools targeted need card payments. |
| D7 | Email notifications | SMS only | Add an email channel through the provider-adapter pattern (ADR 0009). Email is used only when an address exists; SMS stays the main channel. |
| D8 | Super Administrator in the same app as schools | Separate console with TOTP, `ssms_platform` database role | Keep the separation, which is a security control. Add a console dashboard. |
| D9 | GPA | Divisions (O-Level) and grade points | Compute GPA from grade points per grading scheme. **VERIFY** the NECTA formula for A-Level before relying on it. |
| D10 | Reference extras not in the brief: live classes (Zoom), tickets, stationery, gate pass, chat, payroll | — | Not included. Each would be a separate decision later. |

## 19.4 New requirements

Continuing the numbering of [02-requirements.md](02-requirements.md) (FR-01 to FR-71). Priority: M must, S should, C could.

### Session, dashboards, roles

| ID | Requirement | P | Acceptance criteria |
|---|---|---|---|
| FR-72 | A session selector in the top bar; lists and totals follow the selected year. | M | Choosing 2025 shows 2025 enrolments and invoices; the choice is kept per user; the server always checks the year belongs to the school. |
| FR-73 | Dashboards for teacher, librarian, receptionist and accountant, each showing only that role's work. | M | A teacher sees their classes, today's registers not yet taken and homework to mark; a librarian sees loans due and overdue. |
| FR-74 | The staff dashboard adds upcoming exams, recent activity (audit feed, school staff only), mean score by class and subject, and the latest announcements. | S | Tiles match database counts in tests. |
| FR-75 | A platform console dashboard: number of schools by status, students and staff per school, and SMS credit per school. | M | Figures come from `ssms_platform` views; no student names are shown. |
| FR-76 | New role `receptionist` with permissions for inquiries, the admissions desk, announcements and ID-card printing. | M | A receptionist gets 403 on marks, fees and health records. |

### People and attendance

| ID | Requirement | P | Acceptance criteria |
|---|---|---|---|
| FR-77 | Admission inquiries: record name, phone, class wanted and source; set a follow-up date and notes; convert to an enrolment application. | M | Conversion copies the data and links both records; inquiries are per school. |
| FR-78 | Upload a student or staff photograph (JPEG/PNG, ≤ 300 KB after resizing). | M | Wrong type or size → 422. The file is stored outside the web root and served only to permitted users. |
| FR-79 | CSV export of students, staff, invoices and attendance, using the current filters. | M | Export is audited; health and encrypted fields are never exported. |
| FR-80 | Staff attendance by device tap or manual entry, with present, absent, late and on-leave statuses. | M | One record per staff member per day (DB unique). |
| FR-81 | Leave requests for staff and students: type, dates, reason; approve or reject with a comment. | M | Overlapping approved leave → 409. Approved leave marks attendance as "on leave". |
| FR-82 | Subject (period) attendance taken from the timetable slot. | S | One record per student per slot per date (DB unique). |
| FR-83 | Monthly attendance sheet: days × students with P/A/L/E and totals, printable. | M | Totals equal the daily register counts. |

### Exams

| ID | Requirement | P | Acceptance criteria |
|---|---|---|---|
| FR-84 | Printable exam timetable per session, class and room, built from `exams`; the school centre number on exam documents. | M | The timetable lists every paper of the session once; centre number stored in school settings. |
| FR-85 | Admit cards with an exam number series (optional prefix), bulk PDF. | M | Numbers are unique per exam session; the PDF has one card per student. |
| FR-86 | Subject ranking per class and stream, plus GPA where the grading scheme defines points. | S | Ties share a position. GPA rule marked VERIFY until confirmed. |

### Finance

| ID | Requirement | P | Acceptance criteria |
|---|---|---|---|
| FR-87 | Income and expense categories; record other income and expenses with a date, amount, method and attachment. | M | Each entry posts a balanced journal (ADR 0006); reversal only by maker-checker. |
| FR-88 | Income statement and cash book for a period. | M | Totals equal the ledger. |
| FR-89 | Fines: late-payment fines by rule and library fines, added as invoice lines. | S | A fine is waived only with a reason, which is audited. |

### Teaching resources

| ID | Requirement | P | Acceptance criteria |
|---|---|---|---|
| FR-90 | Teachers publish study materials (file or link) to classes or streams and subjects. | M | Students see only materials for their own enrolment; files ≤ 20 MB, allowed types only. |
| FR-91 | Homework: title, instructions, attachment, due date, target streams; optional SMS to parents. | M | Students and their parents see it; teachers see who has submitted. |
| FR-92 | Students submit homework (text and/or file) until the deadline; late submissions are marked late. | M | One live submission per student per homework (DB unique); resubmitting replaces it before the deadline. |
| FR-93 | Teachers give a score and feedback; the student and parent see it. | M | Feedback only from a teacher assigned to that stream and subject. |

### Certificates, cards, library

| ID | Requirement | P | Acceptance criteria |
|---|---|---|---|
| FR-94 | Student and staff ID cards as PDF (photo, name, number, class, validity, QR code holding the card number only). | M | Bulk print per stream; the QR code never holds personal data. |
| FR-95 | Certificate templates (leaving, transfer, character, achievement) with placeholders; issue certificates with a serial number; PDF. | M | Serial unique per school; issued certificates cannot be edited, only revoked with a reason. |
| FR-96 | Library categories and publishers; library cards with a number series. | S | Card number unique per school. |
| FR-97 | Library fines for late returns, at a rate per day set by the school. | C | The fine appears on the next invoice (FR-89). |

### Communication

| ID | Requirement | P | Acceptance criteria |
|---|---|---|---|
| FR-98 | Email channel for notifications and announcements, through a provider adapter; delivery status kept. | S | No email address → SMS only; failures are retried and recorded. |
| FR-99 | School calendar of events and holidays, shown on dashboards and portals. | S | Holidays block attendance registers (as `public_holidays` does today). |

### Non-functional additions

| ID | Requirement |
|---|---|
| NFR-16 | Uploaded files: type checked by content, not by extension; size limits per kind; stored outside the web root under a random name; served only after a permission check; antivirus scan in production (**VERIFY** the scanner choice). |
| NFR-17 | Every new table holding school data has `school_id`, RLS forced, and isolation tests run as `ssms_app` (same rule as ADR 0001). |
| NFR-18 | The first page load stays ≤ 200 KB gzipped; chart and PDF code load only when needed. |

## 19.5 Next

Phase 2 ([20-extension-architecture.md](20-extension-architecture.md)) designs the tables, permissions, API and
screens for FR-72 to FR-99.
