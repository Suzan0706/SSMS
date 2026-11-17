"""Report-card PDFs (design 13-io-specifications O-01) and the results-ready SMS.

A single student's card is rendered on request from the current (possibly amended) results, so it is never stale.
The REPORT_CARDS job renders the whole class into one printable PDF and, on first publication, queues one SMS per
primary guardian who agreed to receive SMS (the idempotency key prevents duplicates if the job runs again).
"""

import io
import json
import uuid
from datetime import UTC, datetime

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.units import mm
from reportlab.pdfgen import canvas
from sqlalchemy import and_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import Principal
from app.core.storage import get_storage
from app.db.session import DbContext, school_session, set_context
from app.models import (
    BackgroundJob,
    Guardian,
    MessageTemplate,
    ResultPublication,
    School,
    SchoolSettings,
    SmsMessage,
    StudentGuardian,
    StudentTermSummary,
    User,
)
from app.models.enums import JobKind, JobStatus, UserStatus
from app.schemas.results import StudentResultsOut
from app.services import imports, results, sms
from app.services.onboarding import TEMPLATES
from app.services.people import decrypt_phone
from app.tasks.dispatch import get_dispatcher

LABELS = {
    "title": ("RIPOTI YA MAENDELEO YA MWANAFUNZI", "STUDENT PROGRESS REPORT"),
    "name": ("Jina", "Name"),
    "number": ("Namba", "Adm. no"),
    "class": ("Darasa", "Class"),
    "term": ("Muhula", "Term"),
    "subject": ("Somo", "Subject"),
    "total": ("Jumla", "Total"),
    "grade": ("Daraja", "Grade"),
    "points": ("Pointi", "Points"),
    "position": ("Nafasi", "Position"),
    "remark": ("Maoni", "Remark"),
    "average": ("Wastani", "Average"),
    "division": ("Daraja la ufaulu", "Division"),
    "best": ("bora", "best"),
    "class_position": ("Nafasi darasani", "Class position"),
    "of": ("kati ya", "of"),
    "attendance": ("Mahudhurio", "Attendance"),
    "class_teacher": ("Mwalimu wa darasa", "Class teacher"),
    "head_teacher": ("Mkuu wa shule", "Head teacher"),
    "stamp": ("Muhuri", "Stamp"),
    "amended": ("Imerekebishwa", "Amended"),
    "scheme": ("Mfumo wa madaraja", "Grading scheme"),
}


COMPONENT_SHORT = {  # column headers must fit 16 mm: CA(30) Kati(20) Muhula(50)
    "CA": ("CA", "CA"),
    "TEST": ("Jaribio", "Test"),
    "MIDTERM": ("Kati", "Mid"),
    "TERMINAL": ("Muhula", "Term"),
    "ANNUAL": ("Mwaka", "Annual"),
    "PROJECT": ("Mradi", "Project"),
    "PRACTICAL": ("Vitendo", "Practical"),
}


def _l(key: str, lang: str) -> str:
    sw, en = LABELS[key]
    return f"{sw} / {en}" if lang == "both" else (sw if lang == "sw" else en)


def _fmt(value) -> str:
    return "" if value is None else f"{float(value):.1f}"


def _draw(c: canvas.Canvas, card: StudentResultsOut, school: dict, lang: str) -> None:
    width, height = A4
    y = height - 18 * mm
    c.setFont("Helvetica-Bold", 13)
    c.drawCentredString(width / 2, y, school["name"].upper())
    c.setFont("Helvetica", 9)
    line = " · ".join(p for p in (school.get("postal_address"), school.get("motto") and f'"{school["motto"]}"') if p)
    if line:
        y -= 5 * mm
        c.drawCentredString(width / 2, y, line)
    y -= 8 * mm
    c.setFont("Helvetica-Bold", 11)
    c.drawCentredString(width / 2, y, _l("title", "both"))
    c.setFont("Helvetica", 8)
    c.drawRightString(width - 15 * mm, y - 5 * mm, f"Ref: {card.admission_no}/{card.academic_year}")

    y -= 14 * mm
    c.setFont("Helvetica", 9.5)
    term = card.term_name_sw if lang == "sw" else card.term_name_en
    class_name = card.class_name_sw if lang == "sw" else card.class_name_en
    c.drawString(15 * mm, y, f"{_l('name', lang)}: {card.full_name.upper()}")
    c.drawString(110 * mm, y, f"{_l('number', lang)}: {card.admission_no}")
    y -= 5.5 * mm
    c.drawString(15 * mm, y, f"{_l('class', lang)}: {class_name} {card.stream_name}")
    c.drawString(110 * mm, y, f"{_l('term', lang)}: {term} {card.academic_year}")

    codes: list[tuple[str, float]] = []
    for subject in card.subjects:
        for comp in subject.components:
            if comp.code not in [code for code, _ in codes]:
                codes.append((comp.code, float(comp.weight)))
    columns = (
        [("subject", 52)]
        + [(code, 16) for code, _ in codes]
        + [("total", 15), ("grade", 13), ("points", 13), ("position", 16), ("remark", 28)]
    )
    y -= 9 * mm
    x = 15 * mm
    c.setFillColor(colors.HexColor("#e8f3ee"))
    c.rect(15 * mm, y - 2 * mm, sum(w for _, w in columns) * mm, 6.5 * mm, fill=1, stroke=0)
    c.setFillColor(colors.black)
    c.setFont("Helvetica-Bold", 8)
    for key, w in columns:
        if key in dict(codes):
            short = COMPONENT_SHORT.get(key, (key, key))[0 if lang == "sw" else 1]
            label = f"{short}({int(dict(codes)[key])})"
        else:
            label = _l(key, lang)
        c.drawString(x + 1 * mm, y, label)
        x += w * mm
    c.setFont("Helvetica", 8.5)
    for subject in card.subjects:
        y -= 6 * mm
        x = 15 * mm
        name = subject.subject_name_sw if lang == "sw" else subject.subject_name_en
        by_code = {comp.code: comp for comp in subject.components}
        cells = [name + (" *" if subject.amended else "")]
        for code, _ in codes:
            comp = by_code.get(code)
            if comp is None:
                cells.append("")
            elif comp.is_absent:
                cells.append("ABS")
            else:
                cells.append(_fmt(float(comp.score or 0) / float(comp.max_score) * float(comp.weight)))
        cells += [
            _fmt(subject.final_score),
            subject.letter_grade,
            str(subject.points),
            f"{subject.subject_position}/{subject.out_of}",
            (subject.remark_sw if lang == "sw" else subject.remark_en) or "",
        ]
        for (key, w), value in zip(columns, cells, strict=True):
            c.drawString(x + 1 * mm, y, value[:30] if key == "subject" else value)
            x += w * mm
    y -= 3 * mm
    c.line(15 * mm, y, 15 * mm + sum(w for _, w in columns) * mm, y)

    s = card.summary
    y -= 7 * mm
    c.setFont("Helvetica-Bold", 9)
    best = (
        f"{_l('points', lang)} ({_l('best', lang)} {s.best_n_subjects}) {s.total_points}" if s.best_n_subjects else ""
    )
    c.drawString(
        15 * mm,
        y,
        f"{_l('average', lang)} {_fmt(s.average_score)}   {best}   "
        f"{_l('division', lang)}: {s.division or '—'}   "
        f"{_l('class_position', lang)} {s.class_position} {_l('of', lang)} {s.class_size}",
    )
    y -= 6 * mm
    c.setFont("Helvetica", 9)
    att = card.attendance
    percent = f" ({round(att.present * 100 / att.sessions)}%)" if att.sessions else ""
    c.drawString(15 * mm, y, f"{_l('attendance', lang)}: {att.present}/{att.sessions}{percent}")

    for key, text in (
        ("class_teacher", card.comments.class_teacher_comment),
        ("head_teacher", card.comments.head_teacher_comment),
    ):
        y -= 10 * mm
        c.setFont("Helvetica-Bold", 9)
        c.drawString(15 * mm, y, f"{_l(key, lang)}:")
        c.setFont("Helvetica", 9)
        c.drawString(55 * mm, y, (text or "")[:95])
        c.line(150 * mm, y - 1 * mm, 190 * mm, y - 1 * mm)
    y -= 12 * mm
    c.drawString(150 * mm, y, _l("stamp", lang))
    c.setFont("Helvetica", 7.5)
    footer = [f"{_l('scheme', lang)}: {card.scheme_name} (v{card.scheme_version})"]
    if card.amended_at:
        footer.append(f"* {_l('amended', 'both')} {card.amended_at:%d/%m/%Y}")
    for i, line in enumerate(footer):
        c.drawString(15 * mm, 15 * mm + i * 4 * mm, line)


async def school_header(session: AsyncSession) -> dict:
    name = (await session.execute(select(School.name))).scalar_one()
    settings = (
        await session.execute(
            select(SchoolSettings.motto, SchoolSettings.postal_address, SchoolSettings.default_language)
        )
    ).first()
    return {
        "name": name,
        "motto": settings.motto if settings else None,
        "postal_address": settings.postal_address if settings else None,
        "language": settings.default_language if settings else "sw",
    }


def render(cards: list[StudentResultsOut], school: dict, lang: str) -> bytes:
    out = io.BytesIO()
    c = canvas.Canvas(out, pagesize=A4, pageCompression=1)
    c.setTitle("Report cards")
    for card in cards:
        _draw(c, card, school, lang)
        c.showPage()
    c.save()
    return out.getvalue()


async def single(
    session: AsyncSession, principal: Principal, student_id: uuid.UUID, term_id: uuid.UUID, lang: str
) -> tuple[StudentResultsOut, bytes]:
    card = await results.student_results(session, principal, student_id, term_id)
    return card, render([card], await school_header(session), lang)


# ---------------------------------------------------------------- the class job


def queue(session: AsyncSession, principal: Principal, publication_id: uuid.UUID, notify: bool) -> BackgroundJob:
    job = BackgroundJob(
        school_id=principal.school_id,
        kind=JobKind.REPORT_CARDS,
        status=JobStatus.QUEUED,
        requested_by=principal.user_id,
        created_by=principal.user_id,
    )
    job.input_file_key = get_storage().put(
        f"{principal.school_id}/report-cards/{publication_id}/{job.id}.json",
        json.dumps({"publication_id": str(publication_id), "notify": notify}).encode(),
    )
    session.add(job)
    return job


async def _notify(session: AsyncSession, school_id: uuid.UUID, publication: ResultPublication, cards) -> list[dict]:
    calls = []
    school = (await session.execute(select(School.name))).scalar_one()
    for card in cards:
        guardian = (
            await session.execute(
                select(User)
                .join(Guardian, Guardian.user_id == User.id)
                .join(
                    StudentGuardian,
                    and_(StudentGuardian.guardian_id == Guardian.id, StudentGuardian.student_id == card.student_id),
                )
                .where(
                    StudentGuardian.is_primary.is_(True),
                    StudentGuardian.receives_sms.is_(True),
                    StudentGuardian.deleted_at.is_(None),
                    User.status == UserStatus.ACTIVE,
                )
            )
        ).scalar_one_or_none()
        phone = decrypt_phone(guardian) if guardian else None
        if not phone:
            continue
        lang = guardian.preferred_language
        template = (
            await session.execute(
                select(MessageTemplate.body).where(
                    MessageTemplate.key == "results_ready",
                    MessageTemplate.language == lang,
                    MessageTemplate.is_active.is_(True),
                    MessageTemplate.deleted_at.is_(None),
                )
            )
        ).scalar()
        template = template or TEMPLATES["results_ready"][0 if lang == "sw" else 1]
        term = card.term_name_sw if lang == "sw" else card.term_name_en
        body = template.format(school=school[:40], student=card.full_name.split()[0], term=term)
        key = f"results:{publication.id.hex}:{card.enrolment_id.hex}"  # fits VARCHAR(80)
        exists = (await session.execute(select(SmsMessage.id).where(SmsMessage.idempotency_key == key))).first()
        if exists:
            continue
        message = await sms.queue_sms(
            session,
            school_id=school_id,
            phone=phone,
            body=body,
            language=lang,
            to_user_id=guardian.id,
            template_key="results_ready",
            idempotency_key=key,
            related_entity="result_publications",
            related_id=publication.id,
        )
        calls.append({"sms_id": str(message.id), "school_id": str(school_id)})
    return calls


async def run_job(job_id: str, school_id: str) -> str:
    job_uuid, school_uuid = uuid.UUID(job_id), uuid.UUID(school_id)
    async with school_session(school_uuid) as session:
        job = (
            await session.execute(
                select(BackgroundJob)
                .where(BackgroundJob.id == job_uuid, BackgroundJob.kind == JobKind.REPORT_CARDS)
                .with_for_update()
            )
        ).scalar_one_or_none()
        if job is None or job.status != JobStatus.QUEUED:
            return "skipped"
        job.status, job.started_at = JobStatus.RUNNING, datetime.now(UTC)
        await session.commit()
        await set_context(session, DbContext(school_id=school_uuid, user_id=job.requested_by))
        params = json.loads(get_storage().get(job.input_file_key))
        publication = (
            await session.execute(
                select(ResultPublication).where(ResultPublication.id == uuid.UUID(params["publication_id"]))
            )
        ).scalar_one()
        enrolments = (
            (
                await session.execute(
                    results.current_summaries()
                    .with_only_columns(StudentTermSummary.enrolment_id)
                    .where(StudentTermSummary.publication_id == publication.id)
                    .order_by(StudentTermSummary.class_position)
                )
            )
            .scalars()
            .all()
        )
        cards = [await results.results_for_enrolment(session, publication, e) for e in enrolments]
        school = await school_header(session)
        key = f"{school_uuid}/report-cards/{publication.id}/class.pdf"
        get_storage().put(key, render(cards, school, school["language"]))
        calls = await _notify(session, school_uuid, publication, cards) if params.get("notify") else []
        job.result_file_key, job.total_items, job.processed_items = key, len(cards), len(cards)
        imports.finish_job(job, JobStatus.SUCCEEDED)
        await session.commit()
    for call in calls:
        get_dispatcher().send("sms.send", **call)
    return "succeeded"
