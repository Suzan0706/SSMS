"""Idempotency-Key handling (stored 24 h in idempotency_keys, per school).

Same key + same request -> the stored response is returned again. Same key + different request ->
422 IDEMPOTENCY_MISMATCH. The caller stores the response in the same transaction as the work it describes.
"""

from datetime import UTC, datetime, timedelta

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import Principal
from app.core.errors import AppError
from app.models import IdempotencyKey

TTL = timedelta(hours=24)


def require_key(key: str | None) -> str:
    if not key or not 8 <= len(key) <= 80:
        raise AppError(422, "IDEMPOTENCY_KEY_REQUIRED", [{"field": "Idempotency-Key", "code": "required"}])
    return key


async def replay(session: AsyncSession, scope: str, key: str, request_hash: str) -> dict | None:
    """The stored response body for this key, or None when the request is new."""
    row = (
        await session.execute(
            select(IdempotencyKey).where(IdempotencyKey.scope == scope, IdempotencyKey.key == key).with_for_update()
        )
    ).scalar_one_or_none()
    if row is None:
        return None
    if row.expires_at <= datetime.now(UTC):
        await session.execute(delete(IdempotencyKey).where(IdempotencyKey.id == row.id))
        await session.flush()
        return None
    if row.request_hash != request_hash:
        raise AppError(422, "IDEMPOTENCY_MISMATCH")
    return row.response_body


def remember(
    session: AsyncSession, principal: Principal, scope: str, key: str, request_hash: str, status: int, body: dict
) -> None:
    session.add(
        IdempotencyKey(
            school_id=principal.school_id,
            scope=scope,
            key=key,
            request_hash=request_hash,
            response_status=status,
            response_body=body,
            expires_at=datetime.now(UTC) + TTL,
            created_by=principal.user_id,
        )
    )
