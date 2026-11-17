"""Candidate numbers, admit cards, the exam timetable PDF and subject ranking (FR-84, FR-85, FR-86)."""

import uuid
from datetime import date
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, Response
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import Principal, active_principal, require_permission
from app.core.errors import forbidden
from app.db.session import get_session
from app.services import exam_docs as service

router = APIRouter(tags=["exams"])
Session = Annotated[AsyncSession, Depends(get_session)]
Numberer = Annotated[Principal, require_permission("exams.admit_cards")]
Reader = Annotated[Principal, require_permission("exams.read", "exams.admit_cards")]
Lang = Literal["sw", "en"] | None
PDF = {200: {"content": {"application/pdf": {}}}}


def _pdf(data: bytes, name: str) -> Response:
    return Response(
        data, media_type="application/pdf", headers={"Content-Disposition": f'attachment; filename="{name}"'}
    )


class NumberIn(BaseModel):
    prefix: str | None = Field(
        default=None,
        max_length=12,
        pattern=r"^[A-Za-z0-9./-]*$",
        description="Default: the school's centre number and a dash",
    )
    start: int = Field(default=1, ge=1, le=9999)


class Candidate(BaseModel):
    enrolment_id: uuid.UUID
    admission_no: str
    full_name: str
    class_code: str
    stream: str
    candidate_no: str | None


class RankRow(BaseModel):
    position: int
    admission_no: str
    full_name: str
    stream: str
    score: float | None
    grade: str | None


@router.get("/exam-sessions/{session_id}/candidates", response_model=list[Candidate], summary="Who sits, with numbers")
async def list_candidates(session_id: uuid.UUID, _: Reader, session: Session, class_id: uuid.UUID | None = None):
    return await service.candidates(session, session_id, class_id)


@router.post("/exam-sessions/{session_id}/candidates", summary="Number every candidate who has no number yet")
async def number_candidates(session_id: uuid.UUID, body: NumberIn, principal: Numberer, session: Session) -> dict:
    return {"numbered": await service.number_candidates(session, principal, session_id, body.prefix, body.start)}


@router.get("/exam-sessions/{session_id}/admit-cards.pdf", response_class=Response, responses=PDF)
async def admit_cards(
    session_id: uuid.UUID, principal: Numberer, session: Session, class_id: uuid.UUID | None = None, lang: Lang = None
):
    data = await service.admit_cards_pdf(session, session_id, lang or principal.language, class_id=class_id)
    return _pdf(data, "admit-cards.pdf")


@router.get("/exam-sessions/{session_id}/timetable.pdf", response_class=Response, responses=PDF)
async def timetable(session_id: uuid.UUID, principal: Reader, session: Session, lang: Lang = None):
    return _pdf(await service.timetable_pdf(session, session_id, lang or principal.language), "exam-timetable.pdf")


class MySession(BaseModel):
    id: uuid.UUID
    name: str
    start_date: date
    end_date: date
    candidate_no: str


@router.get(
    "/portal/exam-sessions", response_model=list[MySession], tags=["portal"], summary="A student's numbered sessions"
)
async def my_sessions(principal: Annotated[Principal, Depends(active_principal)], session: Session):
    if not principal.has("portal.student"):
        raise forbidden()
    return await service.my_sessions(session, principal)


@router.get(
    "/portal/admit-card.pdf", response_class=Response, responses=PDF, tags=["portal"], summary="A student's own card"
)
async def own_admit_card(
    exam_session_id: uuid.UUID,
    principal: Annotated[Principal, Depends(active_principal)],
    session: Session,
    lang: Lang = None,
):
    if not principal.has("portal.student"):
        raise forbidden()
    enrolment = await service.own_enrolment_in(session, principal, exam_session_id)
    data = await service.admit_cards_pdf(session, exam_session_id, lang or principal.language, enrolment_id=enrolment)
    return _pdf(data, "admit-card.pdf")


@router.get(
    "/results/subject-ranking", response_model=list[RankRow], tags=["results"], summary="One subject, best first"
)
async def subject_ranking(
    term_id: uuid.UUID,
    class_id: uuid.UUID,
    subject_id: uuid.UUID,
    principal: Annotated[Principal, require_permission("results.read", "results.publish")],
    session: Session,
):
    return await service.subject_ranking(session, term_id, class_id, subject_id)
