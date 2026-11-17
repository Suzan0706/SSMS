from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import CHAR, BigInteger, DateTime, ForeignKey, Identity, String, func
from sqlalchemy.dialects.postgresql import INET, JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base


class RefreshToken(Base):
    __tablename__ = "refresh_tokens"

    token_id: Mapped[int] = mapped_column(BigInteger, Identity(always=True), primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.user_id"))
    token_hash: Mapped[str] = mapped_column(CHAR(64))
    family_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True))
    issued_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    user_agent: Mapped[str | None] = mapped_column(String(255))
    ip_address: Mapped[str | None] = mapped_column(INET)


class AuditLog(Base):
    """Append-only. Row changes are written by the fn_audit_row trigger; security events by the API."""

    __tablename__ = "audit_logs"

    audit_id: Mapped[int] = mapped_column(BigInteger, Identity(always=True), primary_key=True)
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    actor_user_id: Mapped[int | None] = mapped_column(ForeignKey("users.user_id"))
    actor_role: Mapped[str | None] = mapped_column(String(12))
    action: Mapped[str] = mapped_column(String(20))
    entity_type: Mapped[str] = mapped_column(String(40))
    entity_id: Mapped[str | None] = mapped_column(String(40))
    old_values: Mapped[dict | None] = mapped_column(JSONB)
    new_values: Mapped[dict | None] = mapped_column(JSONB)
    ip_address: Mapped[str | None] = mapped_column(INET)
    user_agent: Mapped[str | None] = mapped_column(String(255))
    request_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
