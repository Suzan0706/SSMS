# 3. Context Diagram and Data Flow Diagrams

Notation (Yourdon/DeMarco):

- external entities are rectangles;
- processes are rounded boxes, numbered `n.0` at Level 1 and `n.m` at Level 2;
- data stores are double-edged boxes `Dn`;
- arrows carry data only.

Long Level 0 labels are drawn as text nodes so they do not overlap the boxes.

## 3.1 Data stores

| Store | Tables |
|---|---|
| D1 Users & Access | `users`, `user_roles`, `roles`, `permissions`, `refresh_tokens`, `otp_codes` |
| D2 Students & Guardians | `students`, `guardians`, `student_guardians`, `student_status_history`, `consent_records`, `data_subject_requests` |
| D3 Enrolments | `enrolment_requirements`, `enrolment_applications`, `enrolment_documents`, `enrolments` |
| D4 Academic Configuration | `education_levels`, `academic_years`, `terms`, `public_holidays`, `classes`, `streams`, `stream_class_teachers`, `subjects`, `class_subjects`, `combinations`, `combination_subjects`, `grading_schemes`, `grade_bands`, `division_rules`, `assessment_components` |
| D5 Attendance | `attendance_sessions`, `attendance_records`, `absence_alerts`, `devices`, `rfid_cards` |
| D6 Marks & Results | `mark_entries`, `result_publications`, `published_results`, `student_term_summaries`, `result_amendments`, `report_card_comments` |
| D7 Finance | `fee_items`, `fee_structures`, `fee_structure_lines`, `discount_rules`, `student_discounts`, `invoices`, `invoice_lines`, `invoice_installments`, `gepg_bills`, `payments`, `payment_allocations`, `payment_reversals`, `receipts`, `ledger_accounts`, `journals`, `ledger_entries`, `bank_deposit_confirmations`, `reconciliation_runs`, `reconciliation_items` |
| D8 Staff | `staff`, `staff_qualifications`, `departments`, `designations`, `teaching_assignments` |
| D9 Timetable & Exams | `rooms`, `timetable_slots`, `exam_sessions`, `exams` |
| D10 Facilities | `hostels`, `hostel_rooms`, `accommodation_requests`, `hostel_allocations`, `buses`, `routes`, `route_stops`, `transport_assignments`, `venues`, `venue_events` |
| D11 Messages | `message_templates`, `sms_messages`, `sms_credit_transactions`, `announcements`, `notifications` |
| D12 Audit Log | `audit_logs` (written by triggers from every process) |
| D13 Student Life | `discipline_records`, `extracurricular_activities`, `student_activities`, `library_books`, `library_loans`, `health_records` |
| D14 Jobs | `background_jobs`, `idempotency_keys`, `document_sequences` |

## 3.2 Level 0 — Context diagram

```mermaid
flowchart LR
    classDef ext fill:#e8f0fe,stroke:#1a73e8,color:#0b3d91
    classDef proc fill:#e6f4ea,stroke:#188038,color:#0d652d
    classDef flow fill:none,stroke:none,color:#333,font-size:11px

    Admin["School Admin<br/>(head, academic master, registrar)"]:::ext
    Teacher["Teacher"]:::ext
    Student["Student"]:::ext
    Parent["Parent / Guardian"]:::ext
    Bursar["Bursar"]:::ext
    Bank["Bank"]:::ext
    MM["Mobile Money<br/>(M-Pesa, Mixx by Yas,<br/>Airtel Money, HaloPesa)"]:::ext
    GePG["GePG"]:::ext
    SMSG["SMS Gateway"]:::ext
    Gate["Gate Device<br/>(RFID / QR)"]:::ext
    P0(("0.0<br/>SSMS")):::proc

    a1["User & role administration<br/>Student records & status changes<br/>Enrolment decisions<br/>Grading & exam setup<br/>Publication & amendment decisions<br/>Staff & department records<br/>Class, subject, room & timetable setup<br/>Facility allocations & bookings<br/>Announcements · Report requests · Credentials"]:::flow
    a2["Access token · Enrolment queue<br/>Incomplete-grades list · Clash alerts<br/>Dashboards, reports & exports · Audit trail"]:::flow
    t1["Attendance register · Marks<br/>Amendment requests · Document validations<br/>Discipline incidents · Credentials"]:::flow
    t2["Access token · Class lists<br/>Mark sheets & sync conflicts<br/>Documents to validate · Teaching timetable"]:::flow
    s1["Application & documents<br/>Accommodation request · Credentials"]:::flow
    s2["Access token · Application status · Timetable<br/>Results & report card · Fee balance"]:::flow
    p1["Phone & OTP code · Enrolment inquiry"]:::flow
    p2["Access token · Children's attendance<br/>Results & report cards<br/>Invoices, control numbers & receipts · Announcements"]:::flow
    b1["Fee structures & discounts<br/>Cash & bank payments · Reversal requests<br/>Provider statements · Credentials"]:::flow
    b2["Access token · Invoices & transaction history<br/>Reconciliation exceptions · Defaulters & aging"]:::flow
    k1["Deposit confirmations · Credentials"]:::flow
    k2["Access token · Deposits awaiting confirmation"]:::flow
    m1["Payment callbacks"]:::flow
    m2["Payment push requests · Acknowledgements"]:::flow
    g1["Control numbers · Payment notifications"]:::flow
    g2["Bill requests · Acknowledgements"]:::flow
    x1["Delivery reports"]:::flow
    x2["SMS messages"]:::flow
    d1["Card taps"]:::flow
    d2["Tap results"]:::flow

    Admin --- a1 --> P0
    P0 --- a2 --> Admin
    Teacher --- t1 --> P0
    P0 --- t2 --> Teacher
    Student --- s1 --> P0
    P0 --- s2 --> Student
    Parent --- p1 --> P0
    P0 --- p2 --> Parent
    Bursar --- b1 --> P0
    P0 --- b2 --> Bursar
    Bank --- k1 --> P0
    P0 --- k2 --> Bank
    MM --- m1 --> P0
    P0 --- m2 --> MM
    GePG --- g1 --> P0
    P0 --- g2 --> GePG
    SMSG --- x1 --> P0
    P0 --- x2 --> SMSG
    Gate --- d1 --> P0
    P0 --- d2 --> Gate
```

SMS to parents leaves the system through the SMS Gateway. The gateway, not SSMS, delivers it to the phone, so it is drawn as *SMS messages → SMS Gateway*.

## 3.3 Level 1

Level 1 is one diagram with ten processes. It is drawn as **four views** so that it stays readable. Each flow appears in exactly one view, and the balancing table in 3.4 covers all four. Entities and stores may repeat between views.

### View A — 1.0 Manage Users, 2.0 Manage Students & Enrolment, 6.0 Staff & Departments

```mermaid
flowchart LR
    classDef ext fill:#e8f0fe,stroke:#1a73e8,color:#0b3d91
    classDef proc fill:#e6f4ea,stroke:#188038,color:#0d652d
    classDef store fill:#fef7e0,stroke:#b06000,color:#5c3900

    Users["All users<br/>(Admin, Teacher, Student,<br/>Bursar, Bank)"]:::ext
    Parent["Parent"]:::ext
    Admin["School Admin"]:::ext
    Teacher["Teacher"]:::ext
    Student["Student"]:::ext

    P1("1.0 Manage<br/>Users"):::proc
    P2("2.0 Manage Students<br/>& Enrolment"):::proc
    P6("6.0 Staff &<br/>Departments"):::proc
    P5("5.0 Fees &<br/>Payments"):::proc
    P9("9.0 Communication"):::proc

    D1[["D1 Users & Access"]]:::store
    D2[["D2 Students & Guardians"]]:::store
    D3[["D3 Enrolments"]]:::store
    D4[["D4 Academic Config"]]:::store
    D8[["D8 Staff"]]:::store
    D13[["D13 Student Life"]]:::store

    Users -->|Credentials| P1
    Parent -->|"Phone & OTP code"| P1
    P1 -->|Access token| Users
    P1 -->|Access token| Parent
    Admin -->|"User & role administration"| P1
    P1 <-->|"Accounts, roles, tokens, OTPs"| D1
    P1 -->|OTP SMS request| P9

    Parent -->|Enrolment inquiry| P2
    Student -->|"Application & documents"| P2
    Teacher -->|Document validations| P2
    Teacher -->|Discipline incidents| P2
    Admin -->|"Student records & status changes"| P2
    Admin -->|Enrolment decisions| P2
    P2 -->|Documents to validate| Teacher
    P2 -->|Application status| Student
    P2 -->|Enrolment queue| Admin
    D4 -->|"Classes, places, requirements"| P2
    P2 <-->|"Students, guardians, consent"| D2
    P2 <-->|"Applications, documents, enrolments"| D3
    P2 <-->|"Discipline, clubs, health"| D13
    P2 -->|New login| D1
    P2 -->|Enrolled student| P5
    P2 -->|"Status & admission SMS request"| P9

    Admin -->|"Staff & department records"| P6
    P6 <-->|"Staff, qualifications, assignments"| D8
    P6 -->|Staff login| D1
```

### View B — 3.0 Attendance, 4.0 Exams & Results, 7.0 Timetable

```mermaid
flowchart LR
    classDef ext fill:#e8f0fe,stroke:#1a73e8,color:#0b3d91
    classDef proc fill:#e6f4ea,stroke:#188038,color:#0d652d
    classDef store fill:#fef7e0,stroke:#b06000,color:#5c3900

    Admin["School Admin"]:::ext
    Teacher["Teacher"]:::ext
    Student["Student"]:::ext
    Parent["Parent"]:::ext
    Gate["Gate Device"]:::ext

    P3("3.0 Attendance"):::proc
    P4("4.0 Exams &<br/>Results"):::proc
    P7("7.0 Timetable"):::proc
    P9("9.0 Communication"):::proc

    D3[["D3 Enrolments"]]:::store
    D4[["D4 Academic Config"]]:::store
    D5[["D5 Attendance"]]:::store
    D6[["D6 Marks & Results"]]:::store
    D8[["D8 Staff"]]:::store
    D9[["D9 Timetable & Exams"]]:::store

    Teacher -->|Attendance register| P3
    Gate -->|Card taps| P3
    P3 -->|Tap results| Gate
    P3 -->|Class lists| Teacher
    P3 -->|"Children's attendance"| Parent
    D3 -->|Enrolled students| P3
    P3 <-->|"Sessions, records, devices"| D5
    P3 -->|Absence alerts| P9

    Admin -->|"Grading & exam setup"| P4
    Admin -->|"Publication & amendment decisions"| P4
    Teacher -->|Marks| P4
    Teacher -->|Amendment requests| P4
    P4 -->|"Mark sheets & sync conflicts"| Teacher
    P4 -->|Incomplete-grades list| Admin
    P4 -->|"Results & report card"| Student
    P4 -->|"Results & report cards"| Parent
    D3 -->|Enrolments| P4
    P4 <-->|"Schemes, bands, components"| D4
    P4 <-->|"Exam sessions, papers"| D9
    P4 <-->|"Drafts, publications, amendments"| D6
    P4 -->|Results-ready SMS| P9

    Admin -->|"Class, subject, room & timetable setup"| P7
    P7 -->|Clash alerts| Admin
    P7 -->|Teaching timetable| Teacher
    P7 -->|Timetable| Student
    D8 -->|"Assignments, loads"| P7
    P7 <-->|"Classes, streams, subjects"| D4
    P7 <-->|"Rooms, slots"| D9
```

### View C — 5.0 Fees & Payments

```mermaid
flowchart LR
    classDef ext fill:#e8f0fe,stroke:#1a73e8,color:#0b3d91
    classDef proc fill:#e6f4ea,stroke:#188038,color:#0d652d
    classDef store fill:#fef7e0,stroke:#b06000,color:#5c3900

    Bursar["Bursar"]:::ext
    Bank["Bank"]:::ext
    MM["Mobile Money"]:::ext
    GePG["GePG"]:::ext
    Parent["Parent"]:::ext
    Student["Student"]:::ext
    P2("2.0 Students &<br/>Enrolment"):::proc
    P5("5.0 Fees &<br/>Payments"):::proc
    P9("9.0 Communication"):::proc
    D2[["D2 Students & Guardians"]]:::store
    D7[["D7 Finance"]]:::store

    P2 -->|Enrolled student| P5
    Bursar -->|"Fee structures & discounts"| P5
    Bursar -->|"Cash & bank payments"| P5
    Bursar -->|Reversal requests| P5
    Bursar -->|Provider statements| P5
    P5 -->|"Invoices & transaction history"| Bursar
    P5 -->|Reconciliation exceptions| Bursar
    Bank -->|Deposit confirmations| P5
    P5 -->|Deposits awaiting confirmation| Bank
    MM -->|Payment callbacks| P5
    P5 -->|"Payment push requests · Acknowledgements"| MM
    GePG -->|"Control numbers · Payment notifications"| P5
    P5 -->|"Bill requests · Acknowledgements"| GePG
    P5 -->|"Invoices, control numbers & receipts"| Parent
    P5 -->|Fee balance| Student
    D2 -->|"Students, siblings, guardians"| P5
    P5 <-->|"Invoices, payments, ledger"| D7
    P5 -->|"Receipt & reminder SMS"| P9
```

### View D — 8.0 Facilities, 9.0 Communication, 10.0 Reports

```mermaid
flowchart LR
    classDef ext fill:#e8f0fe,stroke:#1a73e8,color:#0b3d91
    classDef proc fill:#e6f4ea,stroke:#188038,color:#0d652d
    classDef store fill:#fef7e0,stroke:#b06000,color:#5c3900

    Admin["School Admin"]:::ext
    Student["Student"]:::ext
    Parent["Parent"]:::ext
    Bursar["Bursar"]:::ext
    SMSG["SMS Gateway"]:::ext
    Others("1.0, 2.0, 3.0,<br/>4.0, 5.0"):::proc

    P8("8.0 Facilities"):::proc
    P9("9.0 Communication"):::proc
    P10("10.0 Reports"):::proc

    D10[["D10 Facilities"]]:::store
    D11[["D11 Messages"]]:::store
    D12[["D12 Audit Log"]]:::store
    DALL[["D1–D14 (read only)"]]:::store

    Student -->|Accommodation request| P8
    Admin -->|"Facility allocations & bookings"| P8
    P8 <-->|"Hostels, buses, venues"| D10

    Others -->|SMS requests| P9
    Admin -->|Announcements| P9
    P9 -->|Announcements| Parent
    P9 -->|SMS messages| SMSG
    SMSG -->|Delivery reports| P9
    P9 <-->|"Templates, SMS log, credit"| D11

    Admin -->|Report requests| P10
    P10 -->|"Dashboards, reports & exports"| Admin
    P10 -->|Audit trail| Admin
    P10 -->|"Defaulters & aging"| Bursar
    DALL -->|Report data| P10
    D12 -->|Audit entries| P10
```

Every process writes its changes to **D12 Audit Log** through the database trigger `fn_audit_row`. Those arrows are not drawn.

## 3.4 Balancing table — Level 0 ↔ Level 1

| Level 0 flow | Direction | Level 1 |
|---|---|---|
| Credentials | Admin, Teacher, Student, Bursar, Bank → SSMS | 1.0 |
| Phone & OTP code | Parent → SSMS | 1.0 |
| Access token | SSMS → every user entity | 1.0 |
| User & role administration | Admin → SSMS | 1.0 |
| Student records & status changes · Enrolment decisions | Admin → SSMS | 2.0 |
| Enrolment queue | SSMS → Admin | 2.0 |
| Grading & exam setup · Publication & amendment decisions | Admin → SSMS | 4.0 |
| Incomplete-grades list | SSMS → Admin | 4.0 |
| Staff & department records | Admin → SSMS | 6.0 |
| Class, subject, room & timetable setup | Admin → SSMS | 7.0 |
| Clash alerts | SSMS → Admin | 7.0 |
| Facility allocations & bookings | Admin → SSMS | 8.0 |
| Announcements | Admin → SSMS | 9.0 |
| Report requests | Admin → SSMS | 10.0 |
| Dashboards, reports & exports · Audit trail | SSMS → Admin | 10.0 |
| Attendance register | Teacher → SSMS | 3.0 |
| Marks · Amendment requests | Teacher → SSMS | 4.0 |
| Document validations · Discipline incidents | Teacher → SSMS | 2.0 |
| Class lists | SSMS → Teacher | 3.0 |
| Mark sheets & sync conflicts | SSMS → Teacher | 4.0 |
| Documents to validate | SSMS → Teacher | 2.0 |
| Teaching timetable | SSMS → Teacher | 7.0 |
| Application & documents | Student → SSMS | 2.0 |
| Accommodation request | Student → SSMS | 8.0 |
| Application status | SSMS → Student | 2.0 |
| Timetable | SSMS → Student | 7.0 |
| Results & report card | SSMS → Student | 4.0 |
| Fee balance | SSMS → Student | 5.0 |
| Enrolment inquiry | Parent → SSMS | 2.0 |
| Children's attendance | SSMS → Parent | 3.0 |
| Results & report cards | SSMS → Parent | 4.0 |
| Invoices, control numbers & receipts | SSMS → Parent | 5.0 |
| Announcements | SSMS → Parent | 9.0 |
| Fee structures & discounts · Cash & bank payments · Reversal requests · Provider statements | Bursar → SSMS | 5.0 |
| Invoices & transaction history · Reconciliation exceptions | SSMS → Bursar | 5.0 |
| Defaulters & aging | SSMS → Bursar | 10.0 |
| Deposit confirmations | Bank → SSMS | 5.0 |
| Deposits awaiting confirmation | SSMS → Bank | 5.0 |
| Payment callbacks | Mobile Money → SSMS | 5.0 |
| Payment push requests · Acknowledgements | SSMS → Mobile Money | 5.0 |
| Control numbers · Payment notifications | GePG → SSMS | 5.0 |
| Bill requests · Acknowledgements | SSMS → GePG | 5.0 |
| SMS messages | SSMS → SMS Gateway | 9.0 |
| Delivery reports | SMS Gateway → SSMS | 9.0 |
| Card taps | Gate Device → SSMS | 3.0 |
| Tap results | SSMS → Gate Device | 3.0 |

Internal flows that do not cross the boundary, so they do not appear at Level 0:

- Enrolled student (2.0 → 5.0);
- SMS requests from 1.0, 2.0, 3.0, 4.0 and 5.0 to 9.0;
- all data-store flows.

## 3.5 Level 2 — 2.0 Manage Students & Enrolment

```mermaid
flowchart LR
    classDef ext fill:#e8f0fe,stroke:#1a73e8,color:#0b3d91
    classDef proc fill:#e6f4ea,stroke:#188038,color:#0d652d
    classDef store fill:#fef7e0,stroke:#b06000,color:#5c3900

    Admin["School Admin"]:::ext
    Teacher["Teacher"]:::ext
    Student["Student"]:::ext
    Parent["Parent"]:::ext
    P5("5.0 Fees"):::proc
    P9("9.0 Communication"):::proc

    P21("2.1 Show classes<br/>& requirements"):::proc
    P22("2.2 Register<br/>application"):::proc
    P23("2.3 Receive<br/>documents"):::proc
    P24("2.4 Validate<br/>documents"):::proc
    P25("2.5 Decide<br/>application"):::proc
    P26("2.6 Maintain student<br/>& status"):::proc
    P27("2.7 Record discipline<br/>& student life"):::proc

    D1[["D1 Users & Access"]]:::store
    D2[["D2 Students & Guardians"]]:::store
    D3[["D3 Enrolments"]]:::store
    D4[["D4 Academic Config"]]:::store
    D13[["D13 Student Life"]]:::store

    Parent -->|Enrolment inquiry| P21
    D4 -->|"Classes, streams, capacity"| P21
    D3 -->|Requirements| P21
    P21 -->|Chosen class| P22
    Student -->|"Application & documents"| P22
    P22 -->|"Applicant, guardians, consent"| D2
    P22 -->|"Application INQUIRED → REQUIREMENTS_PENDING"| D3
    P22 -->|Files| P23
    P23 -->|"Document metadata, SHA-256"| D3
    P23 -->|Documents to validate| Teacher
    Teacher -->|Document validations| P24
    P24 <-->|"Validation status, UNDER_REVIEW / back to pending"| D3
    P24 -->|Application status| Student
    D3 -->|Applications ready| P25
    P25 -->|Enrolment queue| Admin
    Admin -->|Enrolment decisions| P25
    P25 -->|"APPROVED + enrolment"| D3
    P25 -->|"Status ACTIVE, admission no."| D2
    P25 -->|Student login| D1
    P25 -->|Enrolled student| P5
    P25 -->|"Status & admission SMS request"| P9
    Admin -->|"Student records & status changes"| P26
    P26 <-->|"Profile, status history"| D2
    Teacher -->|Discipline incidents| P27
    P27 <-->|"Discipline, clubs, health"| D13
```

Balance against 2.0:

- **Inputs:** Enrolment inquiry, Application & documents, Document validations, Discipline incidents, Student records & status changes, Enrolment decisions.
- **Outputs:** Documents to validate, Application status, Enrolment queue, Enrolled student (to 5.0), SMS request (to 9.0), New login (D1).
- **Stores:** D1, D2, D3, D4, D13.

All of these match View A.

## 3.6 Level 2 — 4.0 Exams & Results

```mermaid
flowchart LR
    classDef ext fill:#e8f0fe,stroke:#1a73e8,color:#0b3d91
    classDef proc fill:#e6f4ea,stroke:#188038,color:#0d652d
    classDef store fill:#fef7e0,stroke:#b06000,color:#5c3900

    Admin["School Admin"]:::ext
    Teacher["Teacher"]:::ext
    Student["Student"]:::ext
    Parent["Parent"]:::ext
    P9("9.0 Communication"):::proc

    P41("4.1 Configure grading<br/>& components"):::proc
    P42("4.2 Set exams"):::proc
    P43("4.3 Enter & sync<br/>marks"):::proc
    P44("4.4 Validation<br/>firewall"):::proc
    P45("4.5 Publish<br/>results"):::proc
    P46("4.6 Generate<br/>report cards"):::proc
    P47("4.7 Handle<br/>amendments"):::proc

    D3[["D3 Enrolments"]]:::store
    D4[["D4 Academic Config"]]:::store
    D6[["D6 Marks & Results"]]:::store
    D9[["D9 Timetable & Exams"]]:::store

    Admin -->|"Grading & exam setup"| P41
    P41 -->|"Schemes, bands, divisions, components"| D4
    Admin -->|"Grading & exam setup"| P42
    P42 <-->|"Sessions, papers (no clash)"| D9
    Teacher -->|Marks| P43
    D3 -->|Class lists| P43
    D4 -->|"Components, max scores"| P43
    P43 <-->|"Draft marks, versions"| D6
    P43 -->|"Mark sheets & sync conflicts"| Teacher
    Admin -->|"Publication & amendment decisions"| P44
    D6 -->|Draft marks| P44
    D4 -->|"Weights, scheme"| P44
    P44 -->|Incomplete-grades list| Admin
    P44 -->|Clean class| P45
    P45 -->|"Frozen results, summaries, locked drafts"| D6
    P45 -->|Publication| P46
    P46 -->|"Results & report card"| Student
    P46 -->|"Results & report cards"| Parent
    P46 -->|Results-ready SMS| P9
    Teacher -->|Amendment requests| P47
    Admin -->|"Publication & amendment decisions"| P47
    P47 <-->|"Amendment, new frozen version"| D6
```

Balance against 4.0:

- **Inputs:** Grading & exam setup, Publication & amendment decisions, Marks, Amendment requests.
- **Outputs:** Mark sheets & sync conflicts, Incomplete-grades list, Results & report card(s), Results-ready SMS.
- **Stores:** D3, D4, D6, D9.

All of these match View B.

## 3.7 Level 2 — 5.0 Fees & Payments

```mermaid
flowchart LR
    classDef ext fill:#e8f0fe,stroke:#1a73e8,color:#0b3d91
    classDef proc fill:#e6f4ea,stroke:#188038,color:#0d652d
    classDef store fill:#fef7e0,stroke:#b06000,color:#5c3900

    Bursar["Bursar"]:::ext
    Bank["Bank"]:::ext
    MM["Mobile Money"]:::ext
    GePG["GePG"]:::ext
    Parent["Parent"]:::ext
    Student["Student"]:::ext
    P2("2.0 Enrolment"):::proc
    P9("9.0 Communication"):::proc

    P51("5.1 Configure<br/>fees"):::proc
    P52("5.2 Raise invoices<br/>& control numbers"):::proc
    P53("5.3 Receive payment<br/>callbacks"):::proc
    P54("5.4 Record manual<br/>& bank payments"):::proc
    P55("5.5 Allocate &<br/>post ledger"):::proc
    P56("5.6 Issue<br/>receipts"):::proc
    P57("5.7 Reverse<br/>payments"):::proc
    P58("5.8 Reconcile"):::proc

    D2[["D2 Students & Guardians"]]:::store
    D7[["D7 Finance"]]:::store

    Bursar -->|"Fee structures & discounts"| P51
    P51 -->|"Fee items, structures, discounts"| D7
    P2 -->|Enrolled student| P52
    D2 -->|"Students, siblings"| P52
    P52 <-->|"Invoices, installments, bills"| D7
    P52 -->|Bill requests| GePG
    GePG -->|"Control numbers · Payment notifications"| P53
    P53 -->|Acknowledgements| GePG
    MM -->|Payment callbacks| P53
    P53 -->|"Payment push requests · Acknowledgements"| MM
    P53 -->|Confirmed payment| P55
    Bursar -->|"Cash & bank payments"| P54
    Bank -->|Deposit confirmations| P54
    P54 -->|Deposits awaiting confirmation| Bank
    P54 -->|Confirmed payment| P55
    P55 <-->|"Allocations, journals, invoice totals"| D7
    P55 -->|Allocated payment| P56
    P56 -->|Receipts| D7
    P56 -->|"Invoices, control numbers & receipts"| Parent
    P56 -->|Fee balance| Student
    P56 -->|"Invoices & transaction history"| Bursar
    P56 -->|"Receipt & reminder SMS"| P9
    Bursar -->|Reversal requests| P57
    P57 <-->|"Reversal, reversing journal"| D7
    Bursar -->|Provider statements| P58
    P58 <-->|"Runs, items"| D7
    P58 -->|Reconciliation exceptions| Bursar
```

The control-number SMS to the parent is part of *Invoices, control numbers & receipts*. Balance against 5.0: every input, output and store matches View C.
