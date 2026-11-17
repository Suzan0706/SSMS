"""Generic create / read / update / soft-delete for simple tenant tables (caller's school context, RLS)."""

import uuid
from collections.abc import Iterable

from sqlalchemy import Select, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import Principal
from app.core.errors import AppError, not_found
from app.services import audit
from app.services.people import now


async def get_live(session: AsyncSession, model, item_id: uuid.UUID, lock: bool = False):
    stmt = select(model).where(model.id == item_id)
    if hasattr(model, "deleted_at"):
        stmt = stmt.where(model.deleted_at.is_(None))
    item = (await session.execute(stmt.with_for_update() if lock else stmt)).scalar_one_or_none()
    if item is None:
        raise not_found()
    return item


async def list_live(session: AsyncSession, model, *order_by, where: Iterable = (), limit: int = 200) -> list:
    stmt = select(model).where(*where)
    if hasattr(model, "deleted_at"):
        stmt = stmt.where(model.deleted_at.is_(None))
    return list((await session.execute(stmt.order_by(*order_by).limit(limit))).scalars())


async def create(session: AsyncSession, principal: Principal, model, data: dict, commit: bool = True):
    item = model(school_id=principal.school_id, created_by=principal.user_id, **data)
    session.add(item)
    if commit:
        await session.commit()
    else:
        await session.flush()
    return item


async def update(session: AsyncSession, model, item_id: uuid.UUID, data: dict, commit: bool = True):
    item = await get_live(session, model, item_id, lock=True)
    for field, value in data.items():
        setattr(item, field, value)
    if commit:
        await session.commit()
    else:
        await session.flush()
    return item


async def soft_delete(
    session: AsyncSession, model, item_id: uuid.UUID, reason: str, blockers: Iterable[Select] = ()
) -> None:
    """Soft delete with an audited reason. Each blocker is a SELECT that returns a row when the item is in use."""
    item = await get_live(session, model, item_id, lock=True)
    for stmt in blockers:
        if (await session.execute(stmt.limit(1))).first():
            raise AppError(409, "NOT_ALLOWED", [{"field": "id", "code": "in_use"}])
    item.deleted_at = now()
    await audit.record(session, "DELETE", model.__tablename__, item.id, {"reason": reason})
    await session.commit()


async def flush_checked(session: AsyncSession, field: str, full_code: str) -> None:
    """Flush, turning the database's capacity guard into 422 FULL (detail `full_code`) and a unique clash into 409
    DUPLICATE, both with the field the caller names."""
    try:
        await session.flush()
    except IntegrityError as exc:
        state = getattr(exc.orig, "sqlstate", None)
        if state == "23514" and "is full" in str(exc.orig):
            raise AppError(422, "FULL", [{"field": field, "code": full_code}]) from None
        if state == "23505":
            raise AppError(409, "DUPLICATE", [{"field": field, "code": "duplicate_in_school"}]) from None
        raise
