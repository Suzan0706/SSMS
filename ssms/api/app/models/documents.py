"""Certificates, ID cards and email messages (migration 0018)."""

import uuid
from datetime import date, datetime

from sqlalchemy import CHAR, DateTime, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, SoftDeleteMixin, TenantMixin


class CertificateTemplate(TenantMixin, SoftDeleteMixin, Base):
    __tablename__ = "certificate_templates"
    kind: Mapped[str] = mapped_column(String(12))
    name: Mapped[str] = mapped_column(String(80))
    language: Mapped[str] = mapped_column(CHAR(2))
    body: Mapped[str] = mapped_column(String(4000))
    background_file_id: Mapped[uuid.UUID | None]


class Certificate(TenantMixin, Base):
    """An issued certificate: the text is frozen at issue (trigger); it can only be revoked, once, with a reason."""

    __tablename__ = "certificates"
    template_id: Mapped[uuid.UUID]
    student_id: Mapped[uuid.UUID]
    serial_no: Mapped[str] = mapped_column(String(20))
    issued_on: Mapped[date]
    rendered_text: Mapped[str] = mapped_column(String(4000))
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    revoked_reason: Mapped[str | None] = mapped_column(String(300))


class IdentityCard(TenantMixin, Base):
    __tablename__ = "identity_cards"
    user_id: Mapped[uuid.UUID]
    card_no: Mapped[str] = mapped_column(String(20))
    valid_until: Mapped[date]
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class EmailMessage(TenantMixin, Base):
    __tablename__ = "email_messages"
    to_user_id: Mapped[uuid.UUID]
    template_key: Mapped[str | None] = mapped_column(String(40))
    language: Mapped[str] = mapped_column(CHAR(2))
    subject: Mapped[str] = mapped_column(String(200))
    body: Mapped[str] = mapped_column(Text)
    provider: Mapped[str] = mapped_column(String(12))
    provider_message_id: Mapped[str | None] = mapped_column(String(120))
    status: Mapped[str] = mapped_column(String(10), default="QUEUED")
    error: Mapped[str | None] = mapped_column(String(300))
    idempotency_key: Mapped[str] = mapped_column(String(80))
    related_entity: Mapped[str | None] = mapped_column(String(40))
    related_id: Mapped[uuid.UUID | None]
    queued_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now().astimezone())
    sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
