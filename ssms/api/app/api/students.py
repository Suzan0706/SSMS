"""/students, their guardians, status changes and identifiers; /guardians/{id}/consents."""

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, Query, Response, status
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import Principal, require_permission
from app.core.errors import AppError, not_found
from app.core.pagination import Cursor, Limit, Page
from app.core.storage import get_storage
from app.db.session import get_session
from app.models import StoredFile, Student
from app.models.enums import FilePurpose, StudentStatus
from app.schemas.people import (
    ConsentIn,
    ConsentOut,
    GuardianLinkIn,
    GuardianOut,
    IdentifiersOut,
    StatusChangeIn,
    StatusHistoryOut,
    StudentCreateIn,
    StudentListItem,
    StudentOut,
    StudentUpdateIn,
)
from app.services import crud, files
from app.services import students as service

router = APIRouter(tags=["students"])
Reason = Annotated[str, Query(min_length=3, max_length=300, description="Why the link is removed (audited)")]


@router.get(
    "/students",
    response_model=Page[StudentListItem],
    summary="Search by name or admission number; filter by class, stream, status",
)
async def list_students(
    q: Annotated[str | None, Query(max_length=50)] = None,
    class_id: uuid.UUID | None = None,
    stream_id: uuid.UUID | None = None,
    status_filter: Annotated[StudentStatus | None, Query(alias="status")] = None,
    limit: Limit = 50,
    cursor: Cursor = None,
    _: Principal = require_permission("students.read"),
    session: AsyncSession = Depends(get_session),
):
    items, next_cursor = await service.list_page(
        session, q=q, class_id=class_id, stream_id=stream_id, status=status_filter, limit=limit, cursor=cursor
    )
    return Page[StudentListItem](items=items, next_cursor=next_cursor)


@router.post(
    "/students",
    response_model=StudentOut,
    status_code=status.HTTP_201_CREATED,
    responses={
        409: {"description": "DUPLICATE birth certificate / STREAM_FULL"},
        422: {"description": "VALIDATION_ERROR / ONE_PRIMARY_GUARDIAN"},
    },
    summary="Admit (with stream_id) or register an applicant; guardians are reused by phone",
)
async def create_student(
    body: StudentCreateIn,
    principal: Principal = require_permission("students.create"),
    session: AsyncSession = Depends(get_session),
):
    student_id = await service.admit(session, principal, body)
    return await service.get(session, principal, student_id)


@router.get("/students/{student_id}", response_model=StudentOut)
async def get_student(
    student_id: uuid.UUID,
    principal: Principal = require_permission("students.read"),
    session: AsyncSession = Depends(get_session),
):
    return await service.get(session, principal, student_id)


@router.patch("/students/{student_id}", response_model=StudentOut)
async def update_student(
    student_id: uuid.UUID,
    body: StudentUpdateIn,
    principal: Principal = require_permission("students.update"),
    session: AsyncSession = Depends(get_session),
):
    await service.update_student(session, principal, student_id, body)
    return await service.get(session, principal, student_id)


@router.post(
    "/students/{student_id}/status",
    response_model=StatusHistoryOut,
    responses={409: {"description": "STATUS_TRANSITION"}},
    summary="Suspend, transfer, graduate, drop out or re-admit; leaving ends the enrolment",
)
async def change_status(
    student_id: uuid.UUID,
    body: StatusChangeIn,
    principal: Principal = require_permission("students.status"),
    session: AsyncSession = Depends(get_session),
):
    return await service.change_status(session, principal, student_id, body)


@router.get(
    "/students/{student_id}/identifiers",
    response_model=IdentifiersOut,
    summary="Birth certificate and NIDA numbers in clear (audited VIEW_SENSITIVE)",
)
async def identifiers(
    student_id: uuid.UUID,
    _: Principal = require_permission("students.update"),
    session: AsyncSession = Depends(get_session),
):
    return await service.identifiers(session, student_id)


@router.get("/students/{student_id}/guardians", response_model=list[GuardianOut])
async def list_guardians(
    student_id: uuid.UUID,
    principal: Principal = require_permission("students.read"),
    session: AsyncSession = Depends(get_session),
):
    await service.get(session, principal, student_id)  # 404 when not in this school
    return await service.guardians_of(session, principal, student_id)


@router.post("/students/{student_id}/guardians", response_model=list[GuardianOut], status_code=status.HTTP_201_CREATED)
async def add_guardian(
    student_id: uuid.UUID,
    body: GuardianLinkIn,
    principal: Principal = require_permission("guardians.manage"),
    session: AsyncSession = Depends(get_session),
):
    await service.get(session, principal, student_id)
    await service.link_guardian(session, principal, student_id, body)
    await session.commit()
    return await service.guardians_of(session, principal, student_id)


@router.delete(
    "/students/{student_id}/guardians/{guardian_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    responses={409: {"description": "ONE_PRIMARY_GUARDIAN"}},
)
async def remove_guardian(
    student_id: uuid.UUID,
    guardian_id: uuid.UUID,
    reason: Reason,
    principal: Principal = require_permission("guardians.manage"),
    session: AsyncSession = Depends(get_session),
):
    await service.unlink_guardian(session, principal, student_id, guardian_id, reason)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get("/guardians/{guardian_id}/consents", response_model=list[ConsentOut], tags=["privacy"])
async def list_consents(
    guardian_id: uuid.UUID,
    _: Principal = require_permission("guardians.manage"),
    session: AsyncSession = Depends(get_session),
):
    return await service.consents_of(session, guardian_id)


@router.post(
    "/guardians/{guardian_id}/consents",
    response_model=ConsentOut,
    status_code=status.HTTP_201_CREATED,
    tags=["privacy"],
    summary="Record or withdraw consent (withdrawing SMS consent stops SMS at once)",
)
async def record_consent(
    guardian_id: uuid.UUID,
    body: ConsentIn,
    principal: Principal = require_permission("guardians.manage"),
    session: AsyncSession = Depends(get_session),
):
    return await service.record_consent(session, principal, guardian_id, body)


class PhotoIn(BaseModel):
    file_id: uuid.UUID = Field(description="A PHOTO uploaded with POST /files")


@router.put("/students/{student_id}/photo", status_code=status.HTTP_204_NO_CONTENT, summary="Set the photograph")
async def set_photo(
    student_id: uuid.UUID,
    body: PhotoIn,
    principal: Principal = require_permission("students.update"),
    session: AsyncSession = Depends(get_session),
):
    upload = await files.get(session, body.file_id)
    if upload.purpose != FilePurpose.PHOTO or not files.may_read(upload, principal):
        raise AppError(422, "VALIDATION_ERROR", [{"field": "file_id", "code": "invalid_value"}])
    student = await crud.get_live(session, Student, student_id, lock=True)
    student.photo_file_key = upload.storage_key
    await session.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get(
    "/students/{student_id}/photo",
    response_class=Response,
    responses={200: {"content": {"image/jpeg": {}, "image/png": {}}}, 404: {"description": "No photograph"}},
)
async def get_photo(
    student_id: uuid.UUID,
    principal: Principal = require_permission("students.read"),
    session: AsyncSession = Depends(get_session),
):
    student = await crud.get_live(session, Student, student_id)
    if not student.photo_file_key:
        raise not_found()
    upload = (
        await session.execute(
            select(StoredFile).where(StoredFile.storage_key == student.photo_file_key, StoredFile.deleted_at.is_(None))
        )
    ).scalar_one_or_none()
    if upload is None:
        raise not_found()
    return Response(
        get_storage().get(upload.storage_key),
        media_type=upload.content_type,
        headers={"Cache-Control": "private, max-age=300"},
    )


@router.delete("/students/{student_id}/photo", status_code=status.HTTP_204_NO_CONTENT)
async def remove_photo(
    student_id: uuid.UUID,
    principal: Principal = require_permission("students.update"),
    session: AsyncSession = Depends(get_session),
):
    student = await crud.get_live(session, Student, student_id, lock=True)
    student.photo_file_key = None
    await session.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)
