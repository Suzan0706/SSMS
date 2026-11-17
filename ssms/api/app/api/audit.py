"""/audit-logs: the append-only trail of this school (identifiers and secrets are redacted at write time)."""

import uuid
from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import Principal, require_permission
from app.core.pagination import Cursor, Limit, Page, paginate
from app.db.session import get_session
from app.models import AuditLog

router = APIRouter(tags=["audit"])


class AuditOut(BaseModel):
    id: uuid.UUID
    occurred_at: datetime
    actor_user_id: uuid.UUID | None
    actor_platform_id: uuid.UUID | None
    action: str
    entity_type: str
    entity_id: uuid.UUID | None
    before_data: dict | None
    after_data: dict | None
    ip_address: str | None
    request_id: uuid.UUID | None


@router.get("/audit-logs", response_model=Page[AuditOut], summary="Newest first; filter by entity, actor, action, time")
async def audit_logs(
    entity: Annotated[str | None, Query(max_length=40)] = None,
    entity_id: uuid.UUID | None = None,
    actor: uuid.UUID | None = None,
    action: Annotated[str | None, Query(max_length=20)] = None,
    from_: Annotated[datetime | None, Query(alias="from")] = None,
    to: datetime | None = None,
    limit: Limit = 50,
    cursor: Cursor = None,
    _: Principal = require_permission("audit.read"),
    session: AsyncSession = Depends(get_session),
):
    stmt = select(
        AuditLog.id,
        AuditLog.occurred_at,
        AuditLog.actor_user_id,
        AuditLog.actor_platform_id,
        AuditLog.action,
        AuditLog.entity_type,
        AuditLog.entity_id,
        AuditLog.before_data,
        AuditLog.after_data,
        AuditLog.ip_address,
        AuditLog.request_id,
    )
    for column, value in (
        (AuditLog.entity_type, entity),
        (AuditLog.entity_id, entity_id),
        (AuditLog.actor_user_id, actor),
        (AuditLog.action, action),
    ):
        if value is not None:
            stmt = stmt.where(column == value)
    if from_:
        stmt = stmt.where(AuditLog.occurred_at >= from_)
    if to:
        stmt = stmt.where(AuditLog.occurred_at < to)
    rows, next_cursor = await paginate(
        session, stmt, [AuditLog.occurred_at, AuditLog.id], limit, cursor, descending=True
    )
    return Page[AuditOut](
        items=[AuditOut(**{**r._mapping, "ip_address": str(r.ip_address) if r.ip_address else None}) for r in rows],
        next_cursor=next_cursor,
    )
