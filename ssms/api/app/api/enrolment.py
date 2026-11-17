"""Enrolment workflow (/enrolment, /enrolment-applications, /enrolment-documents, /enrolment-requirements)
and end-of-year promotions (/promotions)."""

import hashlib
import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, File, Form, Header, Query, Request, Response, UploadFile
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import Principal, active_principal, client_ip, request_context, require_permission
from app.api.imports import JobOut, job_out
from app.core.errors import AppError, forbidden
from app.core.files import read_limited
from app.core.pagination import Cursor, Limit, Page, paginate
from app.core.ratelimit import enforce
from app.db.session import get_session, set_context
from app.models import BackgroundJob, EnrolmentApplication, EnrolmentRequirement, Student, User
from app.models.enums import ApplicationStatus, JobKind, JobStatus
from app.schemas.enrolment import (
    ApplicationIn,
    ApplicationListItem,
    ApplicationOut,
    ApproveIn,
    DocumentDecisionIn,
    DocumentOut,
    OfferingsOut,
    PromotionIn,
    ReasonIn,
    RequirementIn,
    RequirementOut,
)
from app.services import crud, idempotency, promotions
from app.services import enrolment as service
from app.tasks.dispatch import get_dispatcher

router = APIRouter(tags=["enrolment"])
Session = Annotated[AsyncSession, Depends(get_session)]
Signed = Annotated[Principal, Depends(active_principal)]
Reason = Annotated[str, Query(min_length=3, max_length=300)]


# ---------------------------------------------------------------- public offerings


@router.get(
    "/enrolment/offerings",
    response_model=OfferingsOut,
    summary="Public: classes, combinations, places left and required documents (no sign-in)",
)
async def offerings(
    request: Request,
    session: Session,
    school_code: Annotated[str, Query(min_length=3, max_length=20)],
    year: uuid.UUID | None = None,
):
    await enforce(f"offerings:{client_ip(request)}", 60, 60)
    school_id = (await session.execute(select(func.resolve_school_by_code(school_code)))).scalar()
    if school_id is None:
        raise AppError(404, "SCHOOL_NOT_FOUND")
    await set_context(session, request_context(request, school_id))
    return await service.offerings(session, year)


# ---------------------------------------------------------------- requirements


@router.get("/enrolment-requirements", response_model=list[RequirementOut])
async def list_requirements(_: Signed, session: Session):
    return await crud.list_live(session, EnrolmentRequirement, EnrolmentRequirement.name_en)


@router.post("/enrolment-requirements", response_model=RequirementOut, status_code=201)
async def create_requirement(
    body: RequirementIn, principal: Annotated[Principal, require_permission("enrolment.manage")], session: Session
):
    return await crud.create(session, principal, EnrolmentRequirement, body.model_dump())


@router.delete("/enrolment-requirements/{requirement_id}", status_code=204)
async def delete_requirement(
    requirement_id: uuid.UUID,
    reason: Reason,
    _: Annotated[Principal, require_permission("enrolment.manage")],
    session: Session,
):
    await crud.soft_delete(session, EnrolmentRequirement, requirement_id, reason)
    return Response(status_code=204)


# ---------------------------------------------------------------- applications


@router.post(
    "/enrolment-applications",
    response_model=ApplicationOut,
    status_code=201,
    responses={409: {"description": "open application exists / enrolment closed"}},
    summary="Staff (enrolment.manage) or a signed-in parent registers an applicant",
)
async def create_application(body: ApplicationIn, principal: Signed, session: Session):
    application_id = await service.create(session, principal, body)
    return await service.out(session, await service.load(session, principal, application_id))


@router.get("/enrolment-applications", response_model=Page[ApplicationListItem])
async def list_applications(
    principal: Signed,
    session: Session,
    status: Annotated[ApplicationStatus | None, Query()] = None,
    class_id: uuid.UUID | None = None,
    limit: Limit = 50,
    cursor: Cursor = None,
):
    if not service.is_staff(principal):
        raise forbidden()
    stmt = (
        select(
            EnrolmentApplication.id,
            EnrolmentApplication.application_no,
            EnrolmentApplication.status,
            EnrolmentApplication.class_id,
            EnrolmentApplication.created_at,
            EnrolmentApplication.submitted_at,
            User.first_name,
            User.last_name,
        )
        .join(Student, Student.id == EnrolmentApplication.student_id)
        .join(User, User.id == Student.user_id)
        .where(EnrolmentApplication.deleted_at.is_(None))
    )
    if status:
        stmt = stmt.where(EnrolmentApplication.status == status)
    if class_id:
        stmt = stmt.where(EnrolmentApplication.class_id == class_id)
    rows, next_cursor = await paginate(
        session, stmt, [EnrolmentApplication.created_at, EnrolmentApplication.id], limit, cursor, descending=True
    )
    return Page[ApplicationListItem](
        items=[
            ApplicationListItem(
                id=r.id,
                application_no=r.application_no,
                status=r.status,
                class_id=r.class_id,
                created_at=r.created_at,
                submitted_at=r.submitted_at,
                student_name=f"{r.first_name} {r.last_name}",
            )
            for r in rows
        ],
        next_cursor=next_cursor,
    )


@router.get("/enrolment-applications/{application_id}", response_model=ApplicationOut)
async def get_application(application_id: uuid.UUID, principal: Signed, session: Session):
    return await service.out(session, await service.load(session, principal, application_id))


@router.post(
    "/enrolment-applications/{application_id}/documents",
    response_model=DocumentOut,
    status_code=201,
    responses={413: {"description": "FILE_TOO_LARGE (5 MB)"}, 422: {"description": "FILE_TYPE (PDF/JPG/PNG)"}},
)
async def upload_document(
    application_id: uuid.UUID,
    requirement_id: Annotated[uuid.UUID, Form()],
    file: Annotated[UploadFile, File()],
    principal: Signed,
    session: Session,
):
    if not (principal.has("enrolment.manage") or principal.has("portal.parent")):
        raise forbidden()
    data = await read_limited(file, service.MAX_DOCUMENT_BYTES)
    return await service.add_document(session, principal, application_id, requirement_id, file.filename or "", data)


@router.post(
    "/enrolment-applications/{application_id}/submit",
    response_model=ApplicationOut,
    responses={422: {"description": "required documents missing or invalid (listed in details)"}},
)
async def submit(application_id: uuid.UUID, principal: Signed, session: Session):
    return await service.out(session, await service.submit(session, principal, application_id))


@router.patch(
    "/enrolment-documents/{document_id}",
    response_model=ApplicationOut,
    summary="Mark a document VALID or INVALID (with a comment); INVALID sends the application back",
)
async def decide_document(
    document_id: uuid.UUID,
    body: DocumentDecisionIn,
    principal: Annotated[Principal, require_permission("enrolment.validate")],
    session: Session,
):
    return await service.out(session, await service.decide_document(session, principal, document_id, body))


@router.get("/enrolment-documents/{document_id}/download", response_class=Response)
async def download_document(document_id: uuid.UUID, principal: Signed, session: Session):
    document, data = await service.document_file(session, principal, document_id)
    return Response(
        data,
        media_type=document.mime_type,
        headers={"Content-Disposition": f'attachment; filename="{document.id}.{document.mime_type.split("/")[1]}"'},
    )


@router.post(
    "/enrolment-applications/{application_id}/approve",
    response_model=ApplicationOut,
    responses={409: {"description": "STREAM_FULL / not under review"}, 422: {"description": "documents_not_valid"}},
)
async def approve(
    application_id: uuid.UUID,
    body: ApproveIn,
    principal: Annotated[Principal, require_permission("enrolment.decide")],
    session: Session,
):
    application, call = await service.approve(
        session, principal, application_id, body.stream_id, body.combination_id, body.note
    )
    if call:
        get_dispatcher().send("sms.send", **call)
    return await service.out(session, application)


@router.post("/enrolment-applications/{application_id}/reject", response_model=ApplicationOut)
async def reject(
    application_id: uuid.UUID,
    body: ReasonIn,
    principal: Annotated[Principal, require_permission("enrolment.decide")],
    session: Session,
):
    return await service.out(
        session, await service.close(session, principal, application_id, ApplicationStatus.REJECTED, body.reason)
    )


@router.post(
    "/enrolment-applications/{application_id}/cancel",
    response_model=ApplicationOut,
    summary="Cancel: enrolment staff, or the parent who applied",
)
async def cancel(application_id: uuid.UUID, body: ReasonIn, principal: Signed, session: Session):
    if not (principal.has("enrolment.manage") or principal.has("portal.parent")):
        raise forbidden()
    return await service.out(
        session, await service.close(session, principal, application_id, ApplicationStatus.CANCELLED, body.reason)
    )


# ---------------------------------------------------------------- promotions


@router.post(
    "/promotions",
    response_model=JobOut,
    status_code=202,
    summary="Promote, repeat or graduate every active enrolment of a year (all-or-nothing job)",
)
async def promote(
    body: PromotionIn,
    principal: Annotated[Principal, require_permission("students.status")],
    session: Session,
    idempotency_key: Annotated[str | None, Header(alias="Idempotency-Key")] = None,
):
    key = idempotency.require_key(idempotency_key)
    digest = hashlib.sha256(body.model_dump_json().encode()).hexdigest()
    previous = await idempotency.replay(session, "POST /promotions", key, digest)
    if previous:
        return job_out(await crud.get_live(session, BackgroundJob, uuid.UUID(previous["job_id"])))
    job = BackgroundJob(
        school_id=principal.school_id,
        kind=JobKind.PROMOTION,
        status=JobStatus.QUEUED,
        idempotency_key=key,
        requested_by=principal.user_id,
        created_by=principal.user_id,
    )
    promotions.store_params(principal, job, body)
    session.add(job)
    idempotency.remember(session, principal, "POST /promotions", key, digest, 202, {"job_id": str(job.id)})
    await session.commit()
    get_dispatcher().send("promotions.run", job_id=str(job.id), school_id=str(principal.school_id))
    return job_out(job)
