"""/ledger-accounts, /fee-items, /fee-structures, /discount-rules, /students/{id}/discounts."""

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, Query, Response
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import Principal, require_permission
from app.core.errors import forbidden
from app.db.session import get_session
from app.models import DiscountRule, FeeItem, FeeStructure, LedgerAccount, StudentDiscount
from app.schemas.finance import (
    DiscountRuleIn,
    DiscountRuleOut,
    FeeItemIn,
    FeeItemOut,
    FeeItemUpdate,
    FeeStructureIn,
    FeeStructureOut,
    FeeStructureUpdate,
    LedgerAccountOut,
    StudentDiscountIn,
    StudentDiscountOut,
)
from app.services import crud
from app.services import fees as service

router = APIRouter(tags=["fees"])
Session = Annotated[AsyncSession, Depends(get_session)]
Reader = Annotated[Principal, require_permission("finance.read", "fees.configure")]
Configurer = Annotated[Principal, require_permission("fees.configure")]
Reason = Annotated[str, Query(min_length=3, max_length=300)]


@router.get("/ledger-accounts", response_model=list[LedgerAccountOut])
async def ledger_accounts(_: Reader, session: Session):
    return await crud.list_live(session, LedgerAccount, LedgerAccount.code)


@router.get("/fee-items", response_model=list[FeeItemOut])
async def list_fee_items(_: Reader, session: Session):
    return await crud.list_live(session, FeeItem, FeeItem.code)


@router.post("/fee-items", response_model=FeeItemOut, status_code=201)
async def create_fee_item(body: FeeItemIn, principal: Configurer, session: Session):
    await service.check_income_account(session, body.income_account_id)
    return await crud.create(session, principal, FeeItem, body.model_dump())


@router.patch("/fee-items/{item_id}", response_model=FeeItemOut)
async def update_fee_item(item_id: uuid.UUID, body: FeeItemUpdate, _: Configurer, session: Session):
    data = body.model_dump(exclude_unset=True)
    if data.get("income_account_id"):
        await service.check_income_account(session, data["income_account_id"])
    return await crud.update(session, FeeItem, item_id, data)


@router.get("/fee-structures", response_model=list[FeeStructureOut])
async def list_structures(
    _: Reader, session: Session, academic_year_id: uuid.UUID | None = None, class_id: uuid.UUID | None = None
):
    where = [
        c
        for c in (
            (FeeStructure.academic_year_id == academic_year_id) if academic_year_id else None,
            (FeeStructure.class_id == class_id) if class_id else None,
        )
        if c is not None
    ]
    structures = await crud.list_live(session, FeeStructure, FeeStructure.created_at.desc(), where=where, limit=100)
    return [await service.structure_out(session, s) for s in structures]


@router.get("/fee-structures/{structure_id}", response_model=FeeStructureOut)
async def get_structure(structure_id: uuid.UUID, _: Reader, session: Session):
    return await service.structure_out(session, await crud.get_live(session, FeeStructure, structure_id))


@router.post(
    "/fee-structures",
    response_model=FeeStructureOut,
    status_code=201,
    responses={409: {"description": "a live structure exists for this class and year"}},
)
async def create_structure(body: FeeStructureIn, principal: Configurer, session: Session):
    return await service.create_structure(session, principal, body)


@router.patch(
    "/fee-structures/{structure_id}",
    response_model=FeeStructureOut,
    responses={409: {"description": "only DRAFT structures change"}},
)
async def update_structure(structure_id: uuid.UUID, body: FeeStructureUpdate, principal: Configurer, session: Session):
    return await service.update_structure(session, principal, structure_id, body)


@router.post(
    "/fee-structures/{structure_id}/approve",
    response_model=FeeStructureOut,
    summary="Approve (needs fees.configure and settings.update); approved fees can be invoiced",
)
async def approve_structure(structure_id: uuid.UUID, principal: Configurer, session: Session):
    if not principal.has("settings.update"):
        raise forbidden()
    return await service.approve_structure(session, principal, structure_id)


@router.post(
    "/fee-structures/{structure_id}/archive",
    response_model=FeeStructureOut,
    summary="Retire an approved structure so a corrected one can be created",
)
async def archive_structure(structure_id: uuid.UUID, _: Configurer, session: Session):
    return await service.archive_structure(session, structure_id)


@router.delete("/fee-structures/{structure_id}", status_code=204, summary="Delete a DRAFT structure")
async def delete_structure(structure_id: uuid.UUID, reason: Reason, _: Configurer, session: Session):
    await service.delete_draft(session, structure_id, reason)
    return Response(status_code=204)


@router.get("/discount-rules", response_model=list[DiscountRuleOut])
async def list_rules(_: Reader, session: Session):
    return await crud.list_live(session, DiscountRule, DiscountRule.code)


@router.post("/discount-rules", response_model=DiscountRuleOut, status_code=201)
async def create_rule(body: DiscountRuleIn, principal: Configurer, session: Session):
    return await crud.create(session, principal, DiscountRule, body.model_dump())


@router.get("/students/{student_id}/discounts", response_model=list[StudentDiscountOut])
async def student_discounts(student_id: uuid.UUID, _: Reader, session: Session):
    return await crud.list_live(
        session, StudentDiscount, StudentDiscount.approved_at.desc(), where=[StudentDiscount.student_id == student_id]
    )


@router.post("/students/{student_id}/discounts", response_model=StudentDiscountOut, status_code=201)
async def add_student_discount(student_id: uuid.UUID, body: StudentDiscountIn, principal: Configurer, session: Session):
    return await service.add_student_discount(
        session, principal, student_id, body.discount_rule_id, body.academic_year_id, body.reason
    )


@router.delete(
    "/students/{student_id}/discounts/{discount_id}",
    status_code=204,
    summary="Withdraw a discount (future invoices only; issued invoices keep their lines)",
)
async def remove_student_discount(
    student_id: uuid.UUID, discount_id: uuid.UUID, reason: Reason, _: Configurer, session: Session
):
    await crud.soft_delete(session, StudentDiscount, discount_id, reason)
    return Response(status_code=204)
