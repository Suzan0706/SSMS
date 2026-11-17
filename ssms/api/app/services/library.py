"""Library categories, publishers, cards and late-return fines (FR-96, FR-97).

A late return by a student is fined at the school's LIBRARY_DAY rate for each day past the due date (after the grace
days), charged once on the student's most recent invoice through invoices.add_charges. Staff borrowers and
students who have never been invoiced are not fined; the return still goes through.
"""

import io
import uuid
from decimal import Decimal

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.units import mm
from reportlab.pdfgen import canvas
from sqlalchemy import and_, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import Principal
from app.core.errors import AppError, not_found
from app.models import (
    AcademicYear,
    Enrolment,
    Invoice,
    LibraryCard,
    LibraryLoan,
    School,
    SchoolClass,
    Stream,
    Student,
    User,
)
from app.models.enums import EnrolmentStatus
from app.services import accounts, calendar, crud, invoices, ledger
from app.services.people import now

FULL_NAME = func.concat_ws(" ", User.first_name, User.last_name)


# ---------------------------------------------------------------- categories and publishers


async def named(session: AsyncSession, model) -> list[dict]:
    return [{"id": r.id, "name": r.name} for r in await crud.list_live(session, model, model.name)]


async def add_named(session: AsyncSession, principal: Principal, model, name: str) -> uuid.UUID:
    item = model(school_id=principal.school_id, name=name.strip(), created_by=principal.user_id)
    session.add(item)
    await crud.flush_checked(session, "name", "duplicate")
    await session.commit()
    return item.id


# ---------------------------------------------------------------- cards


def _cards_query():
    year = select(AcademicYear.id).where(AcademicYear.is_current.is_(True)).scalar_subquery()
    return (
        select(LibraryCard, FULL_NAME, Student.admission_no, SchoolClass.code, Stream.name)
        .join(User, User.id == LibraryCard.user_id)
        .outerjoin(Student, Student.user_id == User.id)
        .outerjoin(
            Enrolment,
            and_(
                Enrolment.student_id == Student.id,
                Enrolment.academic_year_id == year,
                Enrolment.status == EnrolmentStatus.ACTIVE,
            ),
        )
        .outerjoin(Stream, Stream.id == Enrolment.stream_id)
        .outerjoin(SchoolClass, SchoolClass.id == Stream.class_id)
        .where(LibraryCard.revoked_at.is_(None))
        .order_by(SchoolClass.sort_order, Stream.name, User.last_name, User.first_name)
    )


def _card_out(card, name, admission_no, class_code, stream) -> dict:
    return {
        "id": card.id,
        "user_id": card.user_id,
        "card_no": card.card_no,
        "issued_on": card.issued_on,
        "full_name": name,
        "admission_no": admission_no,
        "class_stream": f"{class_code} {stream}" if class_code else None,
    }


async def cards(session: AsyncSession, stream_id: uuid.UUID | None) -> list[dict]:
    stmt = _cards_query()
    if stream_id:
        stmt = stmt.where(Stream.id == stream_id)
    return [_card_out(*r) for r in (await session.execute(stmt)).all()]


async def issue_cards(
    session: AsyncSession, principal: Principal, stream_id: uuid.UUID | None, user_ids: list[uuid.UUID]
) -> int:
    """A card for every chosen person (or every student of the stream) who has no live card. Returns how many."""
    targets = list(user_ids)
    if stream_id:
        year = (await session.execute(select(AcademicYear.id).where(AcademicYear.is_current.is_(True)))).scalar_one()
        targets += list(
            (
                await session.execute(
                    select(Student.user_id)
                    .join(Enrolment, Enrolment.student_id == Student.id)
                    .join(User, User.id == Student.user_id)
                    .where(
                        Enrolment.stream_id == stream_id,
                        Enrolment.academic_year_id == year,
                        Enrolment.status == EnrolmentStatus.ACTIVE,
                    )
                    .order_by(User.last_name, User.first_name)
                )
            ).scalars()
        )
    if not targets:
        raise AppError(422, "VALIDATION_ERROR", [{"field": "user_ids", "code": "required"}])
    known = set(
        (await session.execute(select(User.id).where(User.id.in_(targets), User.deleted_at.is_(None)))).scalars()
    )
    if known != set(targets):
        raise AppError(422, "INVALID_REFERENCE", [{"field": "user_ids", "code": "invalid_value"}])
    holding = set(
        (
            await session.execute(
                select(LibraryCard.user_id).where(LibraryCard.revoked_at.is_(None), LibraryCard.user_id.in_(targets))
            )
        ).scalars()
    )
    today = calendar.today()
    issued = 0
    for user_id in dict.fromkeys(targets):
        if user_id in holding:
            continue
        number = await ledger.next_number(session, principal.school_id, "LIBRARY_CARD", today.year, "LC")
        session.add(
            LibraryCard(
                school_id=principal.school_id,
                user_id=user_id,
                card_no=number,
                issued_on=today,
                created_by=principal.user_id,
            )
        )
        issued += 1
    await session.commit()
    return issued


async def revoke_card(session: AsyncSession, card_id: uuid.UUID) -> None:
    card = await session.get(LibraryCard, card_id, with_for_update=True)
    if card is None or card.revoked_at is not None:
        raise not_found()
    card.revoked_at = now()
    await session.commit()


async def card_holder(session: AsyncSession, card_no: str) -> uuid.UUID | None:
    return (
        await session.execute(
            select(LibraryCard.user_id).where(
                func.upper(LibraryCard.card_no) == card_no.strip().upper(), LibraryCard.revoked_at.is_(None)
            )
        )
    ).scalar_one_or_none()


async def cards_pdf(session: AsyncSession, stream_id: uuid.UUID | None) -> bytes:
    """Eight cards per A4 page (two columns of four), 85 × 54 mm like a bank card."""
    rows = await cards(session, stream_id)
    if not rows:
        raise AppError(409, "NOT_ALLOWED", [{"field": "stream_id", "code": "no_cards"}])
    school = (await session.execute(select(School.name))).scalar_one()
    out = io.BytesIO()
    c = canvas.Canvas(out, pagesize=A4, pageCompression=1)
    c.setTitle("Library cards")
    width, height = A4
    card_w, card_h = 85 * mm, 54 * mm
    left = (width - 2 * card_w - 8 * mm) / 2
    for index, card in enumerate(rows):
        slot = index % 8
        if index and slot == 0:
            c.showPage()
        x = left + (slot % 2) * (card_w + 8 * mm)
        y = height - 15 * mm - (slot // 2 + 1) * (card_h + 6 * mm)
        c.setStrokeColor(colors.HexColor("#312e81"))
        c.setFillColor(colors.HexColor("#1e1b4b"))
        c.roundRect(x, y + card_h - 12 * mm, card_w, 12 * mm, 3 * mm, stroke=0, fill=1)
        c.roundRect(x, y, card_w, card_h, 3 * mm, stroke=1, fill=0)
        c.setFillColor(colors.white)
        c.setFont("Helvetica-Bold", 8)
        c.drawString(x + 4 * mm, y + card_h - 6 * mm, school[:44].upper())
        c.setFont("Helvetica", 7)
        c.drawString(x + 4 * mm, y + card_h - 10 * mm, "KADI YA MAKTABA / LIBRARY CARD")
        c.setFillColor(colors.black)
        c.setFont("Helvetica-Bold", 11)
        c.drawString(x + 4 * mm, y + card_h - 21 * mm, card["full_name"][:32])
        c.setFont("Helvetica", 8)
        lines = [card["admission_no"], card["class_stream"], f"{card['issued_on']:%d/%m/%Y}"]
        for i, text in enumerate(t for t in lines if t):
            c.drawString(x + 4 * mm, y + card_h - (27 + 5 * i) * mm, text)
        c.setFont("Courier-Bold", 13)
        c.drawRightString(x + card_w - 4 * mm, y + 5 * mm, card["card_no"])
    c.showPage()
    c.save()
    return out.getvalue()


# ---------------------------------------------------------------- late returns


async def fine_for(session: AsyncSession, loan: LibraryLoan) -> tuple[Decimal, int]:
    """(fine, chargeable days late) for a loan returned today under the active LIBRARY_DAY rule."""
    rule = await accounts.fine_rule(session, "LIBRARY_DAY")
    if rule is None:
        return Decimal("0"), 0
    days = (calendar.today() - loan.due_date).days - rule.grace_days
    return (rule.amount_tzs * days, days) if days > 0 else (Decimal("0"), 0)


async def return_book(session: AsyncSession, principal: Principal, loan_id: uuid.UUID) -> tuple[uuid.UUID, Decimal]:
    """Mark the loan returned and, when it is late, charge the borrower's term invoice. Returns (loan id, fine)."""
    loan = await crud.get_live(session, LibraryLoan, loan_id, lock=True)
    if loan.returned_at is not None:
        return loan.id, Decimal("0")
    loan.returned_at = now()
    fine, days = await fine_for(session, loan)
    charged = Decimal("0")
    student = (await session.execute(select(Student.id).where(Student.user_id == loan.borrower_user_id))).scalar()
    # the most recent invoice of the student: the current term's once billed, else the last one still open
    term = (
        (
            await session.execute(
                select(Invoice.term_id)
                .where(Invoice.student_id == student, Invoice.cancelled_at.is_(None))
                .order_by(Invoice.issued_at.desc())
                .limit(1)
            )
        ).scalar()
        if student
        else None
    )
    if fine > 0 and student and term:
        rule = await accounts.fine_rule(session, "LIBRARY_DAY")
        number = await invoices.add_charges(
            session,
            principal.school_id,
            student,
            term,
            [(rule.fee_item_id, f"Library fine, {days} day(s) late / Faini ya maktaba, siku {days}", fine)],
            principal.user_id,
        )
        if number:
            charged = fine
    await session.commit()
    return loan.id, charged
