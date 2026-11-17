"""Finance defaults created at onboarding, communication (templates, SMS, credit, announcements, inbox), audit, jobs,
idempotency, privacy requests."""

import uuid
from datetime import datetime

from sqlalchemy import CHAR, DateTime, Integer, LargeBinary, SmallInteger, String
from sqlalchemy.dialects.postgresql import INET, JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, IdMixin, SoftDeleteMixin, TenantMixin
from app.models.enums import (
    Audience,
    CreditKind,
    DsrStatus,
    DsrType,
    FilePurpose,
    JobKind,
    JobStatus,
    ScanStatus,
    SmsStatus,
)


class LedgerAccount(TenantMixin, Base):
    __tablename__ = "ledger_accounts"
    code: Mapped[str] = mapped_column(String(10))
    name_en: Mapped[str] = mapped_column(String(80))
    name_sw: Mapped[str] = mapped_column(String(80))
    kind: Mapped[str] = mapped_column(String(10))
    is_system: Mapped[bool] = mapped_column(default=True)


class FeeItem(TenantMixin, SoftDeleteMixin, Base):
    __tablename__ = "fee_items"
    code: Mapped[str] = mapped_column(String(12))
    name_en: Mapped[str] = mapped_column(String(80))
    name_sw: Mapped[str] = mapped_column(String(80))
    gfs_code: Mapped[str | None] = mapped_column(String(20))
    income_account_id: Mapped[uuid.UUID]


class MessageTemplate(TenantMixin, SoftDeleteMixin, Base):
    __tablename__ = "message_templates"
    key: Mapped[str] = mapped_column(String(40))
    language: Mapped[str] = mapped_column(CHAR(2))
    body: Mapped[str] = mapped_column(String(480))
    is_active: Mapped[bool] = mapped_column(default=True)


class SmsMessage(TenantMixin, Base):
    __tablename__ = "sms_messages"
    to_user_id: Mapped[uuid.UUID | None]
    to_phone_enc: Mapped[bytes] = mapped_column(LargeBinary)
    to_phone_last4: Mapped[str] = mapped_column(CHAR(4))
    template_key: Mapped[str | None] = mapped_column(String(40))
    language: Mapped[str] = mapped_column(CHAR(2))
    body: Mapped[str] = mapped_column(String(480))
    segments: Mapped[int] = mapped_column(SmallInteger)
    provider: Mapped[str] = mapped_column(String(12))
    provider_message_id: Mapped[str | None] = mapped_column(String(80))
    status: Mapped[SmsStatus] = mapped_column(default=SmsStatus.QUEUED)
    cost_credits: Mapped[int] = mapped_column(SmallInteger, default=0)
    error: Mapped[str | None] = mapped_column(String(300))
    idempotency_key: Mapped[str] = mapped_column(String(80))
    related_entity: Mapped[str | None] = mapped_column(String(40))
    related_id: Mapped[uuid.UUID | None]
    queued_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now().astimezone())
    sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    delivered_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class AuditLog(IdMixin, Base):
    __tablename__ = "audit_logs"
    school_id: Mapped[uuid.UUID]
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now().astimezone())
    actor_user_id: Mapped[uuid.UUID | None]
    actor_platform_id: Mapped[uuid.UUID | None]
    action: Mapped[str] = mapped_column(String(20))
    entity_type: Mapped[str] = mapped_column(String(40))
    entity_id: Mapped[uuid.UUID | None]
    before_data: Mapped[dict | None] = mapped_column(JSONB)
    after_data: Mapped[dict | None] = mapped_column(JSONB)
    ip_address: Mapped[str | None] = mapped_column(INET)
    user_agent: Mapped[str | None] = mapped_column(String(255))
    request_id: Mapped[uuid.UUID | None]
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now().astimezone())


class BackgroundJob(TenantMixin, Base):
    __tablename__ = "background_jobs"
    kind: Mapped[JobKind]
    status: Mapped[JobStatus] = mapped_column(default=JobStatus.QUEUED)
    progress_pct: Mapped[int] = mapped_column(SmallInteger, default=0)
    total_items: Mapped[int | None] = mapped_column(Integer)
    processed_items: Mapped[int] = mapped_column(Integer, default=0)
    error_count: Mapped[int] = mapped_column(Integer, default=0)
    input_file_key: Mapped[str | None] = mapped_column(String(255))
    result_file_key: Mapped[str | None] = mapped_column(String(255))
    error_report_file_key: Mapped[str | None] = mapped_column(String(255))
    idempotency_key: Mapped[str | None] = mapped_column(String(80))
    celery_task_id: Mapped[str | None] = mapped_column(String(64))
    requested_by: Mapped[uuid.UUID]
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class IdempotencyKey(TenantMixin, Base):
    __tablename__ = "idempotency_keys"
    scope: Mapped[str] = mapped_column(String(60))
    key: Mapped[str] = mapped_column(String(80))
    request_hash: Mapped[str] = mapped_column(CHAR(64))
    response_status: Mapped[int | None] = mapped_column(SmallInteger)
    response_body: Mapped[dict | None] = mapped_column(JSONB)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class Announcement(TenantMixin, SoftDeleteMixin, Base):
    __tablename__ = "announcements"
    title: Mapped[str] = mapped_column(String(120))
    body: Mapped[str] = mapped_column(String(2000))
    language: Mapped[str] = mapped_column(CHAR(2), default="sw")
    audience: Mapped[Audience]
    class_id: Mapped[uuid.UUID | None]
    stream_id: Mapped[uuid.UUID | None]
    target_user_id: Mapped[uuid.UUID | None]
    send_sms: Mapped[bool] = mapped_column(default=False)
    publish_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now().astimezone())


class Notification(TenantMixin, Base):
    __tablename__ = "notifications"
    user_id: Mapped[uuid.UUID]
    kind: Mapped[str] = mapped_column(String(30))
    title: Mapped[str] = mapped_column(String(120))
    body: Mapped[str] = mapped_column(String(500))
    link: Mapped[str | None] = mapped_column(String(200))
    read_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class SmsCreditTransaction(TenantMixin, Base):
    __tablename__ = "sms_credit_transactions"
    kind: Mapped[CreditKind]
    credits: Mapped[int] = mapped_column(Integer)
    sms_message_id: Mapped[uuid.UUID | None]
    note: Mapped[str | None] = mapped_column(String(200))


class DataSubjectRequest(TenantMixin, Base):
    __tablename__ = "data_subject_requests"
    subject_user_id: Mapped[uuid.UUID]
    request_type: Mapped[DsrType]
    status: Mapped[DsrStatus] = mapped_column(default=DsrStatus.RECEIVED)
    details: Mapped[str | None] = mapped_column(String(500))
    requested_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now().astimezone())
    due_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    handled_by: Mapped[uuid.UUID | None]
    result_file_key: Mapped[str | None] = mapped_column(String(255))


class StoredFile(TenantMixin, SoftDeleteMixin, Base):
    """An uploaded file. The bytes live in storage under storage_key; this row is the only way to reach them."""

    __tablename__ = "stored_files"
    storage_key: Mapped[str] = mapped_column(String(255))
    purpose: Mapped[FilePurpose]
    original_name: Mapped[str] = mapped_column(String(200))
    content_type: Mapped[str] = mapped_column(String(100))
    size_bytes: Mapped[int] = mapped_column(Integer)
    sha256: Mapped[str] = mapped_column(CHAR(64))
    scan_status: Mapped[ScanStatus] = mapped_column(default=ScanStatus.PENDING)
