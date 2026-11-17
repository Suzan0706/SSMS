"""Candidate numbers, admit cards and the exam timetable (FR-84, FR-85), and subject ranking (FR-86).

The school's NECTA centre number is taken from schools.registration_no (VERIFY the format with NECTA). GPA is not
computed here: the A-Level GPA rule is still marked VERIFY in design/19 §19.3 (D9).
"""

import io
import uuid
from datetime import date

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.units import mm
from reportlab.pdfgen import canvas
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import Principal
from app.core.errors import AppError, not_found
from app.models import (
    Enrolment,
    Exam,
    ExamCandidate,
    ExamSession,
    PublishedResult,
    ResultPublication,
    Room,
    School,
    SchoolClass,
    Stream,
    Student,
    Subject,
    Term,
    User,
)
from app.models.enums import EnrolmentStatus
from app.services.results import _superseded

FULL_NAME = func.concat_ws(" ", User.first_name, User.middle_name, User.last_name)


async def _session(session: AsyncSession, exam_session_id: uuid.UUID) -> ExamSession:
    item = await session.get(ExamSession, exam_session_id)
    if item is None or item.deleted_at is not None:
        raise not_found()
    return item


async def _papers(session: AsyncSession, exam_session_id: uuid.UUID, class_id: uuid.UUID | None = None):
    stmt = (
        select(Exam, Subject, SchoolClass.code, Room.name)
        .join(Subject, Subject.id == Exam.subject_id)
        .join(SchoolClass, SchoolClass.id == Exam.class_id)
        .outerjoin(Room, Room.id == Exam.room_id)
        .where(Exam.exam_session_id == exam_session_id, Exam.deleted_at.is_(None))
        .order_by(Exam.exam_date, Exam.time_start, SchoolClass.sort_order)
    )
    if class_id:
        stmt = stmt.where(Exam.class_id == class_id)
    return (await session.execute(stmt)).all()


async def _candidates_query(session: AsyncSession, item: ExamSession, class_id: uuid.UUID | None = None):
    """Students sitting the session: active enrolments of the year, in classes that have a paper in it."""
    year = (await session.execute(select(Term.academic_year_id).where(Term.id == item.term_id))).scalar_one()
    classes = select(Exam.class_id).where(Exam.exam_session_id == item.id, Exam.deleted_at.is_(None))
    stmt = (
        select(
            Enrolment.id,
            Student.admission_no,
            FULL_NAME,
            SchoolClass.id,
            SchoolClass.code,
            Stream.name,
            ExamCandidate.candidate_no,
        )
        .join(Student, Student.id == Enrolment.student_id)
        .join(User, User.id == Student.user_id)
        .join(Stream, Stream.id == Enrolment.stream_id)
        .join(SchoolClass, SchoolClass.id == Stream.class_id)
        .outerjoin(
            ExamCandidate,
            (ExamCandidate.enrolment_id == Enrolment.id) & (ExamCandidate.exam_session_id == item.id),
        )
        .where(
            Enrolment.academic_year_id == year,
            Enrolment.status == EnrolmentStatus.ACTIVE,
            SchoolClass.id.in_(classes),
        )
        .order_by(SchoolClass.sort_order, Stream.name, User.last_name, User.first_name)
    )
    if class_id:
        stmt = stmt.where(SchoolClass.id == class_id)
    return (await session.execute(stmt)).all()


async def candidates(session: AsyncSession, exam_session_id: uuid.UUID, class_id: uuid.UUID | None) -> list[dict]:
    item = await _session(session, exam_session_id)
    return [
        {
            "enrolment_id": e,
            "admission_no": no,
            "full_name": name,
            "class_code": code,
            "stream": stream,
            "candidate_no": cand,
        }
        for e, no, name, _, code, stream, cand in await _candidates_query(session, item, class_id)
    ]


async def number_candidates(
    session: AsyncSession, principal: Principal, exam_session_id: uuid.UUID, prefix: str | None, start: int
) -> int:
    """Give a number to every candidate who has none, in class, stream and name order. Existing numbers are kept,
    so numbering again after late admissions only adds. Returns how many were numbered."""
    item = await _session(session, exam_session_id)
    if prefix is None:
        prefix = ((await session.execute(select(School.registration_no))).scalar() or "") + "-"
    rows = await _candidates_query(session, item)
    taken = set(
        (
            await session.execute(select(ExamCandidate.candidate_no).where(ExamCandidate.exam_session_id == item.id))
        ).scalars()
    )
    added, n = 0, start
    for enrolment_id, *_rest, existing in rows:
        if existing:
            continue
        while f"{prefix}{n:04d}" in taken:
            n += 1
        number = f"{prefix}{n:04d}"
        if len(number) > 20:
            raise AppError(422, "VALIDATION_ERROR", [{"field": "prefix", "code": "too_long"}])
        session.add(
            ExamCandidate(
                school_id=principal.school_id,
                exam_session_id=item.id,
                enrolment_id=enrolment_id,
                candidate_no=number,
                created_by=principal.user_id,
            )
        )
        taken.add(number)
        added += 1
        n += 1
    await session.commit()
    return added


async def _school(session: AsyncSession) -> tuple[str, str | None]:
    return tuple((await session.execute(select(School.name, School.registration_no))).one())


def _name(item: ExamSession, lang: str) -> str:
    return item.name_en if lang == "en" else item.name_sw


def _subject(subject: Subject, lang: str) -> str:
    return subject.name_en if lang == "en" else subject.name_sw


L = {
    "admit": ("KADI YA KUINGIA MTIHANI", "EXAMINATION ADMIT CARD"),
    "timetable": ("RATIBA YA MITIHANI", "EXAMINATION TIMETABLE"),
    "candidate": ("Namba ya mtahiniwa", "Candidate no."),
    "name": ("Jina", "Name"),
    "class": ("Darasa", "Class"),
    "centre": ("Kituo", "Centre"),
    "date": ("Tarehe", "Date"),
    "time": ("Muda", "Time"),
    "subject": ("Somo", "Subject"),
    "room": ("Chumba", "Room"),
    "sign": ("Sahihi ya mkuu wa shule", "Head of school's signature"),
}


def _t(key: str, lang: str) -> str:
    return L[key][1] if lang == "en" else L[key][0]


def _admit_card(c: canvas.Canvas, top: float, school, item, student, papers, lang: str) -> None:
    width = A4[0]
    left, right = 15 * mm, width - 15 * mm
    c.setStrokeColor(colors.HexColor("#312e81"))
    c.setLineWidth(1.2)
    c.rect(left, top - 135 * mm, right - left, 130 * mm)
    y = top - 13 * mm
    c.setFont("Helvetica-Bold", 12)
    c.drawCentredString(width / 2, y, school[0].upper())
    y -= 6 * mm
    c.setFont("Helvetica-Bold", 10)
    c.drawCentredString(width / 2, y, f"{_t('admit', lang)} · {_name(item, lang)}")
    y -= 10 * mm
    _no, name, code, stream, cand = student
    c.setFont("Helvetica", 9)
    for label, value in (
        (_t("candidate", lang), cand or "—"),
        (_t("name", lang), name),
        (_t("class", lang), f"{code} {stream}"),
        (_t("centre", lang), school[1] or "—"),
    ):
        c.drawString(left + 6 * mm, y, f"{label}:")
        c.setFont("Helvetica-Bold", 10)
        c.drawString(left + 42 * mm, y, str(value))
        c.setFont("Helvetica", 9)
        y -= 6 * mm
    y -= 2 * mm
    c.setFont("Helvetica-Bold", 8)
    columns = (left + 6 * mm, left + 36 * mm, left + 62 * mm, left + 140 * mm)
    for x, key in zip(columns, ("date", "time", "subject", "room"), strict=True):
        c.drawString(x, y, _t(key, lang))
    c.setFont("Helvetica", 8)
    for exam, subject, _code, room in papers[:12]:
        y -= 5 * mm
        c.drawString(columns[0], y, exam.exam_date.strftime("%d/%m/%Y"))
        c.drawString(columns[1], y, f"{exam.time_start:%H:%M}-{exam.time_end:%H:%M}")
        c.drawString(columns[2], y, _subject(subject, lang)[:45])
        c.drawString(columns[3], y, (room or "—")[:20])
    c.setFont("Helvetica", 8)
    c.drawString(right - 70 * mm, top - 128 * mm, f"{_t('sign', lang)}: ____________________")


async def admit_cards_pdf(
    session: AsyncSession,
    exam_session_id: uuid.UUID,
    lang: str,
    class_id: uuid.UUID | None = None,
    enrolment_id: uuid.UUID | None = None,
) -> bytes:
    """Two cards per A4 page. Only numbered candidates get a card."""
    item = await _session(session, exam_session_id)
    school = await _school(session)
    rows = [r for r in await _candidates_query(session, item, class_id) if r[6]]
    if enrolment_id:
        rows = [r for r in rows if r[0] == enrolment_id]
    if not rows:
        raise AppError(409, "NOT_ALLOWED", [{"field": "exam_session_id", "code": "no_candidate_numbers"}])
    papers_by_class: dict[uuid.UUID, list] = {}
    out = io.BytesIO()
    c = canvas.Canvas(out, pagesize=A4, pageCompression=1)
    c.setTitle("Admit cards")
    height = A4[1]
    for index, (_e, no, name, class_id_, code, stream, cand) in enumerate(rows):
        if class_id_ not in papers_by_class:
            papers_by_class[class_id_] = await _papers(session, item.id, class_id_)
        top = height - 10 * mm if index % 2 == 0 else height / 2 - 2 * mm
        _admit_card(c, top, school, item, (no, name, code, stream, cand), papers_by_class[class_id_], lang)
        if index % 2 == 1:
            c.showPage()
    if len(rows) % 2 == 1:
        c.showPage()
    c.save()
    return out.getvalue()


async def timetable_pdf(session: AsyncSession, exam_session_id: uuid.UUID, lang: str) -> bytes:
    item = await _session(session, exam_session_id)
    school = await _school(session)
    papers = await _papers(session, item.id)
    out = io.BytesIO()
    c = canvas.Canvas(out, pagesize=A4, pageCompression=1)
    c.setTitle("Exam timetable")
    width, height = A4
    columns = (15 * mm, 42 * mm, 70 * mm, 90 * mm, 160 * mm)

    def header() -> float:
        y = height - 18 * mm
        c.setFont("Helvetica-Bold", 13)
        c.drawCentredString(width / 2, y, school[0].upper())
        y -= 6 * mm
        c.setFont("Helvetica-Bold", 11)
        centre = f" · {_t('centre', lang)} {school[1]}" if school[1] else ""
        c.drawCentredString(width / 2, y, f"{_t('timetable', lang)} · {_name(item, lang)}{centre}")
        y -= 10 * mm
        c.setFont("Helvetica-Bold", 9)
        for x, key in zip(columns, ("date", "time", "class", "subject", "room"), strict=True):
            c.drawString(x, y, _t(key, lang))
        c.line(15 * mm, y - 2 * mm, width - 15 * mm, y - 2 * mm)
        return y - 7 * mm

    y = header()
    c.setFont("Helvetica", 9)
    last_day: date | None = None
    for exam, subject, code, room in papers:
        if y < 20 * mm:
            c.showPage()
            y = header()
            c.setFont("Helvetica", 9)
        if last_day and exam.exam_date != last_day:
            y -= 2 * mm
        c.drawString(columns[0], y, exam.exam_date.strftime("%a %d/%m") if exam.exam_date != last_day else "")
        c.drawString(columns[1], y, f"{exam.time_start:%H:%M}-{exam.time_end:%H:%M}")
        c.drawString(columns[2], y, code)
        c.drawString(columns[3], y, _subject(subject, lang)[:40])
        c.drawString(columns[4], y, (room or "—")[:25])
        last_day = exam.exam_date
        y -= 6 * mm
    c.showPage()
    c.save()
    return out.getvalue()


async def my_sessions(session: AsyncSession, principal: Principal) -> list[dict]:
    """Exam sessions in which the signed-in student has a candidate number (so an admit card exists)."""
    rows = (
        await session.execute(
            select(ExamSession, ExamCandidate.candidate_no)
            .join(ExamCandidate, ExamCandidate.exam_session_id == ExamSession.id)
            .join(Enrolment, Enrolment.id == ExamCandidate.enrolment_id)
            .join(Student, Student.id == Enrolment.student_id)
            .where(Student.user_id == principal.user_id, ExamSession.deleted_at.is_(None))
            .order_by(ExamSession.start_date.desc())
        )
    ).all()
    return [
        {
            "id": s.id,
            "name": _name(s, principal.language),
            "start_date": s.start_date,
            "end_date": s.end_date,
            "candidate_no": no,
        }
        for s, no in rows
    ]


async def own_enrolment_in(session: AsyncSession, principal: Principal, exam_session_id: uuid.UUID) -> uuid.UUID:
    item = await _session(session, exam_session_id)
    year = (await session.execute(select(Term.academic_year_id).where(Term.id == item.term_id))).scalar_one()
    enrolment = (
        await session.execute(
            select(Enrolment.id)
            .join(Student, Student.id == Enrolment.student_id)
            .where(Student.user_id == principal.user_id, Enrolment.academic_year_id == year)
        )
    ).scalar_one_or_none()
    if enrolment is None:
        raise not_found()
    return enrolment


async def subject_ranking(
    session: AsyncSession, term_id: uuid.UUID, class_id: uuid.UUID, subject_id: uuid.UUID
) -> list[dict]:
    """A subject's published results for a class and term, best first; ties share the position given at publishing."""
    publication_id = (
        await session.execute(
            select(ResultPublication.id)
            .where(ResultPublication.term_id == term_id, ResultPublication.class_id == class_id)
            .order_by(ResultPublication.published_at.desc())
            .limit(1)
        )
    ).scalar()
    if publication_id is None:
        return []
    rows = (
        await session.execute(
            select(
                PublishedResult.subject_position,
                Student.admission_no,
                FULL_NAME,
                Stream.name,
                PublishedResult.final_score,
                PublishedResult.letter_grade,
            )
            .join(Enrolment, Enrolment.id == PublishedResult.enrolment_id)
            .join(Student, Student.id == Enrolment.student_id)
            .join(User, User.id == Student.user_id)
            .join(Stream, Stream.id == Enrolment.stream_id)
            .where(
                PublishedResult.publication_id == publication_id,
                PublishedResult.subject_id == subject_id,
                ~_superseded(PublishedResult),  # the current version after any amendment
            )
            .order_by(PublishedResult.subject_position, User.last_name)
        )
    ).all()
    return [
        {"position": p, "admission_no": no, "full_name": name, "stream": stream, "score": score, "grade": grade}
        for p, no, name, stream, score, grade in rows
    ]
