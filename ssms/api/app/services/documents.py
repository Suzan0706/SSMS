"""Certificates and ID cards (FR-94, FR-95).

Certificates: a template's text with {{placeholders}} is filled in and frozen at issue (database trigger), numbered
CT-YYYY-nnnnnn; it can only be revoked, once, with a reason. ID cards: one live card per person, numbered
ID-YYYY-nnnnnn; the QR code holds the card number only, never personal data.
"""

import io
import re
import textwrap
import uuid
from datetime import date, timedelta

from reportlab.graphics import renderPDF
from reportlab.graphics.barcode.qr import QrCodeWidget
from reportlab.graphics.shapes import Drawing
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4, landscape
from reportlab.lib.units import mm
from reportlab.lib.utils import ImageReader
from reportlab.pdfgen import canvas
from sqlalchemy import and_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import Principal
from app.core.errors import AppError, not_found
from app.core.storage import get_storage
from app.models import (
    AcademicYear,
    Certificate,
    CertificateTemplate,
    Designation,
    Enrolment,
    IdentityCard,
    School,
    SchoolClass,
    Staff,
    StoredFile,
    Stream,
    Student,
    User,
)
from app.models.enums import EnrolmentStatus, FilePurpose
from app.services import calendar, ledger
from app.services.people import now

PLACEHOLDER = re.compile(r"\{\{\s*([a-z_]+)\s*\}\}")
FIELDS = ("name", "admission_no", "class", "date_of_birth", "school", "issued_on", "year")
TITLES = {
    "LEAVING": ("CHETI CHA KUMALIZA MASOMO", "LEAVING CERTIFICATE"),
    "TRANSFER": ("CHETI CHA KUHAMA", "TRANSFER CERTIFICATE"),
    "CHARACTER": ("CHETI CHA TABIA", "CHARACTER CERTIFICATE"),
    "ACHIEVEMENT": ("CHETI CHA MAFANIKIO", "CERTIFICATE OF ACHIEVEMENT"),
}


def _current_year():
    return select(AcademicYear.id).where(AcademicYear.is_current.is_(True)).scalar_subquery()


async def _school(session: AsyncSession) -> tuple[str, str | None]:
    return tuple((await session.execute(select(School.name, School.registration_no))).one())


async def _file_bytes(session: AsyncSession, *, file_id=None, key: str | None = None) -> bytes | None:
    stmt = select(StoredFile.storage_key).where(StoredFile.deleted_at.is_(None))
    stmt = stmt.where(StoredFile.id == file_id) if file_id else stmt.where(StoredFile.storage_key == key)
    found = (await session.execute(stmt)).scalar_one_or_none() if (file_id or key) else None
    if not found:
        return None
    try:
        return get_storage().get(found)
    except OSError:
        return None


# ---------------------------------------------------------------- templates and certificates


async def templates(session: AsyncSession) -> list[CertificateTemplate]:
    return list(
        (
            await session.execute(
                select(CertificateTemplate)
                .where(CertificateTemplate.deleted_at.is_(None))
                .order_by(CertificateTemplate.name)
            )
        ).scalars()
    )


async def save_template(session: AsyncSession, principal: Principal, body, template_id=None) -> CertificateTemplate:
    unknown = set(PLACEHOLDER.findall(body.body)) - set(FIELDS)
    if unknown:
        raise AppError(
            422, "VALIDATION_ERROR", [{"field": "body", "code": "unknown_placeholder", "value": sorted(unknown)[0]}]
        )
    if body.background_file_id:
        upload = await session.get(StoredFile, body.background_file_id)
        if upload is None or upload.purpose != FilePurpose.CERT_TEMPLATE:
            raise AppError(422, "VALIDATION_ERROR", [{"field": "background_file_id", "code": "invalid_value"}])
    if template_id is None:
        item = CertificateTemplate(school_id=principal.school_id, created_by=principal.user_id, **body.model_dump())
        session.add(item)
    else:
        item = await session.get(CertificateTemplate, template_id)
        if item is None or item.deleted_at is not None:
            raise not_found()
        for key, value in body.model_dump().items():
            setattr(item, key, value)
    await session.commit()
    return item


async def _student_fields(session: AsyncSession, student_id: uuid.UUID) -> dict | None:
    row = (
        await session.execute(
            select(
                Student.admission_no,
                User.first_name,
                User.middle_name,
                User.last_name,
                User.date_of_birth,
                SchoolClass.code,
                Stream.name,
            )
            .join(User, User.id == Student.user_id)
            .outerjoin(
                Enrolment,
                and_(
                    Enrolment.student_id == Student.id,
                    Enrolment.academic_year_id == _current_year(),
                    Enrolment.status == EnrolmentStatus.ACTIVE,
                ),
            )
            .outerjoin(Stream, Stream.id == Enrolment.stream_id)
            .outerjoin(SchoolClass, SchoolClass.id == Stream.class_id)
            .where(Student.id == student_id, Student.deleted_at.is_(None))
        )
    ).first()
    if row is None:
        return None
    no, first, middle, last, dob, code, stream = row
    return {
        "name": " ".join(p for p in (first, middle, last) if p),
        "admission_no": no,
        "class": f"{code} {stream}" if code else "",
        "date_of_birth": dob.strftime("%d/%m/%Y") if dob else "",
    }


def render(text: str, values: dict) -> str:
    return PLACEHOLDER.sub(lambda m: str(values.get(m.group(1), "")), text)


async def issue(
    session: AsyncSession, principal: Principal, template_id, student_ids, issued_on: date
) -> list[Certificate]:
    template = await session.get(CertificateTemplate, template_id)
    if template is None or template.deleted_at is not None:
        raise AppError(422, "INVALID_REFERENCE", [{"field": "template_id", "code": "invalid_value"}])
    school, _ = await _school(session)
    issued = []
    for student_id in dict.fromkeys(student_ids):
        fields = await _student_fields(session, student_id)
        if fields is None:
            raise AppError(422, "INVALID_REFERENCE", [{"field": "student_ids", "code": "invalid_value"}])
        values = {**fields, "school": school, "issued_on": issued_on.strftime("%d/%m/%Y"), "year": str(issued_on.year)}
        item = Certificate(
            school_id=principal.school_id,
            template_id=template.id,
            student_id=student_id,
            serial_no=await ledger.next_number(session, principal.school_id, "CERTIFICATE", issued_on.year, "CT"),
            issued_on=issued_on,
            rendered_text=render(template.body, values)[:4000],
            created_by=principal.user_id,
        )
        session.add(item)
        issued.append(item)
    await session.commit()
    return issued


async def certificates(session: AsyncSession, student_id: uuid.UUID | None) -> list[dict]:
    stmt = (
        select(
            Certificate,
            CertificateTemplate.kind,
            CertificateTemplate.name,
            User.first_name,
            User.last_name,
            Student.admission_no,
        )
        .join(CertificateTemplate, CertificateTemplate.id == Certificate.template_id)
        .join(Student, Student.id == Certificate.student_id)
        .join(User, User.id == Student.user_id)
        .order_by(Certificate.created_at.desc())
        .limit(300)
    )
    if student_id:
        stmt = stmt.where(Certificate.student_id == student_id)
    return [
        {
            "id": c.id,
            "serial_no": c.serial_no,
            "kind": kind,
            "template": name,
            "student_id": c.student_id,
            "student": f"{first} {last}",
            "admission_no": no,
            "issued_on": c.issued_on,
            "revoked": c.revoked_at is not None,
            "revoked_reason": c.revoked_reason,
        }
        for c, kind, name, first, last, no in (await session.execute(stmt)).all()
    ]


async def revoke_certificate(session: AsyncSession, certificate_id: uuid.UUID, reason: str) -> None:
    item = await session.get(Certificate, certificate_id, with_for_update=True)
    if item is None:
        raise not_found()
    if item.revoked_at is not None:
        raise AppError(409, "NOT_ALLOWED", [{"field": "revoked_at", "code": "already_revoked"}])
    item.revoked_at, item.revoked_reason = now(), reason
    await session.commit()


async def certificate_pdf(session: AsyncSession, certificate_id: uuid.UUID, lang: str) -> bytes:
    item = await session.get(Certificate, certificate_id)
    if item is None:
        raise not_found()
    template = await session.get(CertificateTemplate, item.template_id)
    school, centre = await _school(session)
    background = (
        await _file_bytes(session, file_id=template.background_file_id) if template.background_file_id else None
    )
    out = io.BytesIO()
    page = landscape(A4)
    c = canvas.Canvas(out, pagesize=page, pageCompression=1)
    c.setTitle(f"Certificate {item.serial_no}")
    width, height = page
    if background:
        c.drawImage(ImageReader(io.BytesIO(background)), 0, 0, width, height, preserveAspectRatio=False, mask="auto")
    c.setStrokeColor(colors.HexColor("#312e81"))
    c.setLineWidth(3)
    c.rect(12 * mm, 12 * mm, width - 24 * mm, height - 24 * mm)
    c.setLineWidth(0.8)
    c.rect(15 * mm, 15 * mm, width - 30 * mm, height - 30 * mm)
    c.setFillColor(colors.HexColor("#1e1b4b"))
    c.setFont("Helvetica-Bold", 18)
    c.drawCentredString(width / 2, height - 38 * mm, school.upper())
    sw, en = TITLES.get(template.kind, (template.name.upper(), template.name.upper()))
    c.setFont("Helvetica-Bold", 22)
    c.drawCentredString(width / 2, height - 54 * mm, sw if lang == "sw" else en)
    c.setFillColor(colors.black)
    c.setFont("Helvetica", 13)
    y = height - 75 * mm
    for paragraph in item.rendered_text.splitlines() or [""]:
        for line in textwrap.wrap(paragraph, 95) or [""]:
            c.drawCentredString(width / 2, y, line)
            y -= 7 * mm
    c.setFont("Helvetica", 10)
    c.drawString(25 * mm, 28 * mm, f"No. {item.serial_no}" + (f" · {centre}" if centre else ""))
    c.drawString(25 * mm, 22 * mm, f"{'Tarehe' if lang == 'sw' else 'Date'}: {item.issued_on:%d/%m/%Y}")
    c.line(width - 95 * mm, 30 * mm, width - 25 * mm, 30 * mm)
    c.drawCentredString(width - 60 * mm, 24 * mm, "Mkuu wa shule" if lang == "sw" else "Head of school")
    if item.revoked_at:
        c.saveState()
        c.setFillColor(colors.Color(0.8, 0, 0, alpha=0.25))
        c.setFont("Helvetica-Bold", 70)
        c.translate(width / 2, height / 2)
        c.rotate(25)
        c.drawCentredString(0, 0, "IMEBATILISHWA / REVOKED")
        c.restoreState()
    c.showPage()
    c.save()
    return out.getvalue()


# ---------------------------------------------------------------- ID cards


def _cards_query():
    return (
        select(
            IdentityCard,
            User.first_name,
            User.last_name,
            Student.admission_no,
            Student.photo_file_key,
            SchoolClass.code,
            Stream.name,
            Staff.staff_no,
            Staff.photo_file_key,
            Designation.name_en,
            Designation.name_sw,
        )
        .join(User, User.id == IdentityCard.user_id)
        .outerjoin(Student, Student.user_id == User.id)
        .outerjoin(
            Enrolment,
            and_(
                Enrolment.student_id == Student.id,
                Enrolment.academic_year_id == _current_year(),
                Enrolment.status == EnrolmentStatus.ACTIVE,
            ),
        )
        .outerjoin(Stream, Stream.id == Enrolment.stream_id)
        .outerjoin(SchoolClass, SchoolClass.id == Stream.class_id)
        .outerjoin(Staff, Staff.user_id == User.id)
        .outerjoin(Designation, Designation.id == Staff.designation_id)
        .where(IdentityCard.revoked_at.is_(None))
        .order_by(SchoolClass.sort_order, Stream.name, User.last_name, User.first_name)
    )


def _id_out(row, lang: str) -> dict:
    card, first, last, adm, s_photo, code, stream, staff_no, t_photo, des_en, des_sw = row
    student = adm is not None
    return {
        "id": card.id,
        "user_id": card.user_id,
        "card_no": card.card_no,
        "valid_until": card.valid_until,
        "full_name": f"{first} {last}",
        "kind": "STUDENT" if student else "STAFF",
        "number": adm if student else staff_no,
        "role": (f"{code} {stream}" if code else "") if student else ((des_en if lang == "en" else des_sw) or ""),
        "photo_key": s_photo if student else t_photo,
    }


async def id_cards(
    session: AsyncSession, lang: str, *, stream_id=None, staff: bool = False, user_id=None
) -> list[dict]:
    stmt = _cards_query()
    if stream_id:
        stmt = stmt.where(Stream.id == stream_id)
    if staff:
        stmt = stmt.where(Staff.id.is_not(None))
    if user_id:
        stmt = stmt.where(IdentityCard.user_id == user_id)
    return [_id_out(r, lang) for r in (await session.execute(stmt)).all()]


async def issue_id_cards(session: AsyncSession, principal: Principal, *, stream_id=None, staff: bool = False) -> int:
    today = calendar.today()
    if stream_id:
        year = (await session.execute(select(AcademicYear).where(AcademicYear.is_current.is_(True)))).scalar_one()
        users = (
            (
                await session.execute(
                    select(Student.user_id)
                    .join(Enrolment, Enrolment.student_id == Student.id)
                    .where(
                        Enrolment.stream_id == stream_id,
                        Enrolment.academic_year_id == year.id,
                        Enrolment.status == EnrolmentStatus.ACTIVE,
                    )
                )
            )
            .scalars()
            .all()
        )
        valid_until = year.end_date
    elif staff:
        users = (
            (await session.execute(select(Staff.user_id).where(Staff.status == "ACTIVE", Staff.deleted_at.is_(None))))
            .scalars()
            .all()
        )
        valid_until = today + timedelta(days=365)
    else:
        raise AppError(422, "VALIDATION_ERROR", [{"field": "stream_id", "code": "required"}])
    holding = set(
        (
            await session.execute(
                select(IdentityCard.user_id).where(IdentityCard.revoked_at.is_(None), IdentityCard.user_id.in_(users))
            )
        ).scalars()
    )
    issued = 0
    for user_id in dict.fromkeys(users):
        if user_id in holding:
            continue
        number = await ledger.next_number(session, principal.school_id, "ID_CARD", today.year, "ID")
        session.add(
            IdentityCard(
                school_id=principal.school_id,
                user_id=user_id,
                card_no=number,
                valid_until=valid_until,
                created_by=principal.user_id,
            )
        )
        issued += 1
    await session.commit()
    return issued


async def revoke_id_card(session: AsyncSession, card_id: uuid.UUID) -> None:
    card = await session.get(IdentityCard, card_id, with_for_update=True)
    if card is None or card.revoked_at is not None:
        raise not_found()
    card.revoked_at = now()
    await session.commit()


def _qr(c: canvas.Canvas, value: str, x: float, y: float, size: float) -> None:
    widget = QrCodeWidget(value)
    left, bottom, right, top = widget.getBounds()
    drawing = Drawing(size, size, transform=[size / (right - left), 0, 0, size / (top - bottom), 0, 0])
    drawing.add(widget)
    renderPDF.draw(drawing, c, x, y)


async def id_cards_pdf(session: AsyncSession, cards: list[dict], lang: str) -> bytes:
    if not cards:
        raise AppError(409, "NOT_ALLOWED", [{"field": "cards", "code": "no_cards"}])
    school, _ = await _school(session)
    out = io.BytesIO()
    c = canvas.Canvas(out, pagesize=A4, pageCompression=1)
    c.setTitle("ID cards")
    width, height = A4
    card_w, card_h = 85 * mm, 54 * mm
    left = (width - 2 * card_w - 8 * mm) / 2
    for index, card in enumerate(cards):
        slot = index % 8
        if index and slot == 0:
            c.showPage()
        x = left + (slot % 2) * (card_w + 8 * mm)
        y = height - 15 * mm - (slot // 2 + 1) * (card_h + 6 * mm)
        c.setFillColor(colors.HexColor("#1e1b4b"))
        c.roundRect(x, y + card_h - 11 * mm, card_w, 11 * mm, 3 * mm, stroke=0, fill=1)
        c.setStrokeColor(colors.HexColor("#312e81"))
        c.roundRect(x, y, card_w, card_h, 3 * mm, stroke=1, fill=0)
        c.setFillColor(colors.white)
        c.setFont("Helvetica-Bold", 8)
        c.drawString(x + 3 * mm, y + card_h - 5.5 * mm, school[:46].upper())
        c.setFont("Helvetica", 6.5)
        kind = (
            "KITAMBULISHO CHA MWANAFUNZI / STUDENT ID"
            if card["kind"] == "STUDENT"
            else "KITAMBULISHO CHA MFANYAKAZI / STAFF ID"
        )
        c.drawString(x + 3 * mm, y + card_h - 9 * mm, kind)
        photo = await _file_bytes(session, key=card["photo_key"]) if card["photo_key"] else None
        c.setFillColor(colors.HexColor("#eef2ff"))
        c.rect(x + 3 * mm, y + 5 * mm, 24 * mm, 32 * mm, stroke=0, fill=1)
        if photo:
            c.drawImage(
                ImageReader(io.BytesIO(photo)),
                x + 3 * mm,
                y + 5 * mm,
                24 * mm,
                32 * mm,
                preserveAspectRatio=True,
                mask="auto",
            )
        c.setFillColor(colors.black)
        c.setFont("Helvetica-Bold", 10)
        c.drawString(x + 30 * mm, y + card_h - 17 * mm, card["full_name"][:26])
        c.setFont("Helvetica", 7.5)
        lines = [
            card["number"] or "",
            card["role"],
            f"{'Inatumika hadi' if lang == 'sw' else 'Valid until'} {card['valid_until']:%d/%m/%Y}",
        ]
        for i, text in enumerate(t for t in lines if t):
            c.drawString(x + 30 * mm, y + card_h - (22 + 4.5 * i) * mm, text)
        c.setFont("Courier-Bold", 9)
        c.drawString(x + 30 * mm, y + 5 * mm, card["card_no"])
        _qr(c, card["card_no"], x + card_w - 21 * mm, y + 3 * mm, 18 * mm)
    c.showPage()
    c.save()
    return out.getvalue()
