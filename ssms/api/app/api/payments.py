"""/payments (cash/bank entry, receipts, push), reversals, /bank-deposits, /reconciliation-runs, fee reports."""

import hashlib
import uuid
from datetime import date
from decimal import Decimal
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, File, Form, Header, Query, Response, UploadFile
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import Principal, active_principal, require_permission
from app.api.imports import XLSX
from app.core.errors import forbidden, not_found
from app.core.files import read_limited
from app.db.session import get_session
from app.models import BankDeposit, Payment, ReconciliationRun
from app.models.enums import Channel, DepositStatus
from app.schemas.finance import (
    BankDepositIn,
    BankDepositOut,
    DecisionNoteIn,
    PaymentIn,
    PaymentOut,
    PushIn,
    ReconciliationItemOut,
    ReconciliationRunOut,
    ResolveIn,
    ReversalRequestIn,
    ReversalRequestOut,
)
from app.services import crud, fee_reports, idempotency, invoices, mobile, reconciliation
from app.services import payments as service
from app.tasks.dispatch import get_dispatcher

router = APIRouter()
Session = Annotated[AsyncSession, Depends(get_session)]
Signed = Annotated[Principal, Depends(active_principal)]
Recorder = Annotated[Principal, require_permission("payments.record")]
Finance = Annotated[Principal, require_permission("finance.read")]
PDF = "application/pdf"


def _dispatch(call: dict | None) -> None:
    if call:
        get_dispatcher().send("sms.send", **call)


@router.post(
    "/payments",
    response_model=PaymentOut,
    status_code=201,
    tags=["payments"],
    responses={409: {"description": "DUPLICATE reference for this channel"}},
    summary="Record cash or a bank slip; allocated oldest-due-first, receipt issued at once",
)
async def record(
    body: PaymentIn,
    principal: Recorder,
    session: Session,
    idempotency_key: Annotated[str | None, Header(alias="Idempotency-Key")] = None,
):
    key = idempotency.require_key(idempotency_key)
    digest = hashlib.sha256(body.model_dump_json().encode()).hexdigest()
    previous = await idempotency.replay(session, "POST /payments", key, digest)
    if previous:
        payment = (
            await session.execute(select(Payment).where(Payment.id == uuid.UUID(previous["payment_id"])))
        ).scalar_one()
        return await invoices.payment_out(session, payment)
    payment, call = await service.record_manual(session, principal, body)
    idempotency.remember(session, principal, "POST /payments", key, digest, 201, {"payment_id": str(payment.id)})
    await session.commit()
    _dispatch(call)
    return await invoices.payment_out(session, payment)


@router.get("/payments/{payment_id}", response_model=PaymentOut, tags=["payments"])
async def get_payment(payment_id: uuid.UUID, principal: Signed, session: Session):
    payment = (await session.execute(select(Payment).where(Payment.id == payment_id))).scalar_one_or_none()
    if payment is None or not await invoices.may_see_student(session, principal, payment.student_id):
        raise not_found()
    return await invoices.payment_out(session, payment)


@router.get(
    "/payments/{payment_id}/receipt",
    response_class=Response,
    tags=["payments"],
    responses={200: {"content": {PDF: {}}}},
    summary="Receipt PDF with the amount in words",
)
async def receipt(
    payment_id: uuid.UUID,
    principal: Signed,
    session: Session,
    lang: Annotated[Literal["sw", "en"] | None, Query()] = None,
):
    number, data = await service.receipt_pdf(session, principal, payment_id, lang or principal.language)
    return Response(data, media_type=PDF, headers={"Content-Disposition": f'attachment; filename="{number}.pdf"'})


@router.post(
    "/payments/push",
    status_code=202,
    tags=["payments"],
    summary="Send a mobile-money payment prompt to the payer's phone (parent or bursar)",
)
async def push(body: PushIn, principal: Signed, session: Session):
    return await mobile.push(session, principal, body.invoice_id, body.phone, body.channel)


# ---------------------------------------------------------------- reversals


@router.post(
    "/payments/{payment_id}/reversal-requests", response_model=ReversalRequestOut, status_code=201, tags=["payments"]
)
async def request_reversal(
    payment_id: uuid.UUID,
    body: ReversalRequestIn,
    principal: Annotated[Principal, require_permission("payments.reverse_request")],
    session: Session,
):
    request = await service.request_reversal(session, principal, payment_id, body.reason)
    return next(r for r in await service.reversal_requests(session, principal, None) if r.id == request.id)


@router.get("/reversal-requests", response_model=list[ReversalRequestOut], tags=["payments"])
async def list_reversals(
    principal: Annotated[Principal, require_permission("payments.reverse_request", "payments.reverse_approve")],
    session: Session,
    status: Annotated[Literal["PENDING", "APPROVED", "REJECTED"] | None, Query()] = None,
):
    return await service.reversal_requests(session, principal, status)


@router.post(
    "/reversal-requests/{request_id}/approve",
    response_model=ReversalRequestOut,
    tags=["payments"],
    responses={403: {"description": "approver is the requester (maker-checker)"}},
)
async def approve_reversal(
    request_id: uuid.UUID,
    body: DecisionNoteIn,
    principal: Annotated[Principal, require_permission("payments.reverse_approve")],
    session: Session,
):
    request = await service.approve_reversal(session, principal, request_id, body.note)
    return next(r for r in await service.reversal_requests(session, principal, None) if r.id == request.id)


@router.post("/reversal-requests/{request_id}/reject", response_model=ReversalRequestOut, tags=["payments"])
async def reject_reversal(
    request_id: uuid.UUID,
    body: DecisionNoteIn,
    principal: Annotated[Principal, require_permission("payments.reverse_approve")],
    session: Session,
):
    request = await service.reject_reversal(session, principal, request_id, body.note or "—")
    return next(r for r in await service.reversal_requests(session, principal, None) if r.id == request.id)


# ---------------------------------------------------------------- bank deposits


@router.post(
    "/bank-deposits",
    response_model=BankDepositOut,
    status_code=201,
    tags=["bank"],
    summary="Bursar or parent reports a bank deposit; the bank officer confirms it",
)
async def submit_deposit(body: BankDepositIn, principal: Signed, session: Session):
    if not (principal.has("payments.record") or principal.has("portal.parent")):
        raise forbidden()
    return await service.submit_deposit(session, principal, body)


@router.get("/bank-deposits", response_model=list[BankDepositOut], tags=["bank"])
async def list_deposits(
    _: Annotated[Principal, require_permission("payments.confirm_bank", "payments.record")],
    session: Session,
    status: Annotated[DepositStatus | None, Query()] = None,
):
    where = [BankDeposit.status == status] if status else []
    return await crud.list_live(session, BankDeposit, BankDeposit.created_at.desc(), where=where)


@router.post("/bank-deposits/{deposit_id}/confirm", response_model=BankDepositOut, tags=["bank"])
async def confirm_deposit(
    deposit_id: uuid.UUID,
    body: DecisionNoteIn,
    principal: Annotated[Principal, require_permission("payments.confirm_bank")],
    session: Session,
):
    deposit, call = await service.decide_deposit(session, principal, deposit_id, True, body.note)
    _dispatch(call)
    return deposit


@router.post("/bank-deposits/{deposit_id}/reject", response_model=BankDepositOut, tags=["bank"])
async def reject_deposit(
    deposit_id: uuid.UUID,
    body: DecisionNoteIn,
    principal: Annotated[Principal, require_permission("payments.confirm_bank")],
    session: Session,
):
    deposit, _ = await service.decide_deposit(session, principal, deposit_id, False, body.note or "Rejected")
    return deposit


# ---------------------------------------------------------------- reconciliation


@router.post(
    "/reconciliation-runs",
    response_model=ReconciliationRunOut,
    status_code=201,
    tags=["reconciliation"],
    summary="Upload the day's statement (CSV: external_ref, amount) for one channel",
)
async def create_run(
    run_date: Annotated[date, Form()],
    channel: Annotated[Channel, Form()],
    file: Annotated[UploadFile, File()],
    principal: Annotated[Principal, require_permission("reconciliation.run")],
    session: Session,
):
    data = await read_limited(file, 5 * 1024 * 1024)
    return await reconciliation.out(session, await reconciliation.run(session, principal, run_date, channel, data))


@router.get("/reconciliation-runs", response_model=list[ReconciliationRunOut], tags=["reconciliation"])
async def list_runs(
    _: Annotated[Principal, require_permission("reconciliation.run", "finance.read")], session: Session
):
    runs = await crud.list_live(session, ReconciliationRun, ReconciliationRun.run_date.desc(), limit=100)
    return await reconciliation.out_many(session, list(runs))


@router.get("/reconciliation-runs/{run_id}", response_model=ReconciliationRunOut, tags=["reconciliation"])
async def get_run(
    run_id: uuid.UUID,
    _: Annotated[Principal, require_permission("reconciliation.run", "finance.read")],
    session: Session,
):
    return await reconciliation.out(session, await crud.get_live(session, ReconciliationRun, run_id))


@router.patch("/reconciliation-items/{item_id}", response_model=ReconciliationItemOut, tags=["reconciliation"])
async def resolve_item(
    item_id: uuid.UUID,
    body: ResolveIn,
    principal: Annotated[Principal, require_permission("reconciliation.run")],
    session: Session,
):
    return await reconciliation.resolve(session, principal, item_id, body.note, body.payment_id)


# ---------------------------------------------------------------- reports and reminders


def _maybe_xlsx(rows: list[dict], name: str, fmt: str | None, payload):
    if fmt == "xlsx":
        return Response(
            fee_reports.xlsx(rows),
            media_type=XLSX,
            headers={"Content-Disposition": f'attachment; filename="{name}.xlsx"'},
        )
    return fee_reports.money_json(payload)


@router.get("/reports/fees/aging", tags=["reports"], summary="Outstanding invoices by age (1–30, 31–60, 61–90, 90+)")
async def aging(_: Finance, session: Session, format: Literal["json", "xlsx"] | None = None):
    report = await fee_reports.aging(session)
    return _maybe_xlsx(report["rows"], "aging", format, report)


@router.get("/reports/fees/defaulters", tags=["reports"])
async def defaulters(
    _: Finance,
    session: Session,
    class_id: uuid.UUID | None = None,
    min_balance: Annotated[Decimal, Query(ge=0)] = Decimal("0"),
    format: Literal["json", "xlsx"] | None = None,
):
    rows = await fee_reports.defaulters(session, class_id, min_balance)
    return _maybe_xlsx(rows, "defaulters", format, {"rows": rows})


@router.get("/reports/fees/collections", tags=["reports"], summary="Confirmed payments per day and channel")
async def collections(
    start: Annotated[date, Query(alias="from")],
    end: Annotated[date, Query(alias="to")],
    _: Finance,
    session: Session,
    format: Literal["json", "xlsx"] | None = None,
):
    report = await fee_reports.collections(session, start, end)
    return _maybe_xlsx(report["rows"], "collections", format, report)


@router.post("/fees/reminders/run", tags=["reports"], summary="Send overdue reminders now (once per installment)")
async def reminders(principal: Annotated[Principal, require_permission("invoices.manage")], session: Session):
    calls = await fee_reports.remind(session, principal.school_id, date.today())
    for call in calls:
        get_dispatcher().send("sms.send", **call)
    return {"queued": len(calls)}
