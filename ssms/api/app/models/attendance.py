"""Attendance: gate devices, RFID/QR cards, register/gate/lesson sessions, records and absence alerts
(design/sql/schema.sql §8). One record per student per session; client_record_id makes offline sync idempotent."""

import uuid
from datetime import date, datetime

from sqlalchemy import CHAR, DateTime, String
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, SoftDeleteMixin, TenantMixin
from app.models.enums import (
    AttendanceSource,
    AttendanceStatus,
    CardKind,
    CardStatus,
    DeviceKind,
    DeviceStatus,
    SessionKind,
)


class Device(TenantMixin, SoftDeleteMixin, Base):
    __tablename__ = "devices"
    name: Mapped[str] = mapped_column(String(60))
    kind: Mapped[DeviceKind]
    api_key_hash: Mapped[str] = mapped_column(CHAR(64))
    location: Mapped[str | None] = mapped_column(String(100))
    status: Mapped[DeviceStatus] = mapped_column(default=DeviceStatus.ACTIVE)
    last_seen_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class RfidCard(TenantMixin, SoftDeleteMixin, Base):
    __tablename__ = "rfid_cards"
    student_id: Mapped[uuid.UUID]
    token_hash: Mapped[str] = mapped_column(CHAR(64))
    kind: Mapped[CardKind]
    status: Mapped[CardStatus] = mapped_column(default=CardStatus.ACTIVE)
    issued_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now().astimezone())


class AttendanceSession(TenantMixin, Base):
    __tablename__ = "attendance_sessions"
    session_date: Mapped[date]
    kind: Mapped[SessionKind]
    stream_id: Mapped[uuid.UUID | None]
    timetable_slot_id: Mapped[uuid.UUID | None]
    taken_by: Mapped[uuid.UUID | None]
    opened_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now().astimezone())
    closed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class AttendanceRecord(TenantMixin, Base):
    __tablename__ = "attendance_records"
    session_id: Mapped[uuid.UUID]
    student_id: Mapped[uuid.UUID]
    status: Mapped[AttendanceStatus]
    source: Mapped[AttendanceSource] = mapped_column(default=AttendanceSource.MANUAL)
    device_id: Mapped[uuid.UUID | None]
    captured_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    synced_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now().astimezone())
    client_record_id: Mapped[uuid.UUID]
    recorded_by: Mapped[uuid.UUID | None]


class AbsenceAlert(TenantMixin, Base):
    __tablename__ = "absence_alerts"
    student_id: Mapped[uuid.UUID]
    absence_date: Mapped[date]
    sms_message_id: Mapped[uuid.UUID | None]
