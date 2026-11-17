"""Explicit audit events (logins, exports, sensitive reads). Row changes are audited by the fn_audit_row trigger."""

import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import DbContext
from app.models import AuditLog


async def record(
    session: AsyncSession,
    action: str,
    entity_type: str,
    entity_id: uuid.UUID | None = None,
    after: dict | None = None,
    user_agent: str | None = None,
    actor_user_id: uuid.UUID | None = None,
) -> None:
    """Append one audit row in the current school context (never contains secrets or personal identifiers)."""
    ctx: DbContext = session.info["ctx"]
    session.add(
        AuditLog(
            school_id=ctx.school_id,
            actor_user_id=actor_user_id or ctx.user_id,
            actor_platform_id=ctx.platform_admin_id,
            action=action,
            entity_type=entity_type,
            entity_id=entity_id,
            after_data=after,
            ip_address=ctx.client_ip,
            user_agent=(user_agent or "")[:255] or None,
            request_id=_uuid_or_none(ctx.request_id),
        )
    )


def _uuid_or_none(value: str | None) -> uuid.UUID | None:
    try:
        return uuid.UUID(value) if value else None
    except ValueError:
        return None
