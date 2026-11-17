"""What transport and boarding cost a student in a term (invoice lines come from here).

Transport: the route's term fee (fee item TRANSPORT) while the student has an active assignment for the term.
Boarding: the class fee structure's optional BOARDING line(s) for the term (a yearly line on the first term) while the
student has an active room for the term. Ending an assignment or vacating a room does not refund automatically; the
bursar adds a discount line when the school agrees to one.
"""

import uuid
from decimal import Decimal

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import (
    AcademicYear,
    Enrolment,
    FeeItem,
    FeeStructure,
    FeeStructureLine,
    HostelAllocation,
    Route,
    RouteStop,
    Stream,
    Term,
    TransportAssignment,
)
from app.models.enums import EnrolmentStatus, FeeStructureStatus

Charge = tuple[uuid.UUID, str, Decimal]  # fee item, description, amount


async def _item(session: AsyncSession, code: str) -> FeeItem | None:
    return (
        await session.execute(select(FeeItem).where(FeeItem.code == code, FeeItem.deleted_at.is_(None)))
    ).scalar_one_or_none()


def _name(item: FeeItem, lang: str) -> str:
    return item.name_sw if lang == "sw" else item.name_en


async def transport(session: AsyncSession, student_id: uuid.UUID, term: Term, lang: str) -> list[Charge]:
    item = await _item(session, "TRANSPORT")
    row = (
        await session.execute(
            select(Route.name, Route.term_fee_tzs)
            .join(RouteStop, RouteStop.route_id == Route.id)
            .join(TransportAssignment, TransportAssignment.stop_id == RouteStop.id)
            .where(
                TransportAssignment.student_id == student_id,
                TransportAssignment.term_id == term.id,
                TransportAssignment.ended_at.is_(None),
            )
        )
    ).first()
    if item is None or row is None or row.term_fee_tzs <= 0:
        return []
    term_name = term.name_sw if lang == "sw" else term.name_en
    return [(item.id, f"{_name(item, lang)} ({row.name}) - {term_name}"[:120], row.term_fee_tzs)]


async def boarding(session: AsyncSession, student_id: uuid.UUID, term: Term, lang: str) -> list[Charge]:
    item = await _item(session, "BOARDING")
    housed = (
        await session.execute(
            select(HostelAllocation.id).where(
                HostelAllocation.student_id == student_id,
                HostelAllocation.term_id == term.id,
                HostelAllocation.vacated_at.is_(None),
            )
        )
    ).first()
    if item is None or not housed:
        return []
    class_id = (
        await session.execute(
            select(Stream.class_id)
            .join(Enrolment, Enrolment.stream_id == Stream.id)
            .where(
                Enrolment.student_id == student_id,
                Enrolment.academic_year_id == term.academic_year_id,
                Enrolment.status == EnrolmentStatus.ACTIVE,
            )
        )
    ).scalar()
    first_term = (
        await session.execute(
            select(func.min(Term.term_no)).where(
                Term.academic_year_id == term.academic_year_id, Term.deleted_at.is_(None)
            )
        )
    ).scalar() == term.term_no
    lines = (
        await session.execute(
            select(FeeStructureLine)
            .join(FeeStructure, FeeStructure.id == FeeStructureLine.fee_structure_id)
            .where(
                FeeStructure.academic_year_id == term.academic_year_id,
                FeeStructure.class_id == class_id,
                FeeStructure.status == FeeStructureStatus.APPROVED,
                FeeStructure.deleted_at.is_(None),
                FeeStructureLine.fee_item_id == item.id,
                FeeStructureLine.deleted_at.is_(None),
            )
        )
    ).scalars()
    year = (await session.execute(select(AcademicYear.name).where(AcademicYear.id == term.academic_year_id))).scalar()
    term_name = term.name_sw if lang == "sw" else term.name_en
    return [
        (item.id, f"{_name(item, lang)} - {term_name if ln.term_id else year}"[:120], ln.amount_tzs)
        for ln in lines
        if ln.amount_tzs > 0 and (ln.term_id == term.id or (ln.term_id is None and first_term))
    ]


async def charges(session: AsyncSession, student_id: uuid.UUID, term: Term, lang: str) -> list[Charge]:
    return await transport(session, student_id, term, lang) + await boarding(session, student_id, term, lang)
