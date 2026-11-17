# 8. Class Diagrams

UML 2.x class diagrams of the domain model that Phase 1+ implements as SQLAlchemy 2 (async) models and services.

- **Visibility:** `+` public, `-` private, `#` protected.
- **Static:** `$` marks a class method.
- **Persistence:** every persistent class also has `id: UUID`, `school_id: UUID`, `created_at`, `updated_at`, `created_by` and, where soft-deleted, `deleted_at`. These are inherited from the abstract `TenantEntity` and not repeated.
- **Diagrams:** split into three for readability.

## 8.1 People, access and tenancy

```mermaid
classDiagram
    direction TB
    class TenantEntity {
        <<abstract>>
        #UUID id
        #UUID school_id
        #datetime created_at
        #datetime updated_at
        #UUID created_by
        #datetime deleted_at
        +soft_delete(reason: str) void
    }
    class School {
        +str code
        +str name
        +str registration_no
        +SchoolStatus status
        +settings() SchoolSettings
        +suspend(reason: str) void
    }
    class User {
        <<abstract>>
        +str first_name
        +str middle_name
        +str last_name
        +Gender gender
        +date date_of_birth
        -bytes phone_enc
        -bytes phone_hash
        +str phone_last4
        +str email
        +str username
        -str password_hash
        +Language preferred_language
        +UserStatus status
        +full_name() str
        +age(on: date) int
        +roles() List~Role~
        +has_permission(code: str) bool
        +set_password(raw: str) void
        +verify_password(raw: str) bool
    }
    class Student {
        +str admission_no
        -bytes birth_cert_no_enc
        -bytes nida_enc
        +str prem_number
        +StudentStatus status
        +current_enrolment() Enrolment
        +guardians() List~Guardian~
        +change_status(new: StudentStatus, reason: str, effective: date) StatusChange
        +fee_position() FeePosition
    }
    class Guardian {
        -bytes nida_enc
        +str occupation
        +children() List~Student~
        +has_sms_consent() bool
    }
    class Staff {
        +str staff_no
        +str check_no
        +EmploymentType employment_type
        -Decimal salary_tzs
        +int max_periods_per_week
        +weekly_load(term: Term) int
    }
    class Teacher {
        +assignments(year: AcademicYear) List~TeachingAssignment~
        +can_enter_marks(stream: Stream, subject: Subject) bool
        +validate(doc: EnrolmentDocument, valid: bool, comment: str) void
    }
    class SchoolAdmin {
        +publish(term: Term, cls: SchoolClass) ResultPublication
        +approve(amendment: ResultAmendment) PublishedResult
        +decide(app: EnrolmentApplication, stream: Stream) Enrolment
    }
    class Bursar {
        +record_payment(p: PaymentIn) Payment
        +request_reversal(p: Payment, reason: str) PaymentReversal
    }
    class Role {
        +str code
        +permissions() List~Permission~
    }
    class Permission {
        +str code
        +str module
    }
    class RefreshToken {
        -str token_hash
        +UUID family_id
        +rotate() RefreshToken
        +revoke_family() void
    }
    class OtpCode {
        -str code_hash
        +int attempts
        +verify(code: str) bool
    }
    class Department {
        +str code
        +Staff head
    }
    class ConsentRecord {
        +ConsentPurpose purpose
        +bool granted
    }
    class AuditLog {
        +str action
        +str entity_type
        +UUID entity_id
        +dict before_data
        +dict after_data
    }
    note for Teacher "Teacher, SchoolAdmin and Bursar are Staff with a role,\nnot separate tables (role-based subclassing)."

    TenantEntity <|-- User
    TenantEntity <|-- Department
    User <|-- Student
    User <|-- Guardian
    User <|-- Staff
    Staff <|-- Teacher
    Staff <|-- SchoolAdmin
    Staff <|-- Bursar
    School "1" *-- "0..*" User : tenant of
    User "0..*" -- "1..*" Role : holds
    Role "0..*" -- "1..*" Permission : grants
    User "1" *-- "0..*" RefreshToken
    User "1" *-- "0..*" OtpCode
    Guardian "1..*" -- "0..*" Student : cares for
    Guardian "1" *-- "0..*" ConsentRecord
    Department "1" o-- "0..*" Staff : employs
    User "0..1" --> "0..*" AuditLog : performs
```

## 8.2 Academics: enrolment, timetable, exams, results

```mermaid
classDiagram
    direction TB
    class AcademicYear {
        +str name
        +bool is_current
        +terms() List~Term~
    }
    class Term {
        +int term_no
        +date start_date
        +date end_date
        +is_school_day(d: date) bool
    }
    class EducationLevel {
        +LevelCode code
    }
    class SchoolClass {
        +str code
        +str name_sw
        +SchoolClass next_class
    }
    class Stream {
        +str name
        +int capacity
        +places_left(year: AcademicYear) int
    }
    class Subject {
        +str code
        +str necta_code
        +RoomType room_type
    }
    class Combination {
        +str code
    }
    class Room {
        +RoomType room_type
        +int capacity
    }
    class TeachingAssignment
    class EnrolmentApplication {
        +str application_no
        +ApplicationStatus status
        +submit() void
        +refresh_status() ApplicationStatus
        +approve(stream: Stream) Enrolment
        +reject(reason: str) void
        +cancel(reason: str) void
    }
    class EnrolmentDocument {
        +str sha256
        +ValidationStatus validation_status
        +str comment
    }
    class Enrolment {
        +EnrolmentStatus status
        +date started_on
        +promote(next_stream: Stream) Enrolment
    }
    class TimetableSlot {
        +int day_of_week
        +time time_start
        +time time_end
        +overlaps(other: TimetableSlot) bool
    }
    class Scheduler {
        <<service>>
        +find_conflicts(slot: TimetableSlot) List~Conflict~
        +generate(term: Term, streams: List~Stream~) Draft
    }
    class ExamSession {
        +ExamKind kind
    }
    class Exam {
        +date exam_date
    }
    class GradingScheme {
        +int version
        +int best_n_subjects
        +grade_for(score: Decimal) GradeBand
        +division_for(points: int) str
    }
    class GradeBand {
        +str letter
        +int min_score
        +int max_score
        +int points
    }
    class AssessmentComponent {
        +ComponentCode code
        +Decimal max_score
        +Decimal weight
    }
    class MarkEntry {
        +Decimal score
        +bool is_absent
        +int version
        +datetime locked_at
        +update(score: Decimal, expected_version: int) MarkEntry
    }
    class ResultPublisher {
        <<service>>
        +firewall(term: Term, cls: SchoolClass) List~Problem~
        +publish(term: Term, cls: SchoolClass) ResultPublication
    }
    class ResultPublication {
        +int scheme_version
        +datetime published_at
    }
    class PublishedResult {
        <<frozen>>
        +Decimal final_score
        +str letter_grade
        +int points
        +int subject_position
    }
    class StudentTermSummary {
        <<frozen>>
        +Decimal average_score
        +int total_points
        +str division
        +int class_position
    }
    class ResultAmendment {
        +Decimal new_score
        +AmendmentStatus status
        +approve(by: SchoolAdmin) PublishedResult
    }

    AcademicYear "1" *-- "1..4" Term
    EducationLevel "1" o-- "1..*" SchoolClass
    SchoolClass "1" *-- "1..*" Stream
    SchoolClass "0..*" -- "1..*" Subject : curriculum
    Combination "0..*" -- "1..*" Subject : includes
    TeachingAssignment "0..*" --> "1" Stream
    TeachingAssignment "0..*" --> "1" Subject
    TeachingAssignment "0..*" --> "1" Teacher
    EnrolmentApplication "1" *-- "0..*" EnrolmentDocument
    EnrolmentApplication "0..1" --> "0..1" Enrolment : results in
    Student "1" --> "0..*" Enrolment : one per year
    Stream "1" -- "0..*" Enrolment
    TimetableSlot "0..*" --> "1" Stream
    TimetableSlot "0..*" --> "1" Subject
    TimetableSlot "0..*" --> "1" Teacher
    TimetableSlot "0..*" --> "1" Room
    Scheduler ..> TimetableSlot : creates
    ExamSession "1" *-- "1..*" Exam
    GradingScheme "1" *-- "1..*" GradeBand
    Term "1" *-- "0..*" AssessmentComponent
    Enrolment "1" *-- "0..*" MarkEntry
    MarkEntry "0..*" --> "1" AssessmentComponent
    ResultPublisher ..> MarkEntry : locks
    ResultPublisher ..> ResultPublication : creates
    ResultPublication "1" *-- "1..*" PublishedResult
    ResultPublication "1" *-- "1..*" StudentTermSummary
    ResultPublication "0..*" --> "1" GradingScheme
    PublishedResult "0..1" --> "0..1" PublishedResult : supersedes
    ResultAmendment "0..*" --> "1" PublishedResult : amends
```

## 8.3 Finance, attendance, facilities, communication

```mermaid
classDiagram
    direction TB
    class FeeStructure {
        +FeeStructureStatus status
        +approve(by: SchoolAdmin) void
        +lines_for(term: Term) List~FeeStructureLine~
    }
    class FeeStructureLine {
        +Decimal amount_tzs
    }
    class FeeItem {
        +FeeCode code
        +str gfs_code
    }
    class DiscountRule {
        +Decimal percent
        +Decimal amount_tzs
        +apply(charge: Decimal) Decimal
    }
    class Invoice {
        +str invoice_no
        +date due_date
        +Decimal total_tzs
        +Decimal paid_tzs
        +Decimal balance_tzs
        +InvoiceStatus status
        +cancel(reason: str) void
    }
    class InvoiceLine {
        +LineKind kind
        +Decimal amount_tzs
    }
    class Installment {
        +int seq
        +date due_date
        +Decimal amount_tzs
    }
    class GepgBill {
        +str bill_ref
        +str control_number
        +bool signature_verified
    }
    class Payment {
        +Channel channel
        +str external_ref
        +Decimal amount_tzs
        +PaymentStatus status
        +unallocated() Decimal
    }
    class PaymentAllocator {
        <<service>>
        +allocate(p: Payment) List~Allocation~
    }
    class Allocation {
        +Decimal amount_tzs
    }
    class PaymentReversal {
        +str reason
    }
    class Receipt {
        +str receipt_no
    }
    class Journal {
        <<append-only>>
        +SourceType source_type
        +is_balanced() bool
    }
    class LedgerEntry {
        +Decimal debit_tzs
        +Decimal credit_tzs
    }
    class LedgerAccount {
        +str code
        +AccountKind kind
    }
    class PaymentGateway {
        <<interface>>
        +verify(request: Request) bool
        +parse(request: Request) PaymentNotice
        +acknowledge(notice: PaymentNotice) Response
    }
    class GepgAdapter
    class MpesaAdapter
    class AirtelAdapter
    class AttendanceSession {
        +date session_date
        +SessionKind kind
    }
    class AttendanceRecord {
        +AttendanceStatus status
        +Source source
        +datetime captured_at
        +UUID client_record_id
    }
    class Device {
        -str api_key_hash
        +DeviceKind kind
    }
    class AbsenceAlertJob {
        <<celery task>>
        +run(school: School, day: date) int
    }
    class SmsGateway {
        <<interface>>
        +send(to: str, body: str) ProviderRef
        +delivery_status(ref: str) SmsStatus
    }
    class BeemAdapter
    class NextSmsAdapter
    class SmsMessage {
        +str idempotency_key
        +SmsStatus status
    }
    class HostelRoom {
        +int capacity
    }
    class HostelAllocation
    class Bus {
        +int capacity
    }
    class TransportAssignment
    class VenueEvent {
        +int seats_occupied
    }

    FeeStructure "1" *-- "1..*" FeeStructureLine
    FeeStructureLine "0..*" --> "1" FeeItem
    Student "1" --> "0..*" Invoice : billed
    Invoice "1" *-- "1..*" InvoiceLine
    Invoice "1" *-- "0..*" Installment
    InvoiceLine "0..*" --> "0..1" DiscountRule
    Invoice "1" -- "0..*" GepgBill
    Student "1" --> "0..*" Payment : pays
    PaymentAllocator ..> Allocation : creates
    Payment "1" *-- "0..*" Allocation
    Allocation "0..*" --> "1" Invoice
    Payment "1" -- "0..1" PaymentReversal
    Payment "1" -- "0..1" Receipt
    Journal "1" *-- "2..*" LedgerEntry
    LedgerEntry "0..*" --> "1" LedgerAccount
    PaymentGateway <|.. GepgAdapter
    PaymentGateway <|.. MpesaAdapter
    PaymentGateway <|.. AirtelAdapter
    AttendanceSession "1" *-- "0..*" AttendanceRecord
    AttendanceRecord "0..*" --> "0..1" Device
    AbsenceAlertJob ..> SmsMessage : queues
    SmsGateway <|.. BeemAdapter
    SmsGateway <|.. NextSmsAdapter
    HostelRoom "1" -- "0..capacity" HostelAllocation
    Bus "1" -- "0..capacity" TransportAssignment
```

## 8.4 Design notes

- **No inheritance from Registrar.** The baseline made Students and Instructors inherit from Registrar. Here `User` is abstract (Person + login) and `Student`, `Guardian` and `Staff` specialise it. Teacher, SchoolAdmin and Bursar are **roles** of Staff (RBAC), because one person can be a teacher and a head of department at once.
- **Frozen classes.** `PublishedResult`, `StudentTermSummary`, `Journal`, `LedgerEntry`, `Allocation` and `PaymentReversal` have no update methods. Change means a new row: an amendment, a reversal or a reversing journal.
- **Interfaces for providers.** `PaymentGateway` and `SmsGateway` keep provider details (GePG XML signatures, M-Pesa, Airtel, Beem, NextSMS) in adapters. Switching provider is a configuration change; new providers are new adapters.
- **Services coordinate aggregates.** `Scheduler`, `ResultPublisher` and `PaymentAllocator` are services. Their database-side counterparts are the EXCLUDE constraints, `publish_results()` and `fn_allocation_guard`.
