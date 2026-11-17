"""/teaching-assignments, /timetable (slots, live check, generator) and /exam-sessions, /exams."""

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, Header, Query, Response
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import Principal, active_principal, require_permission
from app.core.errors import AppError
from app.db.session import get_session
from app.models import Exam, ExamSession, Term, TimetableSlot
from app.schemas.timetable import (
    AssignmentItem,
    AssignmentOut,
    CheckOut,
    ExamIn,
    ExamOut,
    ExamSessionIn,
    ExamSessionOut,
    ExamSessionUpdate,
    ExamUpdate,
    GenerateIn,
    GenerateOut,
    SlotCheckIn,
    SlotIn,
    SlotOut,
    SlotUpdate,
)
from app.services import crud
from app.services import timetable as service

router = APIRouter()
Session = Annotated[AsyncSession, Depends(get_session)]
Reason = Annotated[str, Query(min_length=3, max_length=300)]
TimetableReader = Annotated[Principal, require_permission("timetable.read", "timetable.manage")]
TimetableManager = Annotated[Principal, require_permission("timetable.manage")]
ExamReader = Annotated[Principal, require_permission("exams.read", "exams.manage")]
ExamManager = Annotated[Principal, require_permission("exams.manage")]


def _outside(field: str, code: str) -> AppError:
    return AppError(422, "VALIDATION_ERROR", [{"field": field, "code": code}])


# ---------------------------------------------------------------- teaching assignments


@router.get(
    "/teaching-assignments",
    response_model=list[AssignmentOut],
    tags=["timetable"],
    summary="Who teaches what; mine=true lists the caller's own classes (any teacher)",
)
async def list_assignments(
    academic_year_id: uuid.UUID,
    session: Session,
    principal: Annotated[Principal, Depends(active_principal)],
    stream_id: uuid.UUID | None = None,
    staff_id: uuid.UUID | None = None,
    mine: bool = False,
):
    readers = ("staff.read", "staff.manage", "timetable.read", "timetable.manage")
    if not (mine and principal.has("marks.enter")) and not any(principal.has(p) for p in readers):
        raise AppError(403, "FORBIDDEN")
    return await service.list_assignments(
        session, academic_year_id, stream_id, staff_id, principal.user_id if mine else None
    )


@router.put(
    "/teaching-assignments",
    response_model=list[AssignmentOut],
    tags=["timetable"],
    summary="Replace who teaches each subject in one stream for a year",
)
async def put_assignments(
    academic_year_id: uuid.UUID,
    stream_id: uuid.UUID,
    body: list[AssignmentItem],
    principal: Annotated[Principal, require_permission("staff.manage")],
    session: Session,
):
    return await service.replace_assignments(session, principal, academic_year_id, stream_id, body)


# ---------------------------------------------------------------- timetable


@router.get(
    "/timetable",
    response_model=list[SlotOut],
    tags=["timetable"],
    responses={304: {"description": "unchanged (If-None-Match)"}},
    summary="Slots of a term, filtered by stream, teacher or room; ETag for cheap re-checks",
)
async def get_timetable(
    term_id: uuid.UUID,
    principal: TimetableReader,
    session: Session,
    response: Response,
    stream_id: uuid.UUID | None = None,
    staff_id: uuid.UUID | None = None,
    room_id: uuid.UUID | None = None,
    if_none_match: Annotated[str | None, Header(alias="If-None-Match")] = None,
):
    slots = await service.list_slots(session, term_id, stream_id, staff_id, room_id)
    etag = service.etag_of(slots)
    if if_none_match == etag:
        return Response(status_code=304, headers={"ETag": etag})
    response.headers["ETag"] = etag
    response.headers["Cache-Control"] = "private, no-cache"
    return slots


@router.post(
    "/timetable/check",
    response_model=CheckOut,
    tags=["timetable"],
    summary="Live check while typing: clashes, rule problems and free periods that day",
)
async def check(body: SlotCheckIn, _: TimetableManager, session: Session):
    return await service.check(session, body)


@router.post(
    "/timetable/slots",
    response_model=SlotOut,
    status_code=201,
    tags=["timetable"],
    responses={409: {"description": "TIMETABLE_CLASH"}, 422: {"description": "RULE_VIOLATION (problems)"}},
)
async def create_slot(body: SlotIn, principal: TimetableManager, session: Session):
    return await service.create_slot(session, principal, body)


@router.patch("/timetable/slots/{slot_id}", response_model=SlotOut, tags=["timetable"])
async def update_slot(slot_id: uuid.UUID, body: SlotUpdate, _: TimetableManager, session: Session):
    return await service.update_slot(session, slot_id, body)


@router.delete("/timetable/slots/{slot_id}", status_code=204, tags=["timetable"])
async def delete_slot(slot_id: uuid.UUID, reason: Reason, _: TimetableManager, session: Session):
    await crud.soft_delete(session, TimetableSlot, slot_id, reason)
    return Response(status_code=204)


@router.post(
    "/timetable/generate",
    response_model=GenerateOut,
    tags=["timetable"],
    summary="Draft (persist=false) or save (persist=true) a timetable for streams of a term",
)
async def generate(body: GenerateIn, principal: TimetableManager, session: Session):
    return await service.generate(session, principal, body)


# ---------------------------------------------------------------- exams


@router.get("/exam-sessions", response_model=list[ExamSessionOut], tags=["exams"])
async def list_sessions(_: ExamReader, session: Session, term_id: uuid.UUID | None = None):
    where = [ExamSession.term_id == term_id] if term_id else []
    return await crud.list_live(session, ExamSession, ExamSession.start_date.desc(), where=where, limit=100)


async def _check_session_dates(session: AsyncSession, term_id: uuid.UUID, start, end) -> None:
    term = await crud.get_live(session, Term, term_id)
    if start < term.start_date or end > term.end_date:
        raise _outside("start_date", "outside_term")


@router.post("/exam-sessions", response_model=ExamSessionOut, status_code=201, tags=["exams"])
async def create_session(body: ExamSessionIn, principal: ExamManager, session: Session):
    await _check_session_dates(session, body.term_id, body.start_date, body.end_date)
    return await crud.create(session, principal, ExamSession, body.model_dump())


@router.patch("/exam-sessions/{session_id}", response_model=ExamSessionOut, tags=["exams"])
async def update_session(session_id: uuid.UUID, body: ExamSessionUpdate, _: ExamManager, session: Session):
    current = await crud.get_live(session, ExamSession, session_id)
    data = body.model_dump(exclude_unset=True)
    start, end = data.get("start_date", current.start_date), data.get("end_date", current.end_date)
    if end < start:
        raise _outside("end_date", "invalid_value")
    await _check_session_dates(session, current.term_id, start, end)
    return await crud.update(session, ExamSession, session_id, data)


@router.delete("/exam-sessions/{session_id}", status_code=204, tags=["exams"])
async def delete_session(session_id: uuid.UUID, reason: Reason, _: ExamManager, session: Session):
    await crud.soft_delete(
        session,
        ExamSession,
        session_id,
        reason,
        blockers=[select(Exam.id).where(Exam.exam_session_id == session_id, Exam.deleted_at.is_(None))],
    )
    return Response(status_code=204)


@router.get("/exams", response_model=list[ExamOut], tags=["exams"], summary="Papers of a session (or a class)")
async def list_exams(
    _: ExamReader, session: Session, exam_session_id: uuid.UUID | None = None, class_id: uuid.UUID | None = None
):
    where = [
        c
        for c in (
            (Exam.exam_session_id == exam_session_id) if exam_session_id else None,
            (Exam.class_id == class_id) if class_id else None,
        )
        if c is not None
    ]
    return await crud.list_live(session, Exam, Exam.exam_date, Exam.time_start, where=where, limit=300)


async def _check_exam_date(session: AsyncSession, session_id: uuid.UUID, exam_date) -> None:
    exam_session = await crud.get_live(session, ExamSession, session_id)
    if not exam_session.start_date <= exam_date <= exam_session.end_date:
        raise _outside("exam_date", "outside_session")


@router.post(
    "/exams",
    response_model=ExamOut,
    status_code=201,
    tags=["exams"],
    responses={409: {"description": "the class or the room already has a paper at that time"}},
)
async def create_exam(body: ExamIn, principal: ExamManager, session: Session):
    await _check_exam_date(session, body.exam_session_id, body.exam_date)
    return await crud.create(session, principal, Exam, body.model_dump())


@router.patch("/exams/{exam_id}", response_model=ExamOut, tags=["exams"])
async def update_exam(exam_id: uuid.UUID, body: ExamUpdate, _: ExamManager, session: Session):
    current = await crud.get_live(session, Exam, exam_id)
    data = body.model_dump(exclude_unset=True)
    if "exam_date" in data:
        await _check_exam_date(session, current.exam_session_id, data["exam_date"])
    start, end = data.get("time_start", current.time_start), data.get("time_end", current.time_end)
    if end <= start:
        raise _outside("time_end", "invalid_value")
    return await crud.update(session, Exam, exam_id, data)


@router.delete("/exams/{exam_id}", status_code=204, tags=["exams"])
async def delete_exam(exam_id: uuid.UUID, reason: Reason, _: ExamManager, session: Session):
    await crud.soft_delete(session, Exam, exam_id, reason)
    return Response(status_code=204)
