"""/materials, /homework, lesson attendance and the monthly attendance sheet (FR-82, FR-83, FR-90 .. FR-93)."""

import uuid
from datetime import date
from typing import Annotated
from urllib.parse import quote

from fastapi import APIRouter, Depends, Query, Response, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import Principal, active_principal, require_permission
from app.core.errors import forbidden
from app.db.session import get_session
from app.schemas.teaching import (
    HomeworkIn,
    HomeworkOut,
    LessonIn,
    LessonMarkRow,
    LessonOut,
    MarkIn,
    MaterialIn,
    MaterialOut,
    MonthlySheet,
    MySubmission,
    RosterRow,
    StudentHomework,
    SubmissionIn,
)
from app.services import teaching as service
from app.tasks.dispatch import get_dispatcher

router = APIRouter(tags=["teaching"])
Session = Annotated[AsyncSession, Depends(get_session)]
Signed = Annotated[Principal, Depends(active_principal)]
Publisher = Annotated[Principal, require_permission("materials.publish", "academics.configure")]
Setter = Annotated[Principal, require_permission("homework.manage", "academics.configure")]
Taker = Annotated[Principal, require_permission("attendance.take")]
Reader = Annotated[Principal, require_permission("attendance.read")]


def _file(upload, data: bytes) -> Response:
    disposition = "inline" if upload.content_type.startswith("image/") else "attachment"
    return Response(
        data,
        media_type=upload.content_type,
        headers={
            "Content-Disposition": f"{disposition}; filename*=UTF-8''{quote(upload.original_name)}",
            "Cache-Control": "private, no-store",
        },
    )


# ---------------------------------------------------------------- study materials


@router.post("/materials", status_code=status.HTTP_201_CREATED, summary="Publish a file or link to streams")
async def publish_material(body: MaterialIn, principal: Publisher, session: Session) -> dict:
    return {"id": await service.publish_material(session, principal, body)}


@router.get("/materials", response_model=list[MaterialOut], summary="This year's materials (staff)")
async def list_materials(
    principal: Annotated[Principal, require_permission("materials.publish", "academics.configure", "students.read")],
    session: Session,
    stream_id: uuid.UUID | None = None,
    subject_id: uuid.UUID | None = None,
):
    return await service.list_materials(session, principal, stream_id=stream_id, subject_id=subject_id)


@router.get(
    "/materials/mine", response_model=list[MaterialOut], summary="Materials for a student or a parent's children"
)
async def my_materials(principal: Signed, session: Session):
    return await service.my_materials(session, principal)


@router.get(
    "/materials/{material_id}/file",
    response_class=Response,
    responses={200: {"content": {"application/octet-stream": {}}}},
)
async def material_file(material_id: uuid.UUID, principal: Signed, session: Session):
    return _file(*await service.material_file(session, principal, material_id))


@router.delete("/materials/{material_id}", status_code=status.HTTP_204_NO_CONTENT)
async def remove_material(material_id: uuid.UUID, principal: Publisher, session: Session):
    await service.remove_material(session, principal, material_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


# ---------------------------------------------------------------- homework


@router.post("/homework", status_code=status.HTTP_201_CREATED, summary="Set homework (optionally SMS the parents)")
async def set_homework(body: HomeworkIn, principal: Setter, session: Session) -> dict:
    homework_id, calls = await service.set_homework(session, principal, body)
    for call in calls:
        get_dispatcher().send("sms.send", **call)
    return {"id": homework_id, "sms_queued": len(calls)}


@router.get("/homework", response_model=list[HomeworkOut], summary="Homework you set, or all with academics.configure")
async def list_homework(principal: Setter, session: Session, everyone: bool = False):
    if everyone and not principal.has("academics.configure"):
        raise forbidden()
    return await service.list_homework(session, principal, everyone=everyone)


@router.get(
    "/homework/mine", response_model=list[StudentHomework], summary="Homework for a student or a parent's children"
)
async def my_homework(principal: Signed, session: Session):
    return await service.my_homework(session, principal)


@router.get(
    "/homework/{homework_id}/submissions", response_model=list[RosterRow], summary="Every student, submitted or not"
)
async def roster(homework_id: uuid.UUID, principal: Setter, session: Session):
    return await service.roster(session, principal, homework_id)


@router.put(
    "/homework/{homework_id}/submission",
    response_model=MySubmission,
    summary="Hand in (or replace before the deadline)",
)
async def submit(homework_id: uuid.UUID, body: SubmissionIn, principal: Signed, session: Session):
    if not principal.has("homework.submit"):
        raise forbidden()
    return await service.submit(session, principal, homework_id, body)


@router.patch("/homework/submissions/{submission_id}", response_model=MySubmission, summary="Score and feedback")
async def mark(submission_id: uuid.UUID, body: MarkIn, principal: Setter, session: Session):
    return await service.mark(session, principal, submission_id, body)


@router.get(
    "/homework/{homework_id}/file",
    response_class=Response,
    responses={200: {"content": {"application/octet-stream": {}}}},
)
async def homework_file(homework_id: uuid.UUID, principal: Signed, session: Session):
    return _file(*await service.homework_file(session, principal, homework_id))


@router.get(
    "/homework/submissions/{submission_id}/file",
    response_class=Response,
    responses={200: {"content": {"application/octet-stream": {}}}},
)
async def submission_file(submission_id: uuid.UUID, principal: Signed, session: Session):
    return _file(*await service.submission_file(session, principal, submission_id))


@router.delete("/homework/{homework_id}", status_code=status.HTTP_204_NO_CONTENT)
async def remove_homework(homework_id: uuid.UUID, principal: Setter, session: Session):
    await service.remove_homework(session, principal, homework_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


# ---------------------------------------------------------------- lesson attendance and the monthly sheet


@router.get(
    "/attendance/lessons", response_model=list[LessonOut], summary="Your lessons on a day, with how many are marked"
)
async def my_lessons(on: date, principal: Taker, session: Session):
    return await service.my_lessons(session, principal, on)


@router.get("/attendance/lessons/{slot_id}", response_model=list[LessonMarkRow], summary="A lesson's register")
async def lesson_register(slot_id: uuid.UUID, on: date, principal: Taker, session: Session):
    return await service.lesson_register(session, principal, slot_id, on)


@router.put(
    "/attendance/lessons/{slot_id}", status_code=status.HTTP_204_NO_CONTENT, summary="Record or correct a lesson"
)
async def save_lesson(slot_id: uuid.UUID, on: date, body: LessonIn, principal: Taker, session: Session):
    await service.save_lesson(session, principal, slot_id, on, body)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get("/attendance/monthly-sheet", response_model=MonthlySheet, summary="Days × students from the class register")
async def monthly_sheet(
    stream_id: uuid.UUID,
    year: Annotated[int, Query(ge=2000, le=2100)],
    month: Annotated[int, Query(ge=1, le=12)],
    _: Reader,
    session: Session,
):
    return await service.monthly_sheet(session, stream_id, year, month)
