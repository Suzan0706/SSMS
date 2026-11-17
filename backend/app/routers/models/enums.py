from enum import StrEnum


class Role(StrEnum):
    ADMIN = "ADMIN"
    REGISTRAR = "REGISTRAR"
    BURSAR = "BURSAR"
    INSTRUCTOR = "INSTRUCTOR"
    STUDENT = "STUDENT"
    PARENT = "PARENT"


STAFF_ROLES = (Role.ADMIN, Role.REGISTRAR, Role.BURSAR)


class Gender(StrEnum):
    M = "M"
    F = "F"


class StudentStatus(StrEnum):
    APPLICANT = "APPLICANT"
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"
    TRANSFERRED = "TRANSFERRED"
    DROPPED_OUT = "DROPPED_OUT"
    GRADUATED = "GRADUATED"


class GuardianRelationship(StrEnum):
    FATHER = "FATHER"
    MOTHER = "MOTHER"
    GUARDIAN = "GUARDIAN"
    SPONSOR = "SPONSOR"
    OTHER = "OTHER"


class EducationLevel(StrEnum):
    PRE_PRIMARY = "PRE_PRIMARY"
    PRIMARY = "PRIMARY"
    O_LEVEL = "O_LEVEL"
    A_LEVEL = "A_LEVEL"


class RoomType(StrEnum):
    CLASSROOM = "CLASSROOM"
    LABORATORY = "LABORATORY"
    ICT_LAB = "ICT_LAB"
    LIBRARY = "LIBRARY"
    HALL = "HALL"


class EnrolmentStatus(StrEnum):
    PENDING = "PENDING"
    SUBMITTED = "SUBMITTED"
    INVALID = "INVALID"
    VALIDATED = "VALIDATED"
    CONFIRMED = "CONFIRMED"
    CANCELLED = "CANCELLED"


class DocumentStatus(StrEnum):
    PENDING = "PENDING"
    VALID = "VALID"
    INVALID = "INVALID"


class FeeItem(StrEnum):
    TUITION = "TUITION"
    BOARDING = "BOARDING"
    MEALS = "MEALS"
    EXAMINATION = "EXAMINATION"
    UNIFORM = "UNIFORM"
    DEVELOPMENT = "DEVELOPMENT"
    OTHER = "OTHER"


class TransactionType(StrEnum):
    PAYMENT = "PAYMENT"
    REFUND = "REFUND"
    WAIVER = "WAIVER"
    REVERSAL = "REVERSAL"


class PaymentMethod(StrEnum):
    CASH = "CASH"
    BANK = "BANK"
    MPESA = "MPESA"
    TIGO_PESA = "TIGO_PESA"          # rebranded "Mixx by Yas"
    AIRTEL_MONEY = "AIRTEL_MONEY"
    GEPG = "GEPG"


class TransactionStatus(StrEnum):
    PENDING = "PENDING"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"


class TransactionSource(StrEnum):
    MANUAL = "MANUAL"
    GEPG = "GEPG"
    MOBILE_API = "MOBILE_API"
