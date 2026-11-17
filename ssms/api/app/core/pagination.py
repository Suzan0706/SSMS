"""Keyset (cursor) pagination: ?limit=50 (max 50)&cursor=<opaque> -> {"items": [...], "next_cursor": ...}.

The cursor holds the sort key of the last row returned, so page N costs the same as page 1 (no OFFSET).
The sort key must end with a unique column (id) so that ties are broken deterministically.
"""

import base64
import json
import uuid
from datetime import date, datetime
from typing import Annotated, Any, Generic, TypeVar

from fastapi import Query
from pydantic import BaseModel
from sqlalchemy import Select, tuple_
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import AppError

T = TypeVar("T")
DEFAULT_LIMIT, MAX_LIMIT = 50, 50

Limit = Annotated[int, Query(ge=1, le=MAX_LIMIT, description="Page size (default and max 50)")]
Cursor = Annotated[str | None, Query(max_length=500, description="`next_cursor` of the previous page")]


class Page(BaseModel, Generic[T]):
    items: list[T]
    next_cursor: str | None = None


def encode_cursor(values: list[Any]) -> str:
    raw = json.dumps([v.isoformat() if isinstance(v, date | datetime) else str(v) for v in values])
    return base64.urlsafe_b64encode(raw.encode()).decode().rstrip("=")


def _decode(cursor: str, columns) -> list[Any]:
    try:
        values = json.loads(base64.urlsafe_b64decode(cursor + "=" * (-len(cursor) % 4)))
        if not isinstance(values, list) or len(values) != len(columns):
            raise ValueError
        out = []
        for value, column in zip(values, columns, strict=True):
            try:
                kind = column.type.python_type
            except NotImplementedError:
                kind = str
            if kind is object:  # untyped SQL expression: compare as text
                kind = str
            out.append(
                uuid.UUID(value)
                if kind is uuid.UUID
                else datetime.fromisoformat(value)
                if kind is datetime
                else date.fromisoformat(value)
                if kind is date
                else kind(value)
            )
        return out
    except (ValueError, TypeError, json.JSONDecodeError, NotImplementedError):
        raise AppError(422, "VALIDATION_ERROR", [{"field": "cursor", "code": "invalid_value"}]) from None


async def paginate(
    session: AsyncSession, stmt: Select, keys: list, limit: int, cursor: str | None, descending: bool = False
) -> tuple[list, str | None]:
    """Run `stmt` ordered by `keys` (all ascending, or all descending for newest-first lists).
    Each selected row must expose the key columns by name."""
    if cursor:
        position = tuple_(*_decode(cursor, keys))
        stmt = stmt.where(tuple_(*keys) < position if descending else tuple_(*keys) > position)
    order = [k.desc() for k in keys] if descending else keys
    rows = (await session.execute(stmt.order_by(*order).limit(limit + 1))).all()
    if len(rows) <= limit:
        return rows, None
    rows = rows[:limit]
    last = rows[-1]
    return rows, encode_cursor([getattr(last, k.key) for k in keys])
