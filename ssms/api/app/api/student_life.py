"""/discipline-records, /activities (clubs), /library (books, loans, reminders), /students/{id}/health-records,
and the signed-in student's own clubs and loans (/me/activities, /me/loans)."""

import uuid
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import Principal, active_principal, require_permission
from app.core.errors import forbidden
from app.db.session import get_session
from app.models import Activity, LibraryBook, Student
from app.schemas.student_life import (
    ActivityIn,
    ActivityOut,
    ActivityUpdate,
    BookIn,
    BookOut,
    BookUpdate,
    DisciplineIn,
    DisciplineOut,
    DisciplineUpdate,
    HealthIn,
    HealthOut,
    LoanIn,
    LoanOut,
    MemberIn,
    MemberOut,
)
from app.services import calendar, crud, library
from app.services import student_life as service
from app.tasks.dispatch import get_dispatcher

router = APIRouter()
Session = Annotated[AsyncSession, Depends(get_session)]
Signed = Annotated[Principal, Depends(active_principal)]
DisciplineReader = Annotated[Principal, require_permission("discipline.read", "discipline.manage")]
Librarian = Annotated[Principal, require_permission("library.manage")]


# ---------------------------------------------------------------- discipline


@router.get("/discipline-records", response_model=list[DisciplineOut], tags=["discipline"])
async def list_incidents(
    _: DisciplineReader,
    session: Session,
    student_id: uuid.UUID | None = None,
    status: Annotated[Literal["OPEN", "RESOLVED"] | None, Query()] = None,
):
    return await service.discipline_list(session, student_id, status)


@router.post(
    "/discipline-records",
    response_model=DisciplineOut,
    status_code=201,
    tags=["discipline"],
    summary="Record an incident; the primary guardian gets one SMS (if they receive SMS)",
)
async def record_incident(
    body: DisciplineIn, principal: Annotated[Principal, require_permission("discipline.manage")], session: Session
):
    out, call = await service.record_incident(session, principal, body)
    if call:
        get_dispatcher().send("sms.send", **call)
    return out


@router.patch(
    "/discipline-records/{record_id}",
    response_model=DisciplineOut,
    tags=["discipline"],
    summary="Add the action or resolution; resolve=true needs a resolution",
)
async def update_incident(record_id: uuid.UUID, body: DisciplineUpdate, principal: DisciplineReader, session: Session):
    return await service.update_incident(session, principal, record_id, body)


# ---------------------------------------------------------------- clubs


@router.get("/activities", response_model=list[ActivityOut], tags=["clubs"])
async def list_activities(_: Signed, session: Session):
    return await service.activities(session)


@router.post("/activities", response_model=ActivityOut, status_code=201, tags=["clubs"])
async def create_activity(
    body: ActivityIn, principal: Annotated[Principal, require_permission("activities.manage")], session: Session
):
    item = await crud.create(session, principal, Activity, body.model_dump())
    return (await service.activities(session, ids=[item.id]))[0]


@router.patch("/activities/{activity_id}", response_model=ActivityOut, tags=["clubs"])
async def update_activity(
    activity_id: uuid.UUID,
    body: ActivityUpdate,
    _: Annotated[Principal, require_permission("activities.manage")],
    session: Session,
):
    await crud.update(session, Activity, activity_id, body.model_dump(exclude_unset=True))
    return (await service.activities(session, ids=[activity_id]))[0]


@router.get("/activities/{activity_id}/members", response_model=list[MemberOut], tags=["clubs"])
async def list_members(activity_id: uuid.UUID, principal: Signed, session: Session):
    if not await service.may_manage(session, principal, await crud.get_live(session, Activity, activity_id)):
        raise forbidden()
    return await service.members(session, activity_id)


@router.post(
    "/activities/{activity_id}/members",
    response_model=MemberOut,
    status_code=201,
    tags=["clubs"],
    summary="Add a member for the current year (activities.manage or the club's patron)",
)
async def add_member(activity_id: uuid.UUID, body: MemberIn, principal: Signed, session: Session):
    return await service.join(session, principal, activity_id, body)


@router.delete("/activity-members/{member_id}", status_code=204, tags=["clubs"])
async def remove_member(member_id: uuid.UUID, principal: Signed, session: Session):
    await service.leave(session, principal, member_id)


@router.get("/me/activities", response_model=list[MemberOut], tags=["portal"], summary="The signed-in student's clubs")
async def my_activities(principal: Signed, session: Session):
    student_id = (await session.execute(select(Student.id).where(Student.user_id == principal.user_id))).scalar()
    return await service.my_activities(session, student_id) if student_id else []


# ---------------------------------------------------------------- library


@router.get("/library/books", response_model=list[BookOut], tags=["library"], summary="Catalogue with free copies")
async def list_books(_: Signed, session: Session, q: Annotated[str | None, Query(max_length=60)] = None):
    return await service.books(session, q)


@router.post("/library/books", response_model=BookOut, status_code=201, tags=["library"])
async def add_book(body: BookIn, principal: Librarian, session: Session):
    item = await crud.create(session, principal, LibraryBook, body.model_dump())
    return (await service.books(session, ids=[item.id]))[0]


@router.patch(
    "/library/books/{book_id}",
    response_model=BookOut,
    tags=["library"],
    responses={422: {"description": "fewer copies than are on loan (no_copies)"}},
)
async def update_book(book_id: uuid.UUID, body: BookUpdate, _: Librarian, session: Session):
    return await service.change_copies(session, book_id, body.model_dump(exclude_unset=True))


@router.get("/library/loans", response_model=list[LoanOut], tags=["library"])
async def list_loans(
    _: Librarian,
    session: Session,
    open: bool = True,
    overdue: bool = False,
    borrower_user_id: uuid.UUID | None = None,
):
    return await service.loans(session, open, overdue, borrower_user_id)


@router.post(
    "/library/loans",
    response_model=LoanOut,
    status_code=201,
    tags=["library"],
    responses={422: {"description": "FULL no_copies"}},
    summary="Lend a copy to a user (or a student by admission number); due in 14 days by default",
)
async def lend(body: LoanIn, principal: Librarian, session: Session):
    return await service.lend(session, principal, body)


@router.post("/library/loans/{loan_id}/return", response_model=LoanOut, tags=["library"])
async def give_back(loan_id: uuid.UUID, principal: Librarian, session: Session):
    """A late return is fined at the LIBRARY_DAY rate on the student's term invoice (FR-97)."""
    loan_id, fine = await library.return_book(session, principal, loan_id)
    out = await service.loans_by_id(session, loan_id)
    out.fine_tzs = fine if fine else None
    return out


@router.post(
    "/library/reminders/run",
    tags=["library"],
    summary="Send overdue reminders now (one per loan per week; the daily job does the same)",
)
async def remind(principal: Librarian, session: Session):
    calls = await service.remind_overdue(session, principal.school_id, calendar.today())
    for call in calls:
        get_dispatcher().send("sms.send", **call)
    return {"queued": len(calls)}


@router.get("/me/loans", response_model=list[LoanOut], tags=["portal"], summary="Books I have borrowed")
async def my_loans(principal: Signed, session: Session):
    return await service.loans(session, False, False, principal.user_id)


# ---------------------------------------------------------------- health


@router.get(
    "/students/{student_id}/health-records",
    response_model=list[HealthOut],
    tags=["health"],
    responses={403: {"description": "no guardian HEALTH_DATA consent (no_consent)"}},
    summary="Health records (needs consent; every read is audited)",
)
async def health_records(
    student_id: uuid.UUID, principal: Annotated[Principal, require_permission("health.read")], session: Session
):
    return await service.health_records(session, principal, student_id)


@router.post("/students/{student_id}/health-records", response_model=HealthOut, status_code=201, tags=["health"])
async def add_health_record(
    student_id: uuid.UUID,
    body: HealthIn,
    principal: Annotated[Principal, require_permission("health.manage")],
    session: Session,
):
    return await service.add_health_record(session, principal, student_id, body)
