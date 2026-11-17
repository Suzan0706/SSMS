"""Fee setup: fee items, fee structures (DRAFT -> APPROVED -> ARCHIVED), discount rules, student discounts."""

import uuid
from collections import defaultdict
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import Principal
from app.core.errors import AppError
from app.models import (
    AcademicYear,
    DiscountRule,
    FeeItem,
    FeeStructure,
    FeeStructureLine,
    LedgerAccount,
    SchoolClass,
    Student,
    StudentDiscount,
    Term,
)
from app.models.enums import FeeStructureStatus as F
from app.schemas.finance import FeeStructureIn, FeeStructureOut, FeeStructureUpdate, StructureLineIn, StructureLineOut
from app.services import crud
from app.services.people import now


def _invalid(field: str, code: str, status: int = 422, error: str = "VALIDATION_ERROR") -> AppError:
    return AppError(status, error, [{"field": field, "code": code}])


async def check_income_account(session: AsyncSession, account_id: uuid.UUID) -> None:
    kind = (await session.execute(select(LedgerAccount.kind).where(LedgerAccount.id == account_id))).scalar()
    if kind != "INCOME":
        raise _invalid("income_account_id", "invalid_value")


async def structure_out(session: AsyncSession, structure: FeeStructure) -> FeeStructureOut:
    lines = (
        (
            await session.execute(
                select(FeeStructureLine)
                .where(FeeStructureLine.fee_structure_id == structure.id, FeeStructureLine.deleted_at.is_(None))
                .order_by(FeeStructureLine.term_id.nulls_first(), FeeStructureLine.created_at)
            )
        )
        .scalars()
        .all()
    )
    totals: dict[str, Decimal] = defaultdict(lambda: Decimal("0"))
    for line in lines:
        if not line.is_optional:
            totals[str(line.term_id) if line.term_id else "yearly"] += line.amount_tzs
    return FeeStructureOut(
        id=structure.id,
        academic_year_id=structure.academic_year_id,
        class_id=structure.class_id,
        name=structure.name,
        status=structure.status,
        approved_by=structure.approved_by,
        approved_at=structure.approved_at,
        lines=[StructureLineOut.model_validate(line) for line in lines],
        totals=dict(totals),
    )


async def _check_lines(session: AsyncSession, year_id: uuid.UUID, lines: list[StructureLineIn]) -> None:
    keys = [(line.fee_item_id, line.term_id) for line in lines]
    if len(set(keys)) != len(keys):
        raise _invalid("lines", "duplicate_in_file")
    items = set((await session.execute(select(FeeItem.id).where(FeeItem.deleted_at.is_(None)))).scalars())
    if any(line.fee_item_id not in items for line in lines):
        raise _invalid("lines.fee_item_id", "invalid_value")
    terms = set((await session.execute(select(Term.id).where(Term.academic_year_id == year_id))).scalars())
    if any(line.term_id and line.term_id not in terms for line in lines):
        raise _invalid("lines.term_id", "outside_year")


async def _write_lines(session: AsyncSession, principal: Principal, structure_id: uuid.UUID, lines) -> None:
    for line in lines:
        session.add(
            FeeStructureLine(
                school_id=principal.school_id,
                fee_structure_id=structure_id,
                created_by=principal.user_id,
                **line.model_dump(),
            )
        )
    await session.flush()


async def create_structure(session: AsyncSession, principal: Principal, body: FeeStructureIn) -> FeeStructureOut:
    await crud.get_live(session, AcademicYear, body.academic_year_id)
    await crud.get_live(session, SchoolClass, body.class_id)
    await _check_lines(session, body.academic_year_id, body.lines)
    structure = await crud.create(
        session, principal, FeeStructure, body.model_dump(exclude={"lines"}) | {"status": F.DRAFT}, commit=False
    )
    await _write_lines(session, principal, structure.id, body.lines)  # live duplicate (year, class) -> 409
    await session.commit()
    return await structure_out(session, structure)


async def _draft(session: AsyncSession, structure_id: uuid.UUID) -> FeeStructure:
    structure = await crud.get_live(session, FeeStructure, structure_id, lock=True)
    if structure.status != F.DRAFT:
        raise _invalid("status", "invalid_value", 409, "NOT_ALLOWED")  # approved fees are changed by a new structure
    return structure


async def update_structure(
    session: AsyncSession, principal: Principal, structure_id: uuid.UUID, body: FeeStructureUpdate
) -> FeeStructureOut:
    structure = await _draft(session, structure_id)
    if body.name:
        structure.name = body.name
    if body.lines is not None:
        await _check_lines(session, structure.academic_year_id, body.lines)
        old = (
            await session.execute(
                select(FeeStructureLine).where(
                    FeeStructureLine.fee_structure_id == structure.id, FeeStructureLine.deleted_at.is_(None)
                )
            )
        ).scalars()
        for line in old:
            line.deleted_at = now()
        await session.flush()
        await _write_lines(session, principal, structure.id, body.lines)
    await session.commit()
    return await structure_out(session, structure)


async def approve_structure(session: AsyncSession, principal: Principal, structure_id: uuid.UUID) -> FeeStructureOut:
    structure = await _draft(session, structure_id)
    structure.status, structure.approved_by, structure.approved_at = F.APPROVED, principal.user_id, now()
    await session.commit()
    return await structure_out(session, structure)


async def archive_structure(session: AsyncSession, structure_id: uuid.UUID) -> FeeStructureOut:
    structure = await crud.get_live(session, FeeStructure, structure_id, lock=True)
    if structure.status != F.APPROVED:  # drafts are deleted, not archived
        raise _invalid("status", "invalid_value", 409, "NOT_ALLOWED")
    structure.status = F.ARCHIVED
    await session.commit()
    return await structure_out(session, structure)


async def delete_draft(session: AsyncSession, structure_id: uuid.UUID, reason: str) -> None:
    await _draft(session, structure_id)
    await crud.soft_delete(session, FeeStructure, structure_id, reason)


async def add_student_discount(
    session: AsyncSession,
    principal: Principal,
    student_id: uuid.UUID,
    rule_id: uuid.UUID,
    year_id: uuid.UUID,
    reason: str,
) -> StudentDiscount:
    await crud.get_live(session, Student, student_id)
    await crud.get_live(session, DiscountRule, rule_id)
    await crud.get_live(session, AcademicYear, year_id)
    return await crud.create(
        session,
        principal,
        StudentDiscount,
        {
            "student_id": student_id,
            "discount_rule_id": rule_id,
            "academic_year_id": year_id,
            "reason": reason,
            "approved_by": principal.user_id,
        },
    )
