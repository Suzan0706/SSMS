"""Global (non-tenant) tables: platform admins, roles, permissions; and the tenant registry."""

import uuid
from datetime import datetime, time

from sqlalchemy import CHAR, DateTime, LargeBinary, SmallInteger, String
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, IdMixin, SoftDeleteMixin, TimestampMixin
from app.models.enums import Ownership, SchoolStatus


class PlatformAdmin(IdMixin, TimestampMixin, Base):
    __tablename__ = "platform_admins"
    full_name: Mapped[str] = mapped_column(String(100))
    email: Mapped[str] = mapped_column(String(254))
    password_hash: Mapped[str] = mapped_column(String(255))
    mfa_secret_enc: Mapped[bytes | None] = mapped_column(LargeBinary)
    is_active: Mapped[bool] = mapped_column(default=True)
    last_login_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class Role(IdMixin, TimestampMixin, Base):
    __tablename__ = "roles"
    code: Mapped[str] = mapped_column(String(30))
    name_en: Mapped[str] = mapped_column(String(60))
    name_sw: Mapped[str] = mapped_column(String(60))
    is_system: Mapped[bool] = mapped_column(default=True)


class Permission(IdMixin, TimestampMixin, Base):
    __tablename__ = "permissions"
    code: Mapped[str] = mapped_column(String(60))
    module: Mapped[str] = mapped_column(String(30))
    description_en: Mapped[str] = mapped_column(String(200))
    description_sw: Mapped[str] = mapped_column(String(200))


class RolePermission(IdMixin, TimestampMixin, Base):
    __tablename__ = "role_permissions"
    role_id: Mapped[uuid.UUID]
    permission_id: Mapped[uuid.UUID]


class Region(IdMixin, Base):
    __tablename__ = "regions"
    name: Mapped[str] = mapped_column(String(40))


class District(IdMixin, Base):
    __tablename__ = "districts"
    region_id: Mapped[uuid.UUID]
    name: Mapped[str] = mapped_column(String(40))


class School(IdMixin, TimestampMixin, SoftDeleteMixin, Base):
    __tablename__ = "schools"
    code: Mapped[str] = mapped_column(String(20))
    name: Mapped[str] = mapped_column(String(150))
    registration_no: Mapped[str | None] = mapped_column(String(30))
    ownership: Mapped[Ownership]
    district_id: Mapped[uuid.UUID]
    status: Mapped[SchoolStatus] = mapped_column(default=SchoolStatus.ONBOARDING)
    created_by: Mapped[uuid.UUID | None]


class SchoolSettings(IdMixin, TimestampMixin, SoftDeleteMixin, Base):
    __tablename__ = "school_settings"
    school_id: Mapped[uuid.UUID]
    motto: Mapped[str | None] = mapped_column(String(150))
    logo_file_key: Mapped[str | None] = mapped_column(String(255))
    postal_address: Mapped[str | None] = mapped_column(String(150))
    physical_address: Mapped[str | None] = mapped_column(String(200))
    phone: Mapped[str | None] = mapped_column(String(12))
    email: Mapped[str | None] = mapped_column(String(254))
    medium_of_instruction: Mapped[str] = mapped_column(String(10), default="KISWAHILI")
    default_language: Mapped[str] = mapped_column(CHAR(2), default="sw")
    sms_sender_id: Mapped[str | None] = mapped_column(String(11))
    gepg_sp_code: Mapped[str | None] = mapped_column(String(10))
    gepg_sub_sp_code: Mapped[str | None] = mapped_column(String(10))
    absence_sms_cutoff: Mapped[time] = mapped_column(default=time(8, 30))
    is_open_for_enrolment: Mapped[bool] = mapped_column(default=True)
    admission_prefix: Mapped[str] = mapped_column(String(4), default="TZ")
    created_by: Mapped[uuid.UUID | None]


class DocumentSequence(IdMixin, TimestampMixin, Base):
    __tablename__ = "document_sequences"
    school_id: Mapped[uuid.UUID]
    doc_type: Mapped[str] = mapped_column(String(20))
    year: Mapped[int] = mapped_column(SmallInteger)
    last_value: Mapped[int]
