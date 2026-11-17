from enum import StrEnum


class Gender(StrEnum):
    M = "M"
    F = "F"


class UserStatus(StrEnum):
    ACTIVE = "ACTIVE"
    DISABLED = "DISABLED"
    LOCKED = "LOCKED"
    NO_LOGIN = "NO_LOGIN"


class Language(StrEnum):
    sw = "sw"
    en = "en"


class SchoolStatus(StrEnum):
    ONBOARDING = "ONBOARDING"
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"
    CLOSED = "CLOSED"


class Ownership(StrEnum):
    GOVERNMENT = "GOVERNMENT"
    PRIVATE = "PRIVATE"
    FAITH_BASED = "FAITH_BASED"
    COMMUNITY = "COMMUNITY"


class StudentStatus(StrEnum):
    APPLICANT = "APPLICANT"
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"
    TRANSFERRED = "TRANSFERRED"
    GRADUATED = "GRADUATED"
    DROPPED_OUT = "DROPPED_OUT"


class Relationship(StrEnum):
    FATHER = "FATHER"
    MOTHER = "MOTHER"
    GUARDIAN = "GUARDIAN"
    SPONSOR = "SPONSOR"
    SIBLING = "SIBLING"
    OTHER = "OTHER"


class ConsentPurpose(StrEnum):
    SMS = "SMS"
    DATA_PROCESSING = "DATA_PROCESSING"
    PHOTO_PUBLICATION = "PHOTO_PUBLICATION"
    HEALTH_DATA = "HEALTH_DATA"


class ConsentChannel(StrEnum):
    PAPER = "PAPER"
    PORTAL = "PORTAL"
    SMS = "SMS"
    IN_PERSON = "IN_PERSON"


class EmploymentType(StrEnum):
    PERMANENT = "PERMANENT"
    CONTRACT = "CONTRACT"
    VOLUNTEER = "VOLUNTEER"
    INTERN = "INTERN"


class StaffStatus(StrEnum):
    ACTIVE = "ACTIVE"
    ON_LEAVE = "ON_LEAVE"
    TRANSFERRED = "TRANSFERRED"
    RETIRED = "RETIRED"
    TERMINATED = "TERMINATED"


class QualificationLevel(StrEnum):
    CERTIFICATE = "CERTIFICATE"
    DIPLOMA = "DIPLOMA"
    DEGREE = "DEGREE"
    POSTGRAD_DIP = "POSTGRAD_DIP"
    MASTERS = "MASTERS"
    PHD = "PHD"


class EducationLevelCode(StrEnum):
    PRE_PRIMARY = "PRE_PRIMARY"
    PRIMARY = "PRIMARY"
    O_LEVEL = "O_LEVEL"
    A_LEVEL = "A_LEVEL"


class EnrolmentStatus(StrEnum):
    ACTIVE = "ACTIVE"
    PROMOTED = "PROMOTED"
    REPEATED = "REPEATED"
    TRANSFERRED_OUT = "TRANSFERRED_OUT"
    GRADUATED = "GRADUATED"
    WITHDRAWN = "WITHDRAWN"


class JobKind(StrEnum):
    IMPORT_STUDENTS = "IMPORT_STUDENTS"
    IMPORT_GUARDIANS = "IMPORT_GUARDIANS"
    IMPORT_STAFF = "IMPORT_STAFF"
    IMPORT_MARKS = "IMPORT_MARKS"
    REPORT_CARDS = "REPORT_CARDS"
    RECEIPT_PDF = "RECEIPT_PDF"
    EXPORT = "EXPORT"
    COMPLIANCE_EXPORT = "COMPLIANCE_EXPORT"
    SMS_BATCH = "SMS_BATCH"
    RECONCILIATION = "RECONCILIATION"
    INVOICE_RUN = "INVOICE_RUN"
    PROMOTION = "PROMOTION"


class JobStatus(StrEnum):
    QUEUED = "QUEUED"
    RUNNING = "RUNNING"
    SUCCEEDED = "SUCCEEDED"
    FAILED = "FAILED"
    CANCELLED = "CANCELLED"


class SmsStatus(StrEnum):
    QUEUED = "QUEUED"
    SENT = "SENT"
    DELIVERED = "DELIVERED"
    FAILED = "FAILED"
    SKIPPED = "SKIPPED"


class OtpPurpose(StrEnum):
    LOGIN = "LOGIN"
    RESET = "RESET"


class RoomType(StrEnum):
    CLASSROOM = "CLASSROOM"
    LABORATORY = "LABORATORY"
    ICT_LAB = "ICT_LAB"
    WORKSHOP = "WORKSHOP"
    HALL = "HALL"


class ComponentCode(StrEnum):
    CA = "CA"
    TEST = "TEST"
    MIDTERM = "MIDTERM"
    TERMINAL = "TERMINAL"
    ANNUAL = "ANNUAL"
    PROJECT = "PROJECT"
    PRACTICAL = "PRACTICAL"


class ExamKind(StrEnum):
    MONTHLY = "MONTHLY"
    MIDTERM = "MIDTERM"
    TERMINAL = "TERMINAL"
    ANNUAL = "ANNUAL"
    MOCK = "MOCK"


class ApplicationStatus(StrEnum):
    INQUIRED = "INQUIRED"
    REQUIREMENTS_PENDING = "REQUIREMENTS_PENDING"
    UNDER_REVIEW = "UNDER_REVIEW"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"
    CANCELLED = "CANCELLED"


class DocumentStatus(StrEnum):
    PENDING = "PENDING"
    VALID = "VALID"
    INVALID = "INVALID"


class AmendmentStatus(StrEnum):
    PENDING = "PENDING"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"


class FeeStructureStatus(StrEnum):
    DRAFT = "DRAFT"
    APPROVED = "APPROVED"
    ARCHIVED = "ARCHIVED"


class DiscountKind(StrEnum):
    SCHOLARSHIP = "SCHOLARSHIP"
    SIBLING = "SIBLING"
    STAFF_CHILD = "STAFF_CHILD"
    BURSARY = "BURSARY"
    OTHER = "OTHER"


class InvoiceStatus(StrEnum):
    UNPAID = "UNPAID"
    PARTIALLY_PAID = "PARTIALLY_PAID"
    FULLY_PAID = "FULLY_PAID"
    OVERPAID = "OVERPAID"
    CANCELLED = "CANCELLED"


class LineKind(StrEnum):
    CHARGE = "CHARGE"
    DISCOUNT = "DISCOUNT"


class GepgStatus(StrEnum):
    REQUESTED = "REQUESTED"
    ISSUED = "ISSUED"
    FAILED = "FAILED"
    EXPIRED = "EXPIRED"
    CANCELLED = "CANCELLED"
    PAID = "PAID"


class Channel(StrEnum):
    GEPG = "GEPG"
    MPESA = "MPESA"
    TIGOPESA = "TIGOPESA"
    AIRTEL = "AIRTEL"
    HALOPESA = "HALOPESA"
    BANK = "BANK"
    CASH = "CASH"


class PaymentStatus(StrEnum):
    PENDING = "PENDING"
    CONFIRMED = "CONFIRMED"
    FAILED = "FAILED"
    REVERSED = "REVERSED"


class JournalSource(StrEnum):
    INVOICE = "INVOICE"
    INVOICE_CANCEL = "INVOICE_CANCEL"
    PAYMENT = "PAYMENT"
    REVERSAL = "REVERSAL"
    DISCOUNT = "DISCOUNT"
    ADJUSTMENT = "ADJUSTMENT"
    CASH_ENTRY = "CASH_ENTRY"
    CASH_REVERSE = "CASH_REVERSE"


class DepositStatus(StrEnum):
    SUBMITTED = "SUBMITTED"
    CONFIRMED = "CONFIRMED"
    REJECTED = "REJECTED"
    MATCHED = "MATCHED"


class RunStatus(StrEnum):
    RUNNING = "RUNNING"
    BALANCED = "BALANCED"
    EXCEPTIONS = "EXCEPTIONS"
    FAILED = "FAILED"


class MatchStatus(StrEnum):
    MATCHED = "MATCHED"
    MISSING_IN_SYSTEM = "MISSING_IN_SYSTEM"
    MISSING_IN_STATEMENT = "MISSING_IN_STATEMENT"
    AMOUNT_MISMATCH = "AMOUNT_MISMATCH"


class RequestStatus(StrEnum):
    PENDING = "PENDING"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"


class DeviceKind(StrEnum):
    RFID_READER = "RFID_READER"
    QR_SCANNER = "QR_SCANNER"
    TABLET = "TABLET"


class DeviceStatus(StrEnum):
    ACTIVE = "ACTIVE"
    DISABLED = "DISABLED"


class CardKind(StrEnum):
    RFID = "RFID"
    QR = "QR"


class CardStatus(StrEnum):
    ACTIVE = "ACTIVE"
    LOST = "LOST"
    REVOKED = "REVOKED"


class SessionKind(StrEnum):
    REGISTER = "REGISTER"
    GATE = "GATE"
    LESSON = "LESSON"


class AttendanceStatus(StrEnum):
    PRESENT = "PRESENT"
    ABSENT = "ABSENT"
    LATE = "LATE"
    EXCUSED = "EXCUSED"


class AttendanceSource(StrEnum):
    MANUAL = "MANUAL"
    RFID = "RFID"
    QR = "QR"


class Audience(StrEnum):
    SCHOOL = "SCHOOL"
    STAFF = "STAFF"
    PARENTS = "PARENTS"
    CLASS = "CLASS"
    STREAM = "STREAM"
    INDIVIDUAL = "INDIVIDUAL"


class CreditKind(StrEnum):
    TOPUP = "TOPUP"
    DEBIT = "DEBIT"
    REFUND = "REFUND"


class HostelGender(StrEnum):
    M = "M"
    F = "F"
    MIXED = "MIXED"


class AccommodationStatus(StrEnum):
    PENDING = "PENDING"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"
    CANCELLED = "CANCELLED"


class BusStatus(StrEnum):
    ACTIVE = "ACTIVE"
    REPAIR = "REPAIR"
    RETIRED = "RETIRED"


class DisciplineCategory(StrEnum):
    LATENESS = "LATENESS"
    TRUANCY = "TRUANCY"
    FIGHTING = "FIGHTING"
    BULLYING = "BULLYING"
    THEFT = "THEFT"
    CHEATING = "CHEATING"
    PROPERTY_DAMAGE = "PROPERTY_DAMAGE"
    OTHER = "OTHER"


class DisciplineStatus(StrEnum):
    OPEN = "OPEN"
    RESOLVED = "RESOLVED"


class ActivityKind(StrEnum):
    CLUB = "CLUB"
    SPORT = "SPORT"
    SOCIETY = "SOCIETY"
    ARTS = "ARTS"


class ActivityRole(StrEnum):
    MEMBER = "MEMBER"
    LEADER = "LEADER"
    CAPTAIN = "CAPTAIN"
    SECRETARY = "SECRETARY"


class HealthKind(StrEnum):
    ALLERGY = "ALLERGY"
    CONDITION = "CONDITION"
    CLINIC_VISIT = "CLINIC_VISIT"
    VACCINATION = "VACCINATION"


class DsrType(StrEnum):
    EXPORT = "EXPORT"
    CORRECT = "CORRECT"
    DELETE = "DELETE"


class DsrStatus(StrEnum):
    RECEIVED = "RECEIVED"
    IN_PROGRESS = "IN_PROGRESS"
    COMPLETED = "COMPLETED"
    REJECTED = "REJECTED"


class FilePurpose(StrEnum):
    PHOTO = "PHOTO"
    STUDY_MATERIAL = "STUDY_MATERIAL"
    HOMEWORK = "HOMEWORK"
    SUBMISSION = "SUBMISSION"
    RECEIPT = "RECEIPT"
    CERT_TEMPLATE = "CERT_TEMPLATE"


class ScanStatus(StrEnum):
    PENDING = "PENDING"
    CLEAN = "CLEAN"
    INFECTED = "INFECTED"
    SKIPPED = "SKIPPED"
