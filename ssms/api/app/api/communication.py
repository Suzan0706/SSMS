"""/announcements (feed, optional SMS job), /notifications (inbox), /message-templates, /sms log and credit."""

import hashlib
import uuid
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, Header, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import Principal, active_principal, require_permission
from app.db.session import get_session
from app.models import Announcement, BackgroundJob
from app.schemas.communication import (
    AnnouncementCreated,
    AnnouncementIn,
    AnnouncementOut,
    CreditOut,
    InboxOut,
    SmsRow,
    TemplateIn,
    TemplateOut,
)
from app.services import communication as service
from app.services import crud, idempotency

router = APIRouter(tags=["communication"])
Session = Annotated[AsyncSession, Depends(get_session)]
Signed = Annotated[Principal, Depends(active_principal)]
Sender = Annotated[Principal, require_permission("announcements.send")]
Manager = Annotated[Principal, require_permission("sms.manage")]
SCOPE = "POST /announcements"


@router.get("/announcements", response_model=list[AnnouncementOut], summary="What the signed-in user may read")
async def feed(principal: Signed, session: Session):
    return await service.feed(session, principal)


@router.post(
    "/announcements",
    response_model=AnnouncementCreated,
    status_code=201,
    responses={422: {"description": "NO_SMS_CREDIT or audience fields that do not match"}},
    summary="Publish to the school, staff, parents, a class, a stream or one person; SMS optional "
    "(Idempotency-Key required with SMS)",
)
async def create(
    body: AnnouncementIn,
    principal: Sender,
    session: Session,
    idempotency_key: Annotated[str | None, Header(alias="Idempotency-Key")] = None,
):
    key = idempotency.require_key(idempotency_key) if body.send_sms else idempotency_key
    digest = hashlib.sha256(body.model_dump_json().encode()).hexdigest()
    if key:
        previous = await idempotency.replay(session, SCOPE, key, digest)
        if previous:
            item = await crud.get_live(session, Announcement, uuid.UUID(previous["announcement_id"]))
            job = previous.get("job_id")
            total = (
                (
                    await session.execute(select(BackgroundJob.total_items).where(BackgroundJob.id == uuid.UUID(job)))
                ).scalar()
                if job
                else 0
            )
            return AnnouncementCreated(**service.out(item).model_dump(), sms_job_id=job, sms_recipients=total or 0)
    created = await service.create(session, principal, body, key)
    if key:
        stored = {"announcement_id": str(created.id), "job_id": str(created.sms_job_id) if created.sms_job_id else None}
        idempotency.remember(session, principal, SCOPE, key, digest, 201, stored)
        await session.commit()
    return created


@router.delete("/announcements/{announcement_id}", status_code=204)
async def remove(announcement_id: uuid.UUID, _: Sender, session: Session):
    await service.remove(session, announcement_id)


@router.get("/notifications", response_model=InboxOut, summary="My inbox: unread first")
async def inbox(principal: Signed, session: Session):
    unread, items = await service.inbox(session, principal)
    return InboxOut(unread=unread, items=items)


@router.post("/notifications/{notification_id}/read", status_code=204)
async def read_one(notification_id: uuid.UUID, principal: Signed, session: Session):
    await service.mark_read(session, principal, notification_id)


@router.post("/notifications/read-all", status_code=204)
async def read_all(principal: Signed, session: Session):
    await service.mark_read(session, principal, None)


@router.get(
    "/message-templates", response_model=list[TemplateOut], summary="SMS texts in sw and en (defaults included)"
)
async def templates(_: Manager, session: Session):
    return await service.templates(session)


@router.put(
    "/message-templates/{key}/{language}",
    response_model=TemplateOut,
    responses={422: {"description": "bad_placeholder or sms_too_long (more than 3 SMS)"}},
)
async def save_template(
    key: str, language: Literal["sw", "en"], body: TemplateIn, principal: Manager, session: Session
):
    return await service.save_template(session, principal, key, language, body.body, body.is_active)


@router.get("/sms", response_model=list[SmsRow], summary="Latest SMS (numbers masked)")
async def sms_log(
    _: Manager,
    session: Session,
    status: Annotated[Literal["QUEUED", "SENT", "DELIVERED", "FAILED", "SKIPPED"] | None, Query()] = None,
):
    return await service.sms_log(session, status)


@router.get("/sms/credit", response_model=CreditOut, summary="Balance (low below 100) and top-ups/refunds")
async def credit(principal: Manager, session: Session):
    return await service.credit(session, principal.school_id)
