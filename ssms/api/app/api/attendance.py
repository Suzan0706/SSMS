"""/attendance: registers (ETag, offline sync, close), reports (+ Excel), chronic absence; a student's days."""

import hashlib
import uuid
from datetime import date
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, Header, Query, Response
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import Principal, active_principal, require_permission
from app.api.imports import XLSX
from app.db.session import get_session
from app.schemas.attendance import (
    ChronicRow,
    MyStream,
    RegisterOut,
    StreamReportOut,
    StudentAttendanceOut,
    SyncIn,
    SyncOut,
)
from app.services import attendance as service
from app.services import calendar, fee_reports

router = APIRouter(tags=["attendance"])
Session = Annotated[AsyncSession, Depends(get_session)]
Signed = Annotated[Principal, Depends(active_principal)]
Reader = Annotated[Principal, require_permission("attendance.read")]


@router.get("/attendance/my-streams", response_model=list[MyStream], summary="Streams whose register I may take")
async def my_streams(principal: Signed, session: Session):
    return await service.my_streams(session, principal)


@router.get(
    "/attendance/register",
    response_model=RegisterOut,
    responses={304: {"description": "unchanged (If-None-Match)"}},
    summary="One stream's morning register for a day (default today, EAT), with gate-in times",
)
async def register(
    stream_id: uuid.UUID,
    principal: Signed,
    session: Session,
    response: Response,
    day: Annotated[date | None, Query(alias="date")] = None,
    if_none_match: Annotated[str | None, Header(alias="If-None-Match")] = None,
):
    out = await service.register(session, principal, stream_id, day or calendar.today())
    etag = 'W/"' + hashlib.sha256(out.model_dump_json().encode()).hexdigest()[:32] + '"'
    if if_none_match == etag:
        return Response(status_code=304, headers={"ETag": etag})
    response.headers["ETag"] = etag
    return out


@router.post(
    "/attendance/sync",
    response_model=SyncOut,
    summary="Records taken offline; each item is synced, conflict (later server value kept) or error",
)
async def sync(body: SyncIn, principal: Annotated[Principal, require_permission("attendance.take")], session: Session):
    return SyncOut(results=await service.sync(session, principal, body.items))


@router.post("/attendance/sessions/{session_id}/close", status_code=204, summary="Mark the register as taken")
async def close(session_id: uuid.UUID, principal: Signed, session: Session):
    await service.close(session, principal, session_id)


@router.get("/attendance/reports", response_model=StreamReportOut, responses={200: {"content": {XLSX: {}}}})
async def stream_report(
    stream_id: uuid.UUID,
    start: Annotated[date, Query(alias="from")],
    end: Annotated[date, Query(alias="to")],
    _: Reader,
    session: Session,
    format: Literal["json", "xlsx"] | None = None,
):
    report = await service.stream_report(session, stream_id, start, end)
    if format == "xlsx":
        rows = [r.model_dump(exclude={"student_id"}) for r in report.rows]
        return Response(
            fee_reports.xlsx(rows),
            media_type=XLSX,
            headers={"Content-Disposition": f'attachment; filename="attendance-{start}-{end}.xlsx"'},
        )
    return report


@router.get(
    "/attendance/chronic",
    response_model=list[ChronicRow],
    summary="Absent from the register on 3 or more days of the week containing `week`",
)
async def chronic(_: Reader, session: Session, week: date | None = None):
    return await service.chronic(session, week or calendar.today())


@router.get(
    "/students/{student_id}/attendance",
    response_model=StudentAttendanceOut,
    summary="Day by day (register status and gate-in time); staff, the student's guardians or the student",
)
async def student_attendance(
    student_id: uuid.UUID,
    start: Annotated[date, Query(alias="from")],
    end: Annotated[date, Query(alias="to")],
    principal: Signed,
    session: Session,
):
    return await service.student_attendance(session, principal, student_id, start, end)
