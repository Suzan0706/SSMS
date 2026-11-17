# 5. Entity Relationship Diagrams (Crow's Foot)

The schema has **99 tables**: 94 tenant tables, `schools` and 4 global platform tables. Each diagram covers one area and shows keys and the attributes that explain the relationship. Every column is listed in [07-data-dictionary.md](07-data-dictionary.md), and the DDL is [sql/schema.sql](sql/schema.sql).

**Conventions in every diagram:**

- **Common columns are omitted.** Every tenant table also has `school_id` (FK → `schools`), `created_at`, `updated_at` and `created_by` (FK → `users`). Most also have `deleted_at`.
- **Foreign keys are composite.** Every FK drawn is really `(school_id, x_id) → x (school_id, id)`, so a relationship can never cross schools.
- **Notation.** `||--o{` = one to zero-or-many; `||--|{` = one to one-or-many; `|o--o{` = optional parent.

## 5.1 Platform, people and access

```mermaid
erDiagram
    platform_admins ||--o{ schools : "onboards"
    roles ||--o{ role_permissions : "has"
    permissions ||--o{ role_permissions : "granted in"
    schools ||--|| school_settings : "configured by"
    schools ||--o{ users : "has"
    schools ||--o{ document_sequences : "numbers"
    users ||--o{ user_roles : "holds"
    roles ||--o{ user_roles : "assigned as"
    users ||--o{ refresh_tokens : "session"
    users ||--o{ otp_codes : "login code"
    users ||--o| students : "is a"
    users ||--o| guardians : "is a"
    users ||--o| staff : "is a"
    students ||--o{ student_guardians : "has"
    guardians ||--o{ student_guardians : "cares for"
    students ||--o{ student_status_history : "status changes"
    guardians ||--o{ consent_records : "gives"
    students |o--o{ consent_records : "about"
    users ||--o{ data_subject_requests : "subject of"
    departments ||--o{ staff : "employs"
    designations |o--o{ staff : "titles"
    staff |o--o| departments : "heads"
    staff ||--o{ staff_qualifications : "holds"

    schools {
        uuid id PK
        varchar code UK "mfano-sec"
        varchar registration_no UK
        varchar status
    }
    school_settings {
        uuid id PK
        uuid school_id FK, UK
        varchar sms_sender_id
        time absence_sms_cutoff
    }
    users {
        uuid id PK
        varchar username "unique per school"
        bytea phone_enc "AES-GCM"
        bytea phone_hash "HMAC blind index"
        varchar password_hash "Argon2id, NULL for OTP-only"
        date date_of_birth
        varchar status
    }
    roles {
        uuid id PK
        varchar code UK
    }
    permissions {
        uuid id PK
        varchar code UK "module.action"
    }
    role_permissions {
        uuid id PK
        uuid role_id FK
        uuid permission_id FK
    }
    user_roles {
        uuid id PK
        uuid user_id FK
        uuid role_id FK
        timestamptz revoked_at
    }
    refresh_tokens {
        uuid id PK
        char token_hash UK
        uuid family_id
    }
    otp_codes {
        uuid id PK
        char code_hash
        smallint attempts
    }
    students {
        uuid id PK
        uuid user_id FK, UK
        varchar admission_no "unique per school"
        bytea birth_cert_no_enc
        bytea nida_enc "optional"
        varchar status
    }
    guardians {
        uuid id PK
        uuid user_id FK, UK
        bytea nida_enc
    }
    student_guardians {
        uuid id PK
        uuid student_id FK
        uuid guardian_id FK
        boolean is_primary
        boolean receives_sms
    }
    student_status_history {
        uuid id PK
        uuid student_id FK
        varchar new_status
        varchar reason
    }
    consent_records {
        uuid id PK
        uuid guardian_id FK
        varchar purpose
        boolean granted
    }
    data_subject_requests {
        uuid id PK
        uuid subject_user_id FK
        varchar request_type
        timestamptz due_at
    }
    staff {
        uuid id PK
        uuid user_id FK, UK
        varchar staff_no
        numeric salary_tzs "restricted"
        smallint max_periods_per_week
    }
    departments {
        uuid id PK
        uuid head_staff_id FK
    }
    designations {
        uuid id PK
        varchar code
    }
    staff_qualifications {
        uuid id PK
        uuid staff_id FK
        varchar level
    }
    platform_admins {
        uuid id PK
        varchar email UK
    }
    document_sequences {
        uuid id PK
        varchar doc_type
        smallint year
        integer last_value
    }
```

## 5.2 Academic configuration and enrolment

```mermaid
erDiagram
    education_levels ||--o{ classes : "groups"
    education_levels ||--o{ combinations : "offers"
    classes |o--o| classes : "promotes to"
    classes ||--o{ streams : "divided into"
    rooms |o--o{ streams : "home room"
    classes ||--o{ class_subjects : "curriculum"
    subjects ||--o{ class_subjects : "taught in"
    combinations ||--o{ combination_subjects : "includes"
    subjects ||--o{ combination_subjects : "part of"
    departments |o--o{ subjects : "owns"
    academic_years ||--|{ terms : "divided into"
    academic_years ||--o{ stream_class_teachers : "year"
    streams ||--o{ stream_class_teachers : "class teacher"
    staff ||--o{ stream_class_teachers : "is"
    academic_years ||--o{ teaching_assignments : "year"
    streams ||--o{ teaching_assignments : "taught"
    subjects ||--o{ teaching_assignments : "subject"
    staff ||--o{ teaching_assignments : "teacher"
    education_levels ||--o{ grading_schemes : "graded by"
    academic_years ||--o{ grading_schemes : "valid in"
    grading_schemes ||--|{ grade_bands : "bands"
    grading_schemes ||--o{ division_rules : "divisions"
    terms ||--o{ assessment_components : "assessed by"
    education_levels ||--o{ assessment_components : "for level"
    subjects |o--o{ assessment_components : "subject-specific"
    education_levels |o--o{ enrolment_requirements : "requires"
    students ||--o{ enrolment_applications : "applies"
    classes ||--o{ enrolment_applications : "for class"
    academic_years ||--o{ enrolment_applications : "for year"
    enrolment_applications ||--o{ enrolment_documents : "uploads"
    enrolment_requirements ||--o{ enrolment_documents : "satisfies"
    students ||--o{ enrolments : "enrolled"
    streams ||--o{ enrolments : "holds"
    academic_years ||--o{ enrolments : "year"
    combinations |o--o{ enrolments : "A-Level"
    enrolment_applications |o--o| enrolments : "results in"

    education_levels {
        uuid id PK
        varchar code "PRIMARY O_LEVEL A_LEVEL"
    }
    classes {
        uuid id PK
        varchar code "F2 STD7"
        uuid next_class_id FK
    }
    streams {
        uuid id PK
        uuid class_id FK
        varchar name "A B PCM"
        smallint capacity
    }
    subjects {
        uuid id PK
        varchar code
        varchar necta_code
        varchar room_type
    }
    combinations {
        uuid id PK
        varchar code "PCM"
    }
    class_subjects {
        uuid id PK
        uuid class_id FK
        uuid subject_id FK
        boolean is_compulsory
    }
    combination_subjects {
        uuid id PK
        uuid combination_id FK
        uuid subject_id FK
    }
    rooms {
        uuid id PK
        varchar room_type
        smallint capacity
    }
    academic_years {
        uuid id PK
        varchar name "2026"
        boolean is_current
    }
    terms {
        uuid id PK
        uuid academic_year_id FK
        smallint term_no
    }
    stream_class_teachers {
        uuid id PK
        uuid stream_id FK
        uuid academic_year_id FK
        uuid staff_id FK
    }
    teaching_assignments {
        uuid id PK
        uuid stream_id FK
        uuid subject_id FK
        uuid staff_id FK
    }
    grading_schemes {
        uuid id PK
        smallint version
        smallint best_n_subjects
    }
    grade_bands {
        uuid id PK
        varchar letter
        smallint min_score
        smallint max_score
        smallint points
    }
    division_rules {
        uuid id PK
        varchar division
        smallint min_points
        smallint max_points
    }
    assessment_components {
        uuid id PK
        varchar code "CA MIDTERM TERMINAL"
        numeric max_score
        numeric weight "totals 100"
    }
    enrolment_requirements {
        uuid id PK
        varchar name_sw
        boolean is_required
    }
    enrolment_applications {
        uuid id PK
        varchar application_no
        varchar status
    }
    enrolment_documents {
        uuid id PK
        char sha256
        varchar validation_status
    }
    enrolments {
        uuid id PK
        uuid student_id FK
        uuid stream_id FK
        uuid academic_year_id FK "one per student per year"
        varchar status
    }
```

## 5.3 Timetable, exams, marks and results

```mermaid
erDiagram
    terms ||--o{ timetable_slots : "term"
    streams ||--o{ timetable_slots : "class"
    subjects ||--o{ timetable_slots : "subject"
    staff ||--o{ timetable_slots : "teacher"
    rooms ||--o{ timetable_slots : "room"
    terms ||--o{ exam_sessions : "term"
    exam_sessions ||--|{ exams : "papers"
    classes ||--o{ exams : "sits"
    subjects ||--o{ exams : "paper"
    rooms |o--o{ exams : "venue"
    enrolments ||--o{ mark_entries : "marks"
    subjects ||--o{ mark_entries : "subject"
    assessment_components ||--o{ mark_entries : "component"
    terms ||--o{ result_publications : "term"
    classes ||--o{ result_publications : "class"
    grading_schemes ||--o{ result_publications : "scheme used"
    result_publications ||--|{ published_results : "freezes"
    enrolments ||--o{ published_results : "student"
    published_results |o--o| published_results : "supersedes"
    published_results ||--o{ result_amendments : "amended by"
    result_amendments |o--o| published_results : "creates version"
    result_publications ||--|{ student_term_summaries : "summaries"
    student_term_summaries |o--o| student_term_summaries : "supersedes"
    result_publications ||--o{ report_card_comments : "comments"

    timetable_slots {
        uuid id PK
        smallint day_of_week
        time time_start
        time time_end
        timerange slot "EXCLUDE teacher, room, stream"
    }
    exam_sessions {
        uuid id PK
        varchar kind
    }
    exams {
        uuid id PK
        date exam_date
        timerange slot "EXCLUDE class, room"
    }
    mark_entries {
        uuid id PK
        numeric score "<= component max (trigger)"
        integer version "optimistic sync"
        timestamptz locked_at
    }
    result_publications {
        uuid id PK
        smallint scheme_version
        uuid published_by FK
    }
    published_results {
        uuid id PK
        numeric final_score
        varchar letter_grade
        smallint points
        smallint subject_position
        uuid supersedes_id FK
        uuid amendment_id FK
    }
    student_term_summaries {
        uuid id PK
        numeric average_score
        smallint total_points
        varchar division
        smallint class_position
    }
    result_amendments {
        uuid id PK
        numeric new_score
        uuid requested_by FK
        uuid decided_by FK "<> requested_by"
        varchar status
    }
    report_card_comments {
        uuid id PK
        varchar class_teacher_comment
        varchar head_teacher_comment
    }
```

## 5.4 Attendance

```mermaid
erDiagram
    devices ||--o{ attendance_records : "captured by"
    students ||--o{ rfid_cards : "carries"
    streams |o--o{ attendance_sessions : "register for"
    timetable_slots |o--o{ attendance_sessions : "lesson"
    attendance_sessions ||--o{ attendance_records : "contains"
    students ||--o{ attendance_records : "attends"
    students ||--o{ absence_alerts : "alerted"
    sms_messages |o--o| absence_alerts : "sent as"

    devices {
        uuid id PK
        char api_key_hash UK
        varchar kind
        timestamptz last_seen_at
    }
    rfid_cards {
        uuid id PK
        char token_hash "unique per school"
        varchar status
    }
    attendance_sessions {
        uuid id PK
        date session_date
        varchar kind "REGISTER GATE LESSON"
    }
    attendance_records {
        uuid id PK
        varchar status
        varchar source "MANUAL RFID QR"
        timestamptz captured_at
        timestamptz synced_at
        uuid client_record_id UK "idempotent sync"
    }
    absence_alerts {
        uuid id PK
        date absence_date "one per student per day"
    }
    sms_messages {
        uuid id PK
        varchar idempotency_key
    }
```

## 5.5 Finance

```mermaid
erDiagram
    ledger_accounts ||--o{ fee_items : "income account"
    fee_structures ||--|{ fee_structure_lines : "lines"
    fee_items ||--o{ fee_structure_lines : "item"
    terms |o--o{ fee_structure_lines : "billed in"
    discount_rules ||--o{ student_discounts : "applied as"
    students ||--o{ student_discounts : "receives"
    students ||--o{ invoices : "billed"
    terms ||--o{ invoices : "term"
    invoices ||--|{ invoice_lines : "lines"
    fee_items ||--o{ invoice_lines : "item"
    discount_rules |o--o{ invoice_lines : "discount"
    invoices ||--o{ invoice_installments : "due in"
    invoices ||--o{ gepg_bills : "billed via"
    gepg_bills |o--o{ payments : "paid through"
    students ||--o{ payments : "pays"
    payments ||--o{ payment_allocations : "allocated"
    invoices ||--o{ payment_allocations : "settled by"
    payments ||--o| payment_reversals : "reversed by"
    payments ||--o| receipts : "receipted"
    journals ||--|{ ledger_entries : "lines (balanced)"
    ledger_accounts ||--o{ ledger_entries : "posted to"
    students |o--o{ ledger_entries : "sub-ledger"
    payments |o--o| bank_deposit_confirmations : "matched"
    reconciliation_runs ||--o{ reconciliation_items : "items"
    payments |o--o{ reconciliation_items : "matched"

    fee_structures {
        uuid id PK
        varchar status "DRAFT APPROVED ARCHIVED"
    }
    fee_structure_lines {
        uuid id PK
        numeric amount_tzs
    }
    fee_items {
        uuid id PK
        varchar code
        varchar gfs_code "VERIFY"
    }
    discount_rules {
        uuid id PK
        numeric percent
        numeric amount_tzs
    }
    student_discounts {
        uuid id PK
        uuid approved_by FK
    }
    invoices {
        uuid id PK
        varchar invoice_no
        numeric total_tzs "derived by trigger"
        numeric paid_tzs "derived by trigger"
        numeric balance_tzs "generated"
        varchar status "derived"
    }
    invoice_lines {
        uuid id PK
        varchar kind "CHARGE DISCOUNT"
        numeric amount_tzs
    }
    invoice_installments {
        uuid id PK
        smallint seq
        date due_date
    }
    gepg_bills {
        uuid id PK
        varchar bill_ref UK
        varchar control_number UK
        boolean signature_verified
    }
    payments {
        uuid id PK
        varchar channel
        varchar external_ref "unique per school and channel"
        numeric amount_tzs
        varchar status
    }
    payment_allocations {
        uuid id PK
        numeric amount_tzs
    }
    payment_reversals {
        uuid id PK
        uuid reversed_by FK
        uuid approved_by FK "<> reversed_by"
    }
    receipts {
        uuid id PK
        varchar receipt_no "gapless per school"
    }
    ledger_accounts {
        uuid id PK
        varchar code "1300 2100 4000"
        varchar kind
    }
    journals {
        uuid id PK
        varchar source_type
        uuid source_id
    }
    ledger_entries {
        uuid id PK
        numeric debit_tzs
        numeric credit_tzs
    }
    bank_deposit_confirmations {
        uuid id PK
        varchar bank_reference
        uuid confirmed_by FK
    }
    reconciliation_runs {
        uuid id PK
        date run_date
        varchar channel
        varchar status
    }
    reconciliation_items {
        uuid id PK
        varchar external_ref
        varchar status
    }
```

## 5.6 Facilities and student life

```mermaid
erDiagram
    hostels ||--|{ hostel_rooms : "rooms"
    staff |o--o{ hostels : "warden"
    students ||--o{ accommodation_requests : "requests"
    terms ||--o{ accommodation_requests : "term"
    hostels |o--o{ accommodation_requests : "preferred"
    hostel_rooms ||--o{ hostel_allocations : "beds (capacity)"
    students ||--o{ hostel_allocations : "allocated"
    accommodation_requests |o--o| hostel_allocations : "fulfilled by"
    staff |o--o{ buses : "drives"
    routes ||--|{ route_stops : "stops"
    routes ||--o{ transport_assignments : "route"
    buses ||--o{ transport_assignments : "seats (capacity)"
    route_stops ||--o{ transport_assignments : "pick-up"
    students ||--o{ transport_assignments : "rides"
    venues ||--o{ venue_events : "booked (no overlap)"
    students ||--o{ discipline_records : "incidents"
    staff |o--o{ extracurricular_activities : "patron"
    extracurricular_activities ||--o{ student_activities : "members"
    students ||--o{ student_activities : "joins"
    library_books ||--o{ library_loans : "loaned (copies)"
    users ||--o{ library_loans : "borrows"
    students ||--o{ health_records : "health (restricted)"

    hostels {
        uuid id PK
        varchar gender
    }
    hostel_rooms {
        uuid id PK
        smallint capacity
    }
    accommodation_requests {
        uuid id PK
        varchar status
    }
    hostel_allocations {
        uuid id PK
        timestamptz vacated_at
    }
    buses {
        uuid id PK
        varchar bus_no "T 123 DEF"
        smallint capacity
    }
    routes {
        uuid id PK
        numeric term_fee_tzs
    }
    route_stops {
        uuid id PK
        smallint seq
        time pickup_time
    }
    transport_assignments {
        uuid id PK
        timestamptz ended_at
    }
    venues {
        uuid id PK
        smallint total_seats
    }
    venue_events {
        uuid id PK
        date event_date
        smallint seats_occupied
    }
    discipline_records {
        uuid id PK
        varchar category
        varchar status
    }
    extracurricular_activities {
        uuid id PK
        varchar kind
    }
    student_activities {
        uuid id PK
        varchar role
    }
    library_books {
        uuid id PK
        varchar isbn
        smallint copies
    }
    library_loans {
        uuid id PK
        date due_date
        timestamptz returned_at
    }
    health_records {
        uuid id PK
        bytea notes_enc
    }
```

## 5.7 Communication and system

```mermaid
erDiagram
    classes |o--o{ announcements : "audience"
    streams |o--o{ announcements : "audience"
    users |o--o{ announcements : "audience"
    users ||--o{ notifications : "inbox"
    users |o--o{ sms_messages : "recipient"
    sms_messages |o--o{ sms_credit_transactions : "debits"
    users ||--o{ background_jobs : "requests"
    users |o--o{ audit_logs : "actor"
    platform_admins |o--o{ audit_logs : "platform actor"

    announcements {
        uuid id PK
        varchar audience
        boolean send_sms
    }
    notifications {
        uuid id PK
        timestamptz read_at
    }
    message_templates {
        uuid id PK
        varchar key
        char language "sw en"
        varchar body "{placeholders}"
    }
    sms_messages {
        uuid id PK
        bytea to_phone_enc
        varchar provider "BEEM NEXTSMS"
        varchar status
        varchar idempotency_key UK
    }
    sms_credit_transactions {
        uuid id PK
        varchar kind
        integer credits
    }
    audit_logs {
        uuid id PK
        varchar action
        varchar entity_type
        uuid entity_id
        jsonb before_data "redacted"
        jsonb after_data "redacted"
    }
    background_jobs {
        uuid id PK
        varchar kind
        varchar status
        smallint progress_pct
    }
    idempotency_keys {
        uuid id PK
        varchar scope
        varchar key
        char request_hash
    }
```
