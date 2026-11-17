"""Declarative base and the column mixins every tenant table shares (see design/06-data-model.md)."""

import enum
import uuid
from datetime import datetime

from sqlalchemy import DateTime, event, func
from sqlalchemy import Enum as SAEnum
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

from app.core.ids import uuid7


class Base(DeclarativeBase):
    # Enumerations are VARCHAR + CHECK in PostgreSQL, not native ENUM types.
    type_annotation_map = {
        enum.Enum: SAEnum(enum.Enum, native_enum=False, create_constraint=False, length=30),
    }


class IdMixin:
    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid7)


@event.listens_for(IdMixin, "init", propagate=True)
def _assign_id(target, args, kwargs) -> None:
    """Give new objects their UUIDv7 at construction, so related rows can reference it before the flush."""
    kwargs.setdefault("id", uuid7())


class TimestampMixin:
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class TenantRowMixin(IdMixin, TimestampMixin):
    """school_id is set explicitly by repositories; RLS rejects any other value."""

    school_id: Mapped[uuid.UUID]


class TenantMixin(TenantRowMixin):
    created_by: Mapped[uuid.UUID | None]


class SoftDeleteMixin:
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
