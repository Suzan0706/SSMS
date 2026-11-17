"""Abstract person (users) and its subtypes; access tables; consent and privacy."""

import uuid
from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import CHAR, DateTime, LargeBinary, Numeric, SmallInteger, String
from sqlalchemy.dialects.postgresql import INET
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, SoftDeleteMixin, TenantMixin, TenantRowMixin
from app.models.enums import (
    ConsentChannel,
    ConsentPurpose,
    EmploymentType,
    Gender,
    OtpPurpose,
    QualificationLevel,
    Relationship,
    StaffStatus,
    StudentStatus,
    UserStatus,
)


class User(TenantMixin, SoftDeleteMixin, Base):
    __tablename__ = "users"
    first_name: Mapped[str] = mapped_column(String(50))
    middle_name: Mapped[str | None] = mapped_column(String(50))
    last_name: Mapped[str] = mapped_column(String(50))
    gender: Mapped[Gender]
    date_of_birth: Mapped[date | None]
    phone_enc: Mapped[bytes | None] = mapped_column(LargeBinary)
    phone_hash: Mapped[bytes | None] = mapped_column(LargeBinary)
    phone_last4: Mapped[str | None] = mapped_column(CHAR(4))
    email: Mapped[str | None] = mapped_column(String(254))
    username: Mapped[str | None] = mapped_column(String(50))
    password_hash: Mapped[str | None] = mapped_column(String(255))
    preferred_language: Mapped[str] = mapped_column(CHAR(2), default="sw")
    status: Mapped[UserStatus] = mapped_column(default=UserStatus.ACTIVE)
    failed_login_count: Mapped[int] = mapped_column(SmallInteger, default=0)
    locked_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_login_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    must_change_password: Mapped[bool] = mapped_column(default=False)

    @property
    def full_name(self) -> str:
        return " ".join(p for p in (self.first_name, self.middle_name, self.last_name) if p)


class UserRole(TenantMixin, Base):
    __tablename__ = "user_roles"
    user_id: Mapped[uuid.UUID]
    role_id: Mapped[uuid.UUID]
    granted_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now().astimezone())
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class RefreshToken(TenantRowMixin, Base):
    __tablename__ = "refresh_tokens"
    user_id: Mapped[uuid.UUID]
    token_hash: Mapped[str] = mapped_column(CHAR(64))
    family_id: Mapped[uuid.UUID]
    issued_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    user_agent: Mapped[str | None] = mapped_column(String(255))
    ip_address: Mapped[str | None] = mapped_column(INET)


class OtpCode(TenantRowMixin, Base):
    __tablename__ = "otp_codes"
    user_id: Mapped[uuid.UUID]
    code_hash: Mapped[str] = mapped_column(CHAR(64))
    purpose: Mapped[OtpPurpose] = mapped_column(default=OtpPurpose.LOGIN)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    attempts: Mapped[int] = mapped_column(SmallInteger, default=0)
    consumed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class Guardian(TenantMixin, SoftDeleteMixin, Base):
    __tablename__ = "guardians"
    user_id: Mapped[uuid.UUID]
    nida_enc: Mapped[bytes | None] = mapped_column(LargeBinary)
    nida_hash: Mapped[bytes | None] = mapped_column(LargeBinary)
    occupation: Mapped[str | None] = mapped_column(String(80))
    address: Mapped[str | None] = mapped_column(String(200))


class Student(TenantMixin, SoftDeleteMixin, Base):
    __tablename__ = "students"
    user_id: Mapped[uuid.UUID]
    admission_no: Mapped[str] = mapped_column(String(20))
    birth_cert_no_enc: Mapped[bytes | None] = mapped_column(LargeBinary)
    birth_cert_no_hash: Mapped[bytes | None] = mapped_column(LargeBinary)
    nida_enc: Mapped[bytes | None] = mapped_column(LargeBinary)
    nida_hash: Mapped[bytes | None] = mapped_column(LargeBinary)
    prem_number: Mapped[str | None] = mapped_column(String(20))
    photo_file_key: Mapped[str | None] = mapped_column(String(255))
    status: Mapped[StudentStatus] = mapped_column(default=StudentStatus.APPLICANT)
    admission_date: Mapped[date | None]


class StudentStatusHistory(TenantMixin, Base):
    __tablename__ = "student_status_history"
    student_id: Mapped[uuid.UUID]
    old_status: Mapped[StudentStatus | None]
    new_status: Mapped[StudentStatus]
    reason: Mapped[str] = mapped_column(String(300))
    effective_date: Mapped[date]


class StudentGuardian(TenantMixin, SoftDeleteMixin, Base):
    __tablename__ = "student_guardians"
    student_id: Mapped[uuid.UUID]
    guardian_id: Mapped[uuid.UUID]
    relationship: Mapped[Relationship]
    is_primary: Mapped[bool] = mapped_column(default=False)
    receives_sms: Mapped[bool] = mapped_column(default=True)


class ConsentRecord(TenantMixin, Base):
    __tablename__ = "consent_records"
    guardian_id: Mapped[uuid.UUID]
    student_id: Mapped[uuid.UUID | None]
    purpose: Mapped[ConsentPurpose]
    granted: Mapped[bool]
    channel: Mapped[ConsentChannel]
    recorded_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now().astimezone())
    withdrawn_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class Department(TenantMixin, SoftDeleteMixin, Base):
    __tablename__ = "departments"
    code: Mapped[str] = mapped_column(String(10))
    name_en: Mapped[str] = mapped_column(String(80))
    name_sw: Mapped[str] = mapped_column(String(80))
    head_staff_id: Mapped[uuid.UUID | None]


class Designation(TenantMixin, SoftDeleteMixin, Base):
    __tablename__ = "designations"
    code: Mapped[str] = mapped_column(String(20))
    name_en: Mapped[str] = mapped_column(String(60))
    name_sw: Mapped[str] = mapped_column(String(60))


class Staff(TenantMixin, SoftDeleteMixin, Base):
    __tablename__ = "staff"
    user_id: Mapped[uuid.UUID]
    staff_no: Mapped[str] = mapped_column(String(20))
    check_no: Mapped[str | None] = mapped_column(String(20))
    department_id: Mapped[uuid.UUID | None]
    designation_id: Mapped[uuid.UUID | None]
    employment_type: Mapped[EmploymentType] = mapped_column(default=EmploymentType.PERMANENT)
    employment_date: Mapped[date | None]
    salary_tzs: Mapped[Decimal | None] = mapped_column(Numeric(14, 2))
    max_periods_per_week: Mapped[int] = mapped_column(SmallInteger, default=30)
    status: Mapped[StaffStatus] = mapped_column(default=StaffStatus.ACTIVE)
    photo_file_key: Mapped[str | None] = mapped_column(String(255))


class StaffQualification(TenantMixin, SoftDeleteMixin, Base):
    __tablename__ = "staff_qualifications"
    staff_id: Mapped[uuid.UUID]
    level: Mapped[QualificationLevel]
    title: Mapped[str] = mapped_column(String(120))
    institution: Mapped[str] = mapped_column(String(120))
    year_awarded: Mapped[int] = mapped_column(SmallInteger)
