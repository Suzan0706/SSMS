"""/accounts: other income and expenses, reversals, income statement, cash book; /fine-rules (FR-87, FR-88, FR-89)."""

import uuid
from datetime import date
from decimal import Decimal
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, Query, Response, status
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import Principal, require_permission
from app.db.session import get_session
from app.services import accounts as service
from app.services import calendar

router = APIRouter(tags=["accounts"])
Session = Annotated[AsyncSession, Depends(get_session)]
Recorder = Annotated[Principal, require_permission("accounts.record")]
Approver = Annotated[Principal, require_permission("accounts.approve")]
Reader = Annotated[Principal, require_permission("accounts.read", "accounts.record", "accounts.approve")]
FineSetter = Annotated[Principal, require_permission("fines.configure")]
Kind = Literal["INCOME", "EXPENSE"]


class CategoryIn(BaseModel):
    kind: Kind
    name_en: str = Field(min_length=2, max_length=80)
    name_sw: str = Field(min_length=2, max_length=80)
    ledger_account_id: uuid.UUID


class EntryIn(BaseModel):
    category_id: uuid.UUID
    entry_date: date
    amount_tzs: Decimal = Field(gt=0, le=Decimal("999999999999.99"), decimal_places=2)
    method: Literal["CASH", "BANK", "MOBILE_MONEY", "CHEQUE"]
    reference: str | None = Field(default=None, max_length=60)
    party: str | None = Field(default=None, max_length=120, description="Who paid or was paid")
    description: str = Field(min_length=3, max_length=300)
    attachment_file_id: uuid.UUID | None = Field(default=None, description="A RECEIPT upload (scan or photo)")


class ReversalIn(BaseModel):
    reason: str = Field(min_length=5, max_length=300)


class DecisionIn(BaseModel):
    approve: bool


class FineRuleIn(BaseModel):
    amount_tzs: Decimal = Field(gt=0, le=Decimal("10000000"), decimal_places=2)
    grace_days: int = Field(default=0, ge=0, le=365)
    active: bool = True


def _period(start: date | None, end: date | None) -> tuple[date, date]:
    today = calendar.today()
    start, end = start or today.replace(day=1), end or today
    if end < start:
        start, end = end, start
    return start, end


@router.get("/accounts/categories", summary="Income and expense categories")
async def list_categories(principal: Reader, session: Session, kind: Kind | None = None) -> list[dict]:
    return await service.list_categories(session, principal, kind)


@router.get("/accounts/ledger-accounts", summary="Income or expense accounts a category can post to")
async def ledger_accounts(kind: Kind, _: Reader, session: Session) -> list[dict]:
    return await service.accounts_of_kind(session, kind)


@router.post("/accounts/categories", status_code=status.HTTP_201_CREATED)
async def create_category(body: CategoryIn, principal: Approver, session: Session) -> dict:
    return {"id": await service.create_category(session, principal, body)}


@router.post("/accounts/entries", status_code=status.HTTP_201_CREATED, summary="Record income or an expense")
async def record(body: EntryIn, principal: Recorder, session: Session) -> dict:
    entry = await service.record(session, principal, body)
    return {"id": entry.id, "entry_no": entry.entry_no}


@router.get("/accounts/entries", summary="Entries of a period (default: this month)")
async def list_entries(
    principal: Reader,
    session: Session,
    date_from: Annotated[date | None, Query(alias="from")] = None,
    date_to: Annotated[date | None, Query(alias="to")] = None,
    kind: Kind | None = None,
) -> list[dict]:
    start, end = _period(date_from, date_to)
    return await service.list_entries(session, principal, start=start, end=end, kind=kind)


@router.post("/accounts/entries/{entry_id}/reversal-request", status_code=status.HTTP_204_NO_CONTENT)
async def request_reversal(entry_id: uuid.UUID, body: ReversalIn, principal: Recorder, session: Session):
    await service.request_reversal(session, principal, entry_id, body.reason)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post(
    "/accounts/entries/{entry_id}/reversal-decision",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Approve (posts the mirror journal) or reject; never by the person who asked",
)
async def decide_reversal(entry_id: uuid.UUID, body: DecisionIn, principal: Approver, session: Session):
    await service.decide_reversal(session, principal, entry_id, body.approve)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get("/accounts/income-statement", summary="Income and expenses by account, fees included")
async def income_statement(
    principal: Reader,
    session: Session,
    date_from: Annotated[date | None, Query(alias="from")] = None,
    date_to: Annotated[date | None, Query(alias="to")] = None,
) -> dict:
    start, end = _period(date_from, date_to)
    return await service.income_statement(session, principal, start, end)


@router.get("/accounts/cash-book", summary="Movements and running balance of cash, bank or mobile money")
async def cash_book(
    _: Reader,
    session: Session,
    account: Literal["1000", "1110", "1200"] = "1000",
    date_from: Annotated[date | None, Query(alias="from")] = None,
    date_to: Annotated[date | None, Query(alias="to")] = None,
) -> dict:
    start, end = _period(date_from, date_to)
    return await service.cash_book(session, account, start, end)


FineKind = Literal["late-fee", "library-day"]
KINDS = {"late-fee": "LATE_FEE", "library-day": "LIBRARY_DAY"}


@router.get("/fine-rules/{kind}", summary="The active fine of a kind (late fee, or library fine per day), or null")
async def get_fine_rule(kind: FineKind, _: FineSetter, session: Session) -> dict | None:
    rule = await service.fine_rule(session, KINDS[kind])
    return (
        None if rule is None else {"amount_tzs": rule.amount_tzs, "grace_days": rule.grace_days, "active": rule.active}
    )


@router.put("/fine-rules/{kind}", summary="Set a fine (amount per invoice, or per day for library books)")
async def set_fine_rule(kind: FineKind, body: FineRuleIn, principal: FineSetter, session: Session) -> dict:
    rule = await service.set_fine_rule(session, principal, body, KINDS[kind])
    return {"amount_tzs": rule.amount_tzs, "grace_days": rule.grace_days, "active": rule.active}


@router.post("/fine-rules/late-fee/apply", summary="Charge the fine once on every overdue unpaid invoice")
async def apply_late_fees(principal: FineSetter, session: Session) -> dict:
    charged = await service.apply_late_fees(session, principal)
    return {"charged": len(charged), "invoices": charged}
