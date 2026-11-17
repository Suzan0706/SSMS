"""/users: accounts, status, password reset, roles."""

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, Query, Response, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import Principal, require_permission
from app.core.pagination import Cursor, Limit, Page
from app.db.session import get_session
from app.schemas.people import RoleIn, TemporaryPasswordOut, UserListItem, UserUpdateIn
from app.services import staff as service
from app.tasks.dispatch import get_dispatcher

router = APIRouter(prefix="/users", tags=["users"])


@router.get("", response_model=Page[UserListItem], summary="User accounts (phones masked without guardians.manage)")
async def list_users(
    q: Annotated[str | None, Query(max_length=50)] = None,
    role: Annotated[str | None, Query(pattern=r"^[a-z_]{3,30}$")] = None,
    status_filter: Annotated[str | None, Query(alias="status", pattern=r"^[A-Z_]{4,10}$")] = None,
    limit: Limit = 50,
    cursor: Cursor = None,
    principal: Principal = require_permission("users.read"),
    session: AsyncSession = Depends(get_session),
):
    items, next_cursor = await service.list_users(
        session, principal, q=q, role=role, status=status_filter, limit=limit, cursor=cursor
    )
    return Page[UserListItem](items=items, next_cursor=next_cursor)


@router.patch(
    "/{user_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Enable or disable an account, or change its language (disabling signs it out)",
)
async def update_user(
    user_id: uuid.UUID,
    body: UserUpdateIn,
    principal: Principal = require_permission("users.manage"),
    session: AsyncSession = Depends(get_session),
):
    await service.update_user(session, principal, user_id, body)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post(
    "/{user_id}/reset-password",
    response_model=TemporaryPasswordOut,
    summary="New temporary password (shown once, also sent by SMS); unlocks the account",
)
async def reset_password(
    user_id: uuid.UUID,
    principal: Principal = require_permission("users.manage"),
    session: AsyncSession = Depends(get_session),
):
    password, call = await service.reset_password(session, principal, user_id)
    if call:
        get_dispatcher().send("sms.send", **call)
    return TemporaryPasswordOut(temporary_password=password)


@router.post(
    "/{user_id}/roles",
    response_model=list[str],
    status_code=status.HTTP_201_CREATED,
    responses={409: {"description": "DUPLICATE: role already held"}},
)
async def add_role(
    user_id: uuid.UUID,
    body: RoleIn,
    principal: Principal = require_permission("roles.assign"),
    session: AsyncSession = Depends(get_session),
):
    return await service.add_role(session, principal, user_id, body.role_code)


@router.delete("/{user_id}/roles/{role_code}", status_code=status.HTTP_204_NO_CONTENT)
async def remove_role(
    user_id: uuid.UUID,
    role_code: str,
    principal: Principal = require_permission("roles.assign"),
    session: AsyncSession = Depends(get_session),
):
    await service.remove_role(session, principal, user_id, role_code)
    return Response(status_code=status.HTTP_204_NO_CONTENT)
