"""Study materials, homework and submissions, lesson attendance and the monthly sheet (FR-82, FR-83, FR-90 .. FR-93).

Who may do what, beyond the permission codes:
* a teacher publishes and marks only for streams and subjects in their teaching_assignments for the year; the office
  (academics.configure) may do it for any stream;
* a student sees and submits only for their own enrolment; a parent sees only their linked children;
* a lesson register is taken by the slot's teacher (or the office), on the slot's weekday, inside its term.
"""

import uuid
from calendar import monthrange
from datetime import date, datetime

from sqlalchemy import and_, func, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import Principal
from app.core.errors import AppError, forbidden, not_found
from app.core.storage import get_storage
from app.models import (
    AcademicYear,
    AttendanceRecord,
    AttendanceSession,
    Enrolment,
    Guardian,
    Homework,
    HomeworkStream,
    HomeworkSubmission,
    School,
    SchoolClass,
    Staff,
    StoredFile,
    Stream,
    Student,
    StudentGuardian,
    StudyMaterial,
    StudyMaterialStream,
    Subject,
    TeachingAssignment,
    Term,
    TimetableSlot,
    User,
)
from app.models.enums import EnrolmentStatus, FilePurpose, SessionKind
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
    SheetRow,
    StudentHomework,
    SubmissionIn,
)
from app.services import calendar, sms
from app.services.payments import _primary_guardian
from app.services.people import decrypt_phone, now

OFFICE = "academics.configure"
FULL_NAME = func.concat_ws(" ", User.first_name, User.last_name)
CODES = {"PRESENT": "P", "ABSENT": "A", "LATE": "L", "EXCUSED": "E"}


# ---------------------------------------------------------------- shared lookups


async def current_year(session: AsyncSession) -> uuid.UUID:
    year = (
        await session.execute(
            select(AcademicYear.id).where(AcademicYear.is_current.is_(True), AcademicYear.deleted_at.is_(None))
        )
    ).scalar_one_or_none()
    if year is None:
        raise AppError(422, "VALIDATION_ERROR", [{"field": "academic_year_id", "code": "required"}])
    return year


async def own_staff_id(session: AsyncSession, principal: Principal) -> uuid.UUID | None:
    return (
        await session.execute(select(Staff.id).where(Staff.user_id == principal.user_id, Staff.deleted_at.is_(None)))
    ).scalar_one_or_none()


async def stream_labels(session: AsyncSession, ids) -> dict[uuid.UUID, str]:
    rows = await session.execute(
        select(Stream.id, SchoolClass.code, Stream.name)
        .join(SchoolClass, SchoolClass.id == Stream.class_id)
        .where(Stream.id.in_(list(ids)))
    )
    return {i: f"{code} {name}" for i, code, name in rows}


def _subject_name(subject: Subject, principal: Principal) -> str:
    return subject.name_en if principal.language == "en" else subject.name_sw


async def _check_targets(
    session: AsyncSession, principal: Principal, year: uuid.UUID, subject_id: uuid.UUID, stream_ids: list[uuid.UUID]
) -> uuid.UUID:
    """The staff id of the caller, after checking they teach the subject in every stream (the office may skip)."""
    staff_id = await own_staff_id(session, principal)
    known = set(
        (
            await session.execute(select(Stream.id).where(Stream.id.in_(stream_ids), Stream.deleted_at.is_(None)))
        ).scalars()
    )
    if known != set(stream_ids):
        raise AppError(422, "INVALID_REFERENCE", [{"field": "stream_ids", "code": "invalid_value"}])
    if (
        await session.execute(select(Subject.id).where(Subject.id == subject_id, Subject.deleted_at.is_(None)))
    ).first() is None:
        raise AppError(422, "INVALID_REFERENCE", [{"field": "subject_id", "code": "invalid_value"}])
    if staff_id is None:
        raise forbidden()
    if principal.has(OFFICE):
        return staff_id
    taught = set(
        (
            await session.execute(
                select(TeachingAssignment.stream_id).where(
                    TeachingAssignment.staff_id == staff_id,
                    TeachingAssignment.subject_id == subject_id,
                    TeachingAssignment.academic_year_id == year,
                    TeachingAssignment.deleted_at.is_(None),
                )
            )
        ).scalars()
    )
    if not set(stream_ids) <= taught:
        raise AppError(403, "NOT_ALLOWED", [{"field": "stream_ids", "code": "not_your_class"}])
    return staff_id


async def _own_upload(session: AsyncSession, principal: Principal, file_id, purpose: FilePurpose) -> StoredFile:
    row = (
        await session.execute(select(StoredFile).where(StoredFile.id == file_id, StoredFile.deleted_at.is_(None)))
    ).scalar_one_or_none()
    if row is None or row.purpose != purpose or row.created_by != principal.user_id:
        raise AppError(422, "VALIDATION_ERROR", [{"field": "file_id", "code": "invalid_value"}])
    return row


async def _file_names(session: AsyncSession, ids) -> dict[uuid.UUID, str]:
    ids = [i for i in ids if i]
    if not ids:
        return {}
    return dict(
        (await session.execute(select(StoredFile.id, StoredFile.original_name).where(StoredFile.id.in_(ids)))).all()
    )


async def my_students(session: AsyncSession, principal: Principal) -> list[tuple[uuid.UUID, str, uuid.UUID, uuid.UUID]]:
    """(student id, name, enrolment id, stream id) the caller may follow: themself as a student, or their children."""
    year = await current_year(session)
    stmt = (
        select(Student.id, FULL_NAME, Enrolment.id, Enrolment.stream_id)
        .join(User, User.id == Student.user_id)
        .join(
            Enrolment,
            and_(
                Enrolment.student_id == Student.id,
                Enrolment.academic_year_id == year,
                Enrolment.status == EnrolmentStatus.ACTIVE,
            ),
        )
        .where(Student.deleted_at.is_(None))
    )
    if principal.has("portal.student"):
        stmt = stmt.where(Student.user_id == principal.user_id)
    elif principal.has("portal.parent"):
        stmt = (
            stmt.join(
                StudentGuardian, and_(StudentGuardian.student_id == Student.id, StudentGuardian.deleted_at.is_(None))
            )
            .join(Guardian, Guardian.id == StudentGuardian.guardian_id)
            .where(Guardian.user_id == principal.user_id)
        )
    else:
        return []
    return [tuple(r) for r in (await session.execute(stmt)).all()]


async def _enrolled(session: AsyncSession, stream_ids, year: uuid.UUID):
    return (
        await session.execute(
            select(Student.id, Student.admission_no, FULL_NAME, Enrolment.id, Enrolment.stream_id)
            .join(Enrolment, Enrolment.student_id == Student.id)
            .join(User, User.id == Student.user_id)
            .where(
                Enrolment.stream_id.in_(list(stream_ids)),
                Enrolment.academic_year_id == year,
                Enrolment.status == EnrolmentStatus.ACTIVE,
            )
            .order_by(User.last_name, User.first_name)
        )
    ).all()


# ---------------------------------------------------------------- study materials


async def publish_material(session: AsyncSession, principal: Principal, body: MaterialIn) -> uuid.UUID:
    year = await current_year(session)
    staff_id = await _check_targets(session, principal, year, body.subject_id, body.stream_ids)
    if body.file_id:
        await _own_upload(session, principal, body.file_id, FilePurpose.STUDY_MATERIAL)
    item = StudyMaterial(
        school_id=principal.school_id,
        academic_year_id=year,
        subject_id=body.subject_id,
        title=body.title,
        description=body.description,
        file_id=body.file_id,
        link_url=str(body.link_url) if body.link_url else None,
        published_by=staff_id,
        created_by=principal.user_id,
    )
    session.add(item)
    for stream_id in dict.fromkeys(body.stream_ids):
        session.add(
            StudyMaterialStream(
                school_id=principal.school_id, material_id=item.id, stream_id=stream_id, created_by=principal.user_id
            )
        )
    await session.commit()
    return item.id


async def _material_rows(session: AsyncSession, principal: Principal, where) -> list[MaterialOut]:
    rows = (
        await session.execute(
            select(StudyMaterial, Subject, FULL_NAME)
            .join(Subject, Subject.id == StudyMaterial.subject_id)
            .join(Staff, Staff.id == StudyMaterial.published_by)
            .join(User, User.id == Staff.user_id)
            .where(StudyMaterial.deleted_at.is_(None), *where)
            .order_by(StudyMaterial.created_at.desc())
            .limit(200)
        )
    ).all()
    ids = [m.id for m, _, _ in rows]
    links = (
        await session.execute(
            select(StudyMaterialStream.material_id, StudyMaterialStream.stream_id).where(
                StudyMaterialStream.material_id.in_(ids)
            )
        )
    ).all()
    labels = await stream_labels(session, {s for _, s in links})
    names = await _file_names(session, [m.file_id for m, _, _ in rows])
    me = await own_staff_id(session, principal)
    return [
        MaterialOut(
            id=m.id,
            subject_id=m.subject_id,
            subject=_subject_name(subject, principal),
            title=m.title,
            description=m.description,
            streams=sorted(labels[s] for mid, s in links if mid == m.id),
            file_name=names.get(m.file_id),
            link_url=m.link_url,
            published_by=who,
            created_at=m.created_at,
            mine=me is not None and m.published_by == me,
        )
        for m, subject, who in rows
    ]


async def list_materials(
    session: AsyncSession, principal: Principal, *, stream_id: uuid.UUID | None, subject_id: uuid.UUID | None
) -> list[MaterialOut]:
    where = [StudyMaterial.academic_year_id == await current_year(session)]
    if subject_id:
        where.append(StudyMaterial.subject_id == subject_id)
    if stream_id:
        where.append(
            StudyMaterial.id.in_(
                select(StudyMaterialStream.material_id).where(StudyMaterialStream.stream_id == stream_id)
            )
        )
    return await _material_rows(session, principal, where)


async def my_materials(session: AsyncSession, principal: Principal) -> list[MaterialOut]:
    streams = {stream for _, _, _, stream in await my_students(session, principal)}
    if not streams:
        return []
    return await _material_rows(
        session,
        principal,
        [
            StudyMaterial.id.in_(
                select(StudyMaterialStream.material_id).where(StudyMaterialStream.stream_id.in_(streams))
            )
        ],
    )


async def remove_material(session: AsyncSession, principal: Principal, material_id: uuid.UUID) -> None:
    item = await session.get(StudyMaterial, material_id)
    if item is None or item.deleted_at is not None:
        raise not_found()
    if not principal.has(OFFICE) and item.published_by != await own_staff_id(session, principal):
        raise forbidden()
    item.deleted_at = now()
    await session.commit()


async def _target_streams(session: AsyncSession, link, parent_id) -> set[uuid.UUID]:
    column = link.material_id if link is StudyMaterialStream else link.homework_id
    return set((await session.execute(select(link.stream_id).where(column == parent_id))).scalars())


async def _may_open(
    session: AsyncSession, principal: Principal, streams: set[uuid.UUID], staff_permission: str
) -> bool:
    if principal.has(staff_permission) or principal.has(OFFICE):
        return True
    return any(stream in streams for _, _, _, stream in await my_students(session, principal))


async def material_file(
    session: AsyncSession, principal: Principal, material_id: uuid.UUID
) -> tuple[StoredFile, bytes]:
    item = await session.get(StudyMaterial, material_id)
    if item is None or item.deleted_at is not None or item.file_id is None:
        raise not_found()
    streams = await _target_streams(session, StudyMaterialStream, item.id)
    if not await _may_open(session, principal, streams, "materials.publish"):
        raise not_found()
    upload = await session.get(StoredFile, item.file_id)
    return upload, get_storage().get(upload.storage_key)


# ---------------------------------------------------------------- homework


def _late(due_at: datetime) -> bool:
    return datetime.now(due_at.tzinfo) > due_at


async def set_homework(session: AsyncSession, principal: Principal, body: HomeworkIn) -> tuple[uuid.UUID, list[dict]]:
    """Returns the homework id and the SMS to dispatch after commit."""
    year = await current_year(session)
    staff_id = await _check_targets(session, principal, year, body.subject_id, body.stream_ids)
    if body.file_id:
        await _own_upload(session, principal, body.file_id, FilePurpose.HOMEWORK)
    item = Homework(
        school_id=principal.school_id,
        academic_year_id=year,
        created_by=principal.user_id,
        set_by=staff_id,
        **body.model_dump(exclude={"stream_ids"}),
    )
    session.add(item)
    for stream_id in dict.fromkeys(body.stream_ids):
        session.add(
            HomeworkStream(
                school_id=principal.school_id, homework_id=item.id, stream_id=stream_id, created_by=principal.user_id
            )
        )
    await session.flush()
    calls = await _notify_parents(session, principal, item, year) if body.notify_parents else []
    await session.commit()
    return item.id, calls


async def _notify_parents(session: AsyncSession, principal: Principal, item: Homework, year: uuid.UUID) -> list[dict]:
    school = (await session.execute(select(School.name))).scalar_one()
    subject = await session.get(Subject, item.subject_id)
    streams = await _target_streams(session, HomeworkStream, item.id)
    due = calendar.local(item.due_at).strftime("%d/%m %H:%M")
    calls = []
    for student_id, _, name, _, _ in await _enrolled(session, streams, year):
        guardian = await _primary_guardian(session, student_id)
        phone = decrypt_phone(guardian) if guardian else None
        if not phone:
            continue
        lang = guardian.preferred_language
        text = (
            f"{school[:40]}: Homework ({subject.name_en}) for {name}: {item.title}. Due {due}."
            if lang == "en"
            else f"{school[:40]}: Kazi ya nyumbani ({subject.name_sw}) kwa {name}: {item.title}. Mwisho {due}."
        )
        message = await sms.queue_sms(
            session,
            school_id=principal.school_id,
            phone=phone,
            body=text,
            language=lang,
            to_user_id=guardian.id,
            template_key="homework",
            idempotency_key=f"hw:{item.id}:{student_id}",  # at most 80 characters
            related_entity="homework",
            related_id=item.id,
        )
        if message.status == "QUEUED":
            calls.append({"sms_id": str(message.id), "school_id": str(principal.school_id)})
    return calls


async def _may_mark(session: AsyncSession, principal: Principal, item: Homework, stream_id: uuid.UUID) -> bool:
    if principal.has(OFFICE):
        return True
    staff_id = await own_staff_id(session, principal)
    if staff_id is None:
        return False
    if item.set_by == staff_id:
        return True
    return (
        await session.execute(
            select(TeachingAssignment.id).where(
                TeachingAssignment.staff_id == staff_id,
                TeachingAssignment.subject_id == item.subject_id,
                TeachingAssignment.stream_id == stream_id,
                TeachingAssignment.academic_year_id == item.academic_year_id,
                TeachingAssignment.deleted_at.is_(None),
            )
        )
    ).first() is not None


async def list_homework(session: AsyncSession, principal: Principal, *, everyone: bool) -> list[HomeworkOut]:
    year = await current_year(session)
    me = await own_staff_id(session, principal)
    stmt = (
        select(Homework, Subject, FULL_NAME)
        .join(Subject, Subject.id == Homework.subject_id)
        .join(Staff, Staff.id == Homework.set_by)
        .join(User, User.id == Staff.user_id)
        .where(Homework.deleted_at.is_(None), Homework.academic_year_id == year)
        .order_by(Homework.due_at.desc())
        .limit(200)
    )
    if not everyone:
        stmt = stmt.where(Homework.set_by == me)
    rows = (await session.execute(stmt)).all()
    ids = [h.id for h, _, _ in rows]
    links = (
        await session.execute(
            select(HomeworkStream.homework_id, HomeworkStream.stream_id).where(HomeworkStream.homework_id.in_(ids))
        )
    ).all()
    labels = await stream_labels(session, {s for _, s in links})
    expected = dict(
        (
            await session.execute(
                select(HomeworkStream.homework_id, func.count(Enrolment.id))
                .join(
                    Enrolment,
                    and_(
                        Enrolment.stream_id == HomeworkStream.stream_id,
                        Enrolment.academic_year_id == year,
                        Enrolment.status == EnrolmentStatus.ACTIVE,
                    ),
                )
                .where(HomeworkStream.homework_id.in_(ids))
                .group_by(HomeworkStream.homework_id)
            )
        ).all()
    )
    counts = {
        hid: (n, m)
        for hid, n, m in (
            await session.execute(
                select(
                    HomeworkSubmission.homework_id,
                    func.count(),
                    func.count().filter(HomeworkSubmission.marked_at.is_not(None)),
                )
                .where(HomeworkSubmission.homework_id.in_(ids))
                .group_by(HomeworkSubmission.homework_id)
            )
        ).all()
    }
    names = await _file_names(session, [h.file_id for h, _, _ in rows])
    return [
        HomeworkOut(
            id=h.id,
            subject_id=h.subject_id,
            subject=_subject_name(subject, principal),
            title=h.title,
            instructions=h.instructions,
            file_name=names.get(h.file_id),
            max_score=h.max_score,
            due_at=h.due_at,
            streams=sorted(labels[s] for hid, s in links if hid == h.id),
            set_by=who,
            created_at=h.created_at,
            expected=expected.get(h.id, 0),
            submitted=counts.get(h.id, (0, 0))[0],
            marked=counts.get(h.id, (0, 0))[1],
            mine=me is not None and h.set_by == me,
        )
        for h, subject, who in rows
    ]


def _submission_out(sub: HomeworkSubmission | None, names: dict) -> MySubmission | None:
    if sub is None:
        return None
    return MySubmission(
        id=sub.id,
        submitted_at=sub.submitted_at,
        is_late=sub.is_late,
        file_name=names.get(sub.file_id),
        body=sub.body,
        score=sub.score,
        feedback=sub.feedback,
        marked_at=sub.marked_at,
    )


async def _live_homework(session: AsyncSession, homework_id: uuid.UUID) -> Homework:
    item = await session.get(Homework, homework_id)
    if item is None or item.deleted_at is not None:
        raise not_found()
    return item


async def roster(session: AsyncSession, principal: Principal, homework_id: uuid.UUID) -> list[RosterRow]:
    item = await _live_homework(session, homework_id)
    streams = await _target_streams(session, HomeworkStream, item.id)
    if not any([await _may_mark(session, principal, item, s) for s in streams]):
        raise forbidden()
    students = await _enrolled(session, streams, item.academic_year_id)
    subs = {
        s.enrolment_id: s
        for s in (
            await session.execute(select(HomeworkSubmission).where(HomeworkSubmission.homework_id == item.id))
        ).scalars()
    }
    names = await _file_names(session, [s.file_id for s in subs.values()])
    labels = await stream_labels(session, streams)
    return [
        RosterRow(
            student_id=sid,
            admission_no=no,
            full_name=name,
            stream=labels[stream],
            submission=_submission_out(subs.get(enrolment), names),
        )
        for sid, no, name, enrolment, stream in students
    ]


async def my_homework(session: AsyncSession, principal: Principal) -> list[StudentHomework]:
    mine = await my_students(session, principal)
    if not mine:
        return []
    by_stream: dict[uuid.UUID, list] = {}
    for student in mine:
        by_stream.setdefault(student[3], []).append(student)
    rows = (
        await session.execute(
            select(Homework, Subject, HomeworkStream.stream_id)
            .join(HomeworkStream, HomeworkStream.homework_id == Homework.id)
            .join(Subject, Subject.id == Homework.subject_id)
            .where(Homework.deleted_at.is_(None), HomeworkStream.stream_id.in_(by_stream))
            .order_by(Homework.due_at.desc())
            .limit(200)
        )
    ).all()
    enrolments = [e for _, _, e, _ in mine]
    subs = {
        (s.homework_id, s.enrolment_id): s
        for s in (
            await session.execute(select(HomeworkSubmission).where(HomeworkSubmission.enrolment_id.in_(enrolments)))
        ).scalars()
    }
    names = await _file_names(session, [h.file_id for h, _, _ in rows] + [s.file_id for s in subs.values()])
    out = []
    for h, subject, stream in rows:
        for student_id, name, enrolment, _ in by_stream[stream]:
            sub = subs.get((h.id, enrolment))
            out.append(
                StudentHomework(
                    id=h.id,
                    student_id=student_id,
                    student_name=name,
                    subject=_subject_name(subject, principal),
                    title=h.title,
                    instructions=h.instructions,
                    file_name=names.get(h.file_id),
                    max_score=h.max_score,
                    due_at=h.due_at,
                    overdue=sub is None and _late(h.due_at),
                    submission=_submission_out(sub, names),
                )
            )
    return out


async def submit(
    session: AsyncSession, principal: Principal, homework_id: uuid.UUID, body: SubmissionIn
) -> MySubmission:
    if not principal.has("portal.student"):
        raise forbidden()
    item = await _live_homework(session, homework_id)
    streams = await _target_streams(session, HomeworkStream, item.id)
    enrolment = next((e for _, _, e, stream in await my_students(session, principal) if stream in streams), None)
    if enrolment is None:
        raise not_found()
    if body.file_id:
        await _own_upload(session, principal, body.file_id, FilePurpose.SUBMISSION)
    existing = (
        await session.execute(
            select(HomeworkSubmission)
            .where(HomeworkSubmission.homework_id == item.id, HomeworkSubmission.enrolment_id == enrolment)
            .with_for_update()
        )
    ).scalar_one_or_none()
    if existing is not None and existing.marked_at is not None:
        raise AppError(409, "NOT_ALLOWED", [{"field": "homework_id", "code": "already_marked"}])
    late = _late(item.due_at)
    if existing is not None and late:
        raise AppError(409, "NOT_ALLOWED", [{"field": "homework_id", "code": "past_due"}])  # first answer stands
    if existing is None:
        existing = HomeworkSubmission(
            school_id=principal.school_id, homework_id=item.id, enrolment_id=enrolment, created_by=principal.user_id
        )
        session.add(existing)
    existing.body, existing.file_id = body.body, body.file_id
    existing.submitted_at, existing.is_late = now(), late
    await session.commit()
    return _submission_out(existing, await _file_names(session, [existing.file_id]))


async def mark(session: AsyncSession, principal: Principal, submission_id: uuid.UUID, body: MarkIn) -> MySubmission:
    sub = await session.get(HomeworkSubmission, submission_id, with_for_update=True)
    if sub is None:
        raise not_found()
    item = await _live_homework(session, sub.homework_id)
    stream = (await session.execute(select(Enrolment.stream_id).where(Enrolment.id == sub.enrolment_id))).scalar_one()
    if not await _may_mark(session, principal, item, stream):
        raise forbidden()
    if body.score is not None and (item.max_score is None or body.score > item.max_score):
        raise AppError(422, "VALIDATION_ERROR", [{"field": "score", "code": "above_max"}])
    sub.score, sub.feedback = body.score, body.feedback
    sub.marked_by, sub.marked_at = await own_staff_id(session, principal), now()
    await session.commit()
    return _submission_out(sub, await _file_names(session, [sub.file_id]))


async def homework_file(
    session: AsyncSession, principal: Principal, homework_id: uuid.UUID
) -> tuple[StoredFile, bytes]:
    item = await _live_homework(session, homework_id)
    if item.file_id is None:
        raise not_found()
    streams = await _target_streams(session, HomeworkStream, item.id)
    if not await _may_open(session, principal, streams, "homework.manage"):
        raise not_found()
    upload = await session.get(StoredFile, item.file_id)
    return upload, get_storage().get(upload.storage_key)


async def submission_file(
    session: AsyncSession, principal: Principal, submission_id: uuid.UUID
) -> tuple[StoredFile, bytes]:
    sub = await session.get(HomeworkSubmission, submission_id)
    if sub is None or sub.file_id is None:
        raise not_found()
    item = await _live_homework(session, sub.homework_id)
    stream = (await session.execute(select(Enrolment.stream_id).where(Enrolment.id == sub.enrolment_id))).scalar_one()
    own = any(e == sub.enrolment_id for _, _, e, _ in await my_students(session, principal))
    if not own and not await _may_mark(session, principal, item, stream):
        raise not_found()
    upload = await session.get(StoredFile, sub.file_id)
    return upload, get_storage().get(upload.storage_key)


async def remove_homework(session: AsyncSession, principal: Principal, homework_id: uuid.UUID) -> None:
    item = await _live_homework(session, homework_id)
    if not principal.has(OFFICE) and item.set_by != await own_staff_id(session, principal):
        raise forbidden()
    item.deleted_at = now()
    await session.commit()


# ---------------------------------------------------------------- lesson attendance


async def _slot_for(
    session: AsyncSession, principal: Principal, slot_id: uuid.UUID, day: date
) -> tuple[TimetableSlot, Term]:
    slot = await session.get(TimetableSlot, slot_id)
    if slot is None or slot.deleted_at is not None:
        raise not_found()
    if not principal.has(OFFICE) and slot.staff_id != await own_staff_id(session, principal):
        raise forbidden()
    term = await session.get(Term, slot.term_id)
    if day.isoweekday() != slot.day_of_week or not term.start_date <= day <= term.end_date:
        raise AppError(422, "VALIDATION_ERROR", [{"field": "date", "code": "not_this_lesson"}])
    return slot, term


async def my_lessons(session: AsyncSession, principal: Principal, day: date) -> list[LessonOut]:
    staff_id = await own_staff_id(session, principal)
    if staff_id is None:
        return []
    slots = (
        await session.execute(
            select(TimetableSlot, Subject)
            .join(Term, Term.id == TimetableSlot.term_id)
            .join(Subject, Subject.id == TimetableSlot.subject_id)
            .where(
                TimetableSlot.staff_id == staff_id,
                TimetableSlot.deleted_at.is_(None),
                TimetableSlot.day_of_week == day.isoweekday(),
                Term.start_date <= day,
                Term.end_date >= day,
            )
            .order_by(TimetableSlot.time_start)
        )
    ).all()
    if not slots:
        return []
    labels = await stream_labels(session, {s.stream_id for s, _ in slots})
    year = (await session.execute(select(Term.academic_year_id).where(Term.id == slots[0][0].term_id))).scalar_one()
    expected = dict(
        (
            await session.execute(
                select(Enrolment.stream_id, func.count())
                .where(
                    Enrolment.stream_id.in_({s.stream_id for s, _ in slots}),
                    Enrolment.academic_year_id == year,
                    Enrolment.status == EnrolmentStatus.ACTIVE,
                )
                .group_by(Enrolment.stream_id)
            )
        ).all()
    )
    marked = dict(
        (
            await session.execute(
                select(AttendanceSession.timetable_slot_id, func.count(AttendanceRecord.id))
                .join(AttendanceRecord, AttendanceRecord.session_id == AttendanceSession.id)
                .where(
                    AttendanceSession.kind == SessionKind.LESSON,
                    AttendanceSession.session_date == day,
                    AttendanceSession.timetable_slot_id.in_([s.id for s, _ in slots]),
                )
                .group_by(AttendanceSession.timetable_slot_id)
            )
        ).all()
    )
    return [
        LessonOut(
            slot_id=s.id,
            time_start=s.time_start,
            time_end=s.time_end,
            subject=_subject_name(subject, principal),
            stream=labels[s.stream_id],
            marked=marked.get(s.id, 0),
            expected=expected.get(s.stream_id, 0),
        )
        for s, subject in slots
    ]


async def lesson_register(
    session: AsyncSession, principal: Principal, slot_id: uuid.UUID, day: date
) -> list[LessonMarkRow]:
    slot, term = await _slot_for(session, principal, slot_id, day)
    statuses = dict(
        (
            await session.execute(
                select(AttendanceRecord.student_id, AttendanceRecord.status)
                .join(AttendanceSession, AttendanceSession.id == AttendanceRecord.session_id)
                .where(
                    AttendanceSession.kind == SessionKind.LESSON,
                    AttendanceSession.session_date == day,
                    AttendanceSession.timetable_slot_id == slot.id,
                )
            )
        ).all()
    )
    return [
        LessonMarkRow(student_id=sid, admission_no=no, full_name=name, status=statuses.get(sid))
        for sid, no, name, _, _ in await _enrolled(session, [slot.stream_id], term.academic_year_id)
    ]


async def save_lesson(
    session: AsyncSession, principal: Principal, slot_id: uuid.UUID, day: date, body: LessonIn
) -> None:
    slot, term = await _slot_for(session, principal, slot_id, day)
    if day > calendar.today():
        raise AppError(422, "VALIDATION_ERROR", [{"field": "date", "code": "future_date"}])
    if await calendar.closed_reason(session, day):
        raise AppError(422, "VALIDATION_ERROR", [{"field": "date", "code": "school_closed"}])
    enrolled = {sid for sid, *_ in await _enrolled(session, [slot.stream_id], term.academic_year_id)}
    if any(m.student_id not in enrolled for m in body.marks):
        raise AppError(422, "INVALID_REFERENCE", [{"field": "student_id", "code": "not_in_class"}])
    await session.execute(
        insert(AttendanceSession)
        .values(
            id=uuid.uuid4(),
            school_id=principal.school_id,
            session_date=day,
            kind=SessionKind.LESSON,
            timetable_slot_id=slot.id,  # the stream comes from the slot (ck_as_scope)
            taken_by=principal.user_id,
            created_by=principal.user_id,
        )
        .on_conflict_do_nothing(constraint="uq_attendance_sessions")
    )
    lesson = (
        await session.execute(
            select(AttendanceSession)
            .where(
                AttendanceSession.kind == SessionKind.LESSON,
                AttendanceSession.session_date == day,
                AttendanceSession.timetable_slot_id == slot.id,
            )
            .with_for_update()
        )
    ).scalar_one()
    moment = now()
    for m in body.marks:
        await session.execute(
            insert(AttendanceRecord)
            .values(
                id=uuid.uuid4(),
                school_id=principal.school_id,
                session_id=lesson.id,
                student_id=m.student_id,
                status=m.status,
                captured_at=moment,
                client_record_id=uuid.uuid4(),
                recorded_by=principal.user_id,
                created_by=principal.user_id,
            )
            .on_conflict_do_update(
                constraint="uq_attendance_records",
                set_={"status": m.status, "recorded_by": principal.user_id, "captured_at": moment},
            )
        )
    await session.commit()


# ---------------------------------------------------------------- monthly sheet


async def monthly_sheet(session: AsyncSession, stream_id: uuid.UUID, year: int, month: int) -> MonthlySheet:
    first, last = date(year, month, 1), date(year, month, monthrange(year, month)[1])
    label = (await stream_labels(session, [stream_id])).get(stream_id)
    if label is None:
        raise not_found()
    school_year = (
        await session.execute(
            select(Term.academic_year_id).where(
                Term.start_date <= last, Term.end_date >= first, Term.deleted_at.is_(None)
            )
        )
    ).scalar()
    records = (
        await session.execute(
            select(AttendanceSession.session_date, AttendanceRecord.student_id, AttendanceRecord.status)
            .join(AttendanceRecord, AttendanceRecord.session_id == AttendanceSession.id, isouter=True)
            .where(
                AttendanceSession.kind == SessionKind.REGISTER,
                AttendanceSession.stream_id == stream_id,
                AttendanceSession.session_date.between(first, last),
            )
        )
    ).all()
    days = sorted({d for d, _, _ in records})
    marks: dict[uuid.UUID, dict[str, str]] = {}
    for day, student, status in records:
        if student is not None:
            marks.setdefault(student, {})[day.isoformat()] = CODES[str(status)]
    students = await _enrolled(session, [stream_id], school_year) if school_year else []
    rows = []
    for sid, no, name, _, _ in students:
        mine = marks.get(sid, {})
        values = list(mine.values())
        rows.append(
            SheetRow(
                student_id=sid,
                admission_no=no,
                full_name=name,
                marks=mine,
                present=values.count("P"),
                absent=values.count("A"),
                late=values.count("L"),
                excused=values.count("E"),
            )
        )
    return MonthlySheet(stream=label, year=year, month=month, days=days, rows=rows)
