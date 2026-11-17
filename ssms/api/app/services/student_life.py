"""Discipline, clubs, library and health records.

Discipline: teachers record incidents (discipline.manage); the primary guardian who receives SMS is told once
(key discipline:<record>); RESOLVED needs a resolution (also a database CHECK).
Clubs: activities.manage, or the club's patron for its own members; memberships are per academic year.
Library: a loan needs a free copy (fn_capacity_guard -> 422 FULL no_copies); overdue loans get one SMS per ISO week
(students: their primary guardian; staff: themselves).
Health: health.read / health.manage AND a guardian's HEALTH_DATA consent for the student; notes are encrypted and
every read is audited as VIEW_SENSITIVE.
"""

import uuid
from datetime import date, timedelta

from sqlalchemy import and_, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import Principal
from app.core.crypto import get_cipher
from app.core.errors import AppError, forbidden
from app.db.session import DbContext, provider, school_session, set_context
from app.models import (
    AcademicYear,
    Activity,
    ConsentRecord,
    DisciplineRecord,
    Guardian,
    HealthRecord,
    LibraryBook,
    LibraryLoan,
    School,
    SmsMessage,
    Staff,
    Student,
    StudentActivity,
    StudentGuardian,
    User,
)
from app.models.enums import ConsentPurpose, DisciplineStatus
from app.schemas.student_life import (
    ActivityOut,
    BookOut,
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
from app.services import audit, calendar, crud, library, sms
from app.services.payments import _primary_guardian, template_text
from app.services.people import decrypt_phone, now
from app.tasks.dispatch import get_dispatcher

HEALTH_FIELD = "health_records.notes"
LOAN_DAYS = 14


def _name(first: str, middle: str | None, last: str) -> str:
    return " ".join(p for p in (first, middle, last) if p)


async def _school(session: AsyncSession) -> str:
    return (await session.execute(select(School.name))).scalar_one()[:40]


async def _learner(session: AsyncSession, student_id: uuid.UUID) -> str:
    row = (
        await session.execute(
            select(User.first_name, User.last_name)
            .join(Student, Student.user_id == User.id)
            .where(Student.id == student_id)
        )
    ).first()
    return f"{row.first_name} {row.last_name}"


# ---------------------------------------------------------------- discipline


async def _discipline_rows(session: AsyncSession, *where) -> list[DisciplineOut]:
    recorder = User.__table__.alias("recorder")
    rows = (
        await session.execute(
            select(
                DisciplineRecord,
                Student.admission_no,
                User.first_name,
                User.middle_name,
                User.last_name,
                recorder.c.first_name,
                recorder.c.last_name,
            )
            .join(Student, Student.id == DisciplineRecord.student_id)
            .join(User, User.id == Student.user_id)
            .join(recorder, recorder.c.id == DisciplineRecord.recorded_by)
            .where(DisciplineRecord.deleted_at.is_(None), *where)
            .order_by(DisciplineRecord.incident_date.desc(), DisciplineRecord.created_at.desc())
            .limit(200)
        )
    ).all()
    return [
        DisciplineOut(
            id=r.id,
            student_id=r.student_id,
            admission_no=admission,
            full_name=_name(first, middle, last),
            incident_date=r.incident_date,
            category=r.category,
            description=r.description,
            action_taken=r.action_taken,
            resolution=r.resolution,
            status=r.status,
            parent_notified_at=r.parent_notified_at,
            recorded_by=r.recorded_by,
            recorded_by_name=f"{rf} {rl}",
        )
        for r, admission, first, middle, last, rf, rl in rows
    ]


async def discipline_list(
    session: AsyncSession, student_id: uuid.UUID | None, status: str | None
) -> list[DisciplineOut]:
    where = []
    if student_id:
        where.append(DisciplineRecord.student_id == student_id)
    if status:
        where.append(DisciplineRecord.status == status)
    return await _discipline_rows(session, *where)


async def _notify_parent(session: AsyncSession, record: DisciplineRecord) -> dict | None:
    guardian = await _primary_guardian(session, record.student_id)
    phone = decrypt_phone(guardian) if guardian else None
    if not phone:
        return None
    lang = guardian.preferred_language
    body = (await template_text(session, "discipline_notice", lang)).format(
        school=await _school(session),
        student=await _learner(session, record.student_id),
        category=record.category.replace("_", " ").lower(),
        date=record.incident_date.strftime("%d/%m/%Y"),
    )
    message = await sms.queue_sms(
        session,
        school_id=record.school_id,
        phone=phone,
        body=body,
        language=lang,
        to_user_id=guardian.id,
        template_key="discipline_notice",
        idempotency_key=f"discipline:{record.id.hex}",
        related_entity="discipline_records",
        related_id=record.id,
    )
    record.parent_notified_at = now()
    return {"sms_id": str(message.id), "school_id": str(record.school_id)} if message.status == "QUEUED" else None


async def record_incident(
    session: AsyncSession, principal: Principal, body: DisciplineIn
) -> tuple[DisciplineOut, dict | None]:
    await crud.get_live(session, Student, body.student_id)
    record = DisciplineRecord(
        school_id=principal.school_id,
        recorded_by=principal.user_id,
        created_by=principal.user_id,
        **body.model_dump(exclude={"notify_parent"}),
    )
    session.add(record)
    await session.flush()
    call = await _notify_parent(session, record) if body.notify_parent else None
    await session.commit()
    return (await _discipline_rows(session, DisciplineRecord.id == record.id))[0], call


async def update_incident(
    session: AsyncSession, principal: Principal, record_id: uuid.UUID, body: DisciplineUpdate
) -> DisciplineOut:
    """The recorder or a discipline reader (school office) updates; RESOLVED needs a resolution."""
    record = await crud.get_live(session, DisciplineRecord, record_id, lock=True)
    if record.recorded_by != principal.user_id and not principal.has("discipline.read"):
        raise forbidden()
    if record.status == DisciplineStatus.RESOLVED:
        raise AppError(409, "NOT_ALLOWED", [{"field": "status", "code": "invalid_value"}])
    if body.action_taken is not None:
        record.action_taken = body.action_taken
    if body.resolution is not None:
        record.resolution = body.resolution
    if body.resolve:
        if not record.resolution:
            raise AppError(422, "VALIDATION_ERROR", [{"field": "resolution", "code": "required"}])
        record.status = DisciplineStatus.RESOLVED
    await session.commit()
    return (await _discipline_rows(session, DisciplineRecord.id == record.id))[0]


# ---------------------------------------------------------------- clubs


async def current_year(session: AsyncSession) -> uuid.UUID:
    year = (await session.execute(select(AcademicYear.id).where(AcademicYear.is_current))).scalar()
    if year is None:
        raise AppError(422, "VALIDATION_ERROR", [{"field": "academic_year_id", "code": "required"}])
    return year


async def activities(session: AsyncSession, ids: list[uuid.UUID] | None = None) -> list[ActivityOut]:
    year = (await session.execute(select(AcademicYear.id).where(AcademicYear.is_current))).scalar()
    counts = (
        select(StudentActivity.activity_id, func.count().label("n"))
        .where(StudentActivity.academic_year_id == year, StudentActivity.deleted_at.is_(None))
        .group_by(StudentActivity.activity_id)
        .subquery()
    )
    stmt = (
        select(Activity, User.first_name, User.last_name, counts.c.n)
        .outerjoin(Staff, Staff.id == Activity.patron_staff_id)
        .outerjoin(User, User.id == Staff.user_id)
        .outerjoin(counts, counts.c.activity_id == Activity.id)
        .where(Activity.deleted_at.is_(None))
        .order_by(Activity.name)
    )
    if ids:
        stmt = stmt.where(Activity.id.in_(ids))
    return [
        ActivityOut(
            id=a.id,
            name=a.name,
            kind=a.kind,
            patron_staff_id=a.patron_staff_id,
            patron_name=f"{first} {last}" if first else None,
            meeting_day=a.meeting_day,
            members=n or 0,
        )
        for a, first, last, n in (await session.execute(stmt)).all()
    ]


async def may_manage(session: AsyncSession, principal: Principal, activity: Activity) -> bool:
    if principal.has("activities.manage"):
        return True
    patron = (await session.execute(select(Staff.user_id).where(Staff.id == activity.patron_staff_id))).scalar()
    return patron is not None and patron == principal.user_id


async def _member_rows(session: AsyncSession, *where) -> list[MemberOut]:
    rows = (
        await session.execute(
            select(
                StudentActivity, Activity.name, Student.admission_no, User.first_name, User.middle_name, User.last_name
            )
            .join(Activity, Activity.id == StudentActivity.activity_id)
            .join(Student, Student.id == StudentActivity.student_id)
            .join(User, User.id == Student.user_id)
            .where(StudentActivity.deleted_at.is_(None), *where)
            .order_by(Activity.name, User.last_name)
        )
    ).all()
    return [
        MemberOut(
            id=m.id,
            activity_id=m.activity_id,
            activity_name=name,
            student_id=m.student_id,
            admission_no=admission,
            full_name=_name(first, middle, last),
            role=m.role,
            academic_year_id=m.academic_year_id,
        )
        for m, name, admission, first, middle, last in rows
    ]


async def members(session: AsyncSession, activity_id: uuid.UUID) -> list[MemberOut]:
    year = await current_year(session)
    return await _member_rows(
        session, StudentActivity.activity_id == activity_id, StudentActivity.academic_year_id == year
    )


async def join(session: AsyncSession, principal: Principal, activity_id: uuid.UUID, body: MemberIn) -> MemberOut:
    activity = await crud.get_live(session, Activity, activity_id)
    if not await may_manage(session, principal, activity):
        raise forbidden()
    await crud.get_live(session, Student, body.student_id)
    member = StudentActivity(
        school_id=principal.school_id,
        student_id=body.student_id,
        activity_id=activity_id,
        academic_year_id=await current_year(session),
        role=body.role,
        created_by=principal.user_id,
    )
    session.add(member)
    await crud.flush_checked(session, "student_id", "invalid_value")  # one membership per club and year
    await session.commit()
    return (await _member_rows(session, StudentActivity.id == member.id))[0]


async def leave(session: AsyncSession, principal: Principal, member_id: uuid.UUID) -> None:
    member = await crud.get_live(session, StudentActivity, member_id, lock=True)
    if not await may_manage(session, principal, await crud.get_live(session, Activity, member.activity_id)):
        raise forbidden()
    member.deleted_at = now()
    await session.commit()


async def my_activities(session: AsyncSession, student_id: uuid.UUID) -> list[MemberOut]:
    year = (await session.execute(select(AcademicYear.id).where(AcademicYear.is_current))).scalar()
    return await _member_rows(
        session, StudentActivity.student_id == student_id, StudentActivity.academic_year_id == year
    )


# ---------------------------------------------------------------- library


async def books(session: AsyncSession, q: str | None = None, ids: list[uuid.UUID] | None = None) -> list[BookOut]:
    on_loan = (
        select(LibraryLoan.book_id, func.count().label("n"))
        .where(LibraryLoan.returned_at.is_(None))
        .group_by(LibraryLoan.book_id)
        .subquery()
    )
    stmt = (
        select(LibraryBook, on_loan.c.n)
        .outerjoin(on_loan, on_loan.c.book_id == LibraryBook.id)
        .where(LibraryBook.deleted_at.is_(None))
        .order_by(LibraryBook.title)
        .limit(200)
    )
    if q:
        like = f"%{q.strip()}%"
        stmt = stmt.where(
            or_(LibraryBook.title.ilike(like), LibraryBook.author.ilike(like), LibraryBook.isbn.ilike(like))
        )
    if ids:
        stmt = stmt.where(LibraryBook.id.in_(ids))
    out = []
    for book, n in (await session.execute(stmt)).all():
        item = BookOut.model_validate(book)
        item.on_loan, item.available = n or 0, max(book.copies - (n or 0), 0)
        out.append(item)
    return out


async def change_copies(session: AsyncSession, book_id: uuid.UUID, data: dict) -> BookOut:
    book = await crud.get_live(session, LibraryBook, book_id, lock=True)
    current = (await books(session, ids=[book.id]))[0]
    if data.get("copies") is not None and data["copies"] < current.on_loan:
        raise AppError(422, "VALIDATION_ERROR", [{"field": "copies", "code": "no_copies"}])
    for field, value in data.items():
        setattr(book, field, value)
    await session.commit()
    return (await books(session, ids=[book.id]))[0]


async def _loan_rows(session: AsyncSession, *where, limit: int = 200) -> list[LoanOut]:
    today = calendar.today()
    rows = (
        await session.execute(
            select(LibraryLoan, LibraryBook.title, User.first_name, User.middle_name, User.last_name)
            .join(LibraryBook, LibraryBook.id == LibraryLoan.book_id)
            .join(User, User.id == LibraryLoan.borrower_user_id)
            .where(*where)
            .order_by(LibraryLoan.due_date, LibraryLoan.loaned_at)
            .limit(limit)
        )
    ).all()
    return [
        LoanOut(
            id=loan.id,
            book_id=loan.book_id,
            title=title,
            borrower_user_id=loan.borrower_user_id,
            borrower_name=_name(first, middle, last),
            loaned_at=loan.loaned_at,
            due_date=loan.due_date,
            returned_at=loan.returned_at,
            overdue=loan.returned_at is None and loan.due_date < today,
        )
        for loan, title, first, middle, last in rows
    ]


async def loans(
    session: AsyncSession, open_only: bool, overdue: bool, borrower_user_id: uuid.UUID | None
) -> list[LoanOut]:
    where = []
    if open_only or overdue:
        where.append(LibraryLoan.returned_at.is_(None))
    if overdue:
        where.append(LibraryLoan.due_date < calendar.today())
    if borrower_user_id:
        where.append(LibraryLoan.borrower_user_id == borrower_user_id)
    return await _loan_rows(session, *where)


async def lend(session: AsyncSession, principal: Principal, body: LoanIn) -> LoanOut:
    book = await crud.get_live(session, LibraryBook, body.book_id)
    borrower = body.borrower_user_id
    if borrower is None and body.admission_no:
        borrower = (
            await session.execute(
                select(Student.user_id).where(
                    func.upper(Student.admission_no) == body.admission_no.strip().upper(), Student.deleted_at.is_(None)
                )
            )
        ).scalar()
    if borrower is None and body.card_no:
        borrower = await library.card_holder(session, body.card_no)
    if borrower is None:
        raise AppError(422, "VALIDATION_ERROR", [{"field": "borrower_user_id", "code": "required"}])
    await crud.get_live(session, User, borrower)
    due = body.due_date or calendar.today() + timedelta(days=LOAN_DAYS)
    if due < calendar.today():
        raise AppError(422, "VALIDATION_ERROR", [{"field": "due_date", "code": "invalid_value"}])
    loan = LibraryLoan(
        school_id=principal.school_id,
        book_id=book.id,
        borrower_user_id=borrower,
        due_date=due,
        issued_by=principal.user_id,
        created_by=principal.user_id,
    )
    session.add(loan)
    await crud.flush_checked(session, "book_id", "no_copies")
    await session.commit()
    return (await _loan_rows(session, LibraryLoan.id == loan.id))[0]


async def loans_by_id(session: AsyncSession, loan_id: uuid.UUID) -> LoanOut:
    return (await _loan_rows(session, LibraryLoan.id == loan_id))[0]


async def give_back(session: AsyncSession, loan_id: uuid.UUID) -> LoanOut:
    loan = await crud.get_live(session, LibraryLoan, loan_id, lock=True)
    if loan.returned_at is None:
        loan.returned_at = now()
        await session.commit()
    return (await _loan_rows(session, LibraryLoan.id == loan.id))[0]


async def remind_overdue(session: AsyncSession, school_id: uuid.UUID, today: date) -> list[dict]:
    """One SMS per overdue loan per ISO week; returns the sms.send calls."""
    year, week, _ = today.isocalendar()
    school = await _school(session)
    calls = []
    for loan in await _loan_rows(session, LibraryLoan.returned_at.is_(None), LibraryLoan.due_date < today, limit=1000):
        student_id = (
            await session.execute(select(Student.id).where(Student.user_id == loan.borrower_user_id))
        ).scalar()
        recipient = (
            await _primary_guardian(session, student_id)
            if student_id
            else (await session.execute(select(User).where(User.id == loan.borrower_user_id))).scalar_one()
        )
        phone = decrypt_phone(recipient) if recipient else None
        key = f"library:{loan.id.hex}:{year}W{week:02d}"
        if not phone or (await session.execute(select(SmsMessage.id).where(SmsMessage.idempotency_key == key))).first():
            continue
        lang = recipient.preferred_language
        body = (await template_text(session, "library_overdue", lang)).format(
            school=school, title=loan.title[:60], borrower=loan.borrower_name, due=loan.due_date.strftime("%d/%m/%Y")
        )
        message = await sms.queue_sms(
            session,
            school_id=school_id,
            phone=phone,
            body=body,
            language=lang,
            to_user_id=recipient.id,
            template_key="library_overdue",
            idempotency_key=key,
            related_entity="library_loans",
            related_id=loan.id,
        )
        if message.status == "QUEUED":
            calls.append({"sms_id": str(message.id), "school_id": str(school_id)})
    await session.commit()
    return calls


async def run_reminders(school_id: str, today: str | None = None) -> str:
    async with school_session(uuid.UUID(school_id)) as session:
        calls = await remind_overdue(
            session, uuid.UUID(school_id), date.fromisoformat(today) if today else calendar.today()
        )
    for call in calls:
        get_dispatcher().send("sms.send", **call)
    return f"{len(calls)} overdue reminders"


async def fanout() -> str:
    """Daily (Celery beat): one library reminder job per active school."""
    async with provider.app() as session:
        await set_context(session, DbContext())
        schools = (await session.execute(select(func.list_active_school_ids()))).scalars().all()
    for school_id in schools:
        get_dispatcher().send("library.remind", school_id=str(school_id))
    return f"{len(schools)} schools"


# ---------------------------------------------------------------- health


async def has_health_consent(session: AsyncSession, student_id: uuid.UUID) -> bool:
    """A guardian of the student has granted HEALTH_DATA consent (for this student or all their children)."""
    return (
        await session.execute(
            select(ConsentRecord.id)
            .join(Guardian, Guardian.id == ConsentRecord.guardian_id)
            .join(
                StudentGuardian,
                and_(
                    StudentGuardian.guardian_id == Guardian.id,
                    StudentGuardian.student_id == student_id,
                    StudentGuardian.deleted_at.is_(None),
                ),
            )
            .where(
                ConsentRecord.purpose == ConsentPurpose.HEALTH_DATA,
                ConsentRecord.granted.is_(True),
                ConsentRecord.withdrawn_at.is_(None),
                or_(ConsentRecord.student_id == student_id, ConsentRecord.student_id.is_(None)),
            )
            .limit(1)
        )
    ).first() is not None


async def _require_consent(session: AsyncSession, student_id: uuid.UUID) -> None:
    await crud.get_live(session, Student, student_id)
    if not await has_health_consent(session, student_id):
        raise AppError(403, "FORBIDDEN", [{"field": "student_id", "code": "no_consent"}])


def _notes(blob: bytes) -> str | None:
    try:
        return get_cipher().decrypt(blob, HEALTH_FIELD)
    except Exception:  # noqa: BLE001 - unreadable or foreign ciphertext: show nothing, never fail the list
        return None


async def health_records(session: AsyncSession, principal: Principal, student_id: uuid.UUID) -> list[HealthOut]:
    await _require_consent(session, student_id)
    rows = (
        await session.execute(
            select(HealthRecord, User.first_name, User.last_name)
            .join(User, User.id == HealthRecord.recorded_by)
            .where(HealthRecord.student_id == student_id, HealthRecord.deleted_at.is_(None))
            .order_by(HealthRecord.record_date.desc())
        )
    ).all()
    await audit.record(session, "VIEW_SENSITIVE", "health_records", student_id, {"records": len(rows)})
    await session.commit()
    return [
        HealthOut(
            id=r.id,
            student_id=r.student_id,
            record_date=r.record_date,
            kind=r.kind,
            notes=_notes(r.notes_enc),
            recorded_by_name=f"{first} {last}",
            created_at=r.created_at,
        )
        for r, first, last in rows
    ]


async def add_health_record(
    session: AsyncSession, principal: Principal, student_id: uuid.UUID, body: HealthIn
) -> HealthOut:
    await _require_consent(session, student_id)
    record = HealthRecord(
        school_id=principal.school_id,
        student_id=student_id,
        record_date=body.record_date,
        kind=body.kind,
        notes_enc=get_cipher().encrypt(body.notes, HEALTH_FIELD),
        recorded_by=principal.user_id,
        created_by=principal.user_id,
    )
    session.add(record)
    await session.commit()
    await session.refresh(record)
    me = (await session.execute(select(User.first_name, User.last_name).where(User.id == principal.user_id))).first()
    return HealthOut(
        id=record.id,
        student_id=student_id,
        record_date=record.record_date,
        kind=record.kind,
        notes=body.notes,
        recorded_by_name=f"{me.first_name} {me.last_name}",
        created_at=record.created_at,
    )
