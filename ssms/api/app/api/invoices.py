"""/invoices (generate job, list, detail, cancel, GePG control number, PDF) and /students/{id}/statement."""

import hashlib
import uuid
from datetime import date
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, Header, Query, Response
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import Principal, active_principal, require_permission
from app.api.imports import JobOut, job_out
from app.core.pagination import Cursor, Limit, Page, paginate
from app.core.storage import get_storage
from app.db.session import get_session
from app.models import BackgroundJob, Invoice
from app.models.enums import InvoiceStatus, JobKind, JobStatus
from app.schemas.finance import CancelIn, GenerateInvoicesIn, InvoiceListItem, InvoiceOut, StatementOut
from app.services import crud, gepg, idempotency
from app.services import invoices as service
from app.tasks.dispatch import get_dispatcher

router = APIRouter(tags=["invoices"])
Session = Annotated[AsyncSession, Depends(get_session)]
Manager = Annotated[Principal, require_permission("invoices.manage")]
Signed = Annotated[Principal, Depends(active_principal)]
PDF = "application/pdf"


@router.post(
    "/invoices/generate",
    response_model=JobOut,
    status_code=202,
    summary="Bill every active student of the classes for a term (approved fee structure; job)",
)
async def generate(
    body: GenerateInvoicesIn,
    principal: Manager,
    session: Session,
    idempotency_key: Annotated[str | None, Header(alias="Idempotency-Key")] = None,
):
    key = idempotency.require_key(idempotency_key)
    digest = hashlib.sha256(body.model_dump_json().encode()).hexdigest()
    previous = await idempotency.replay(session, "POST /invoices/generate", key, digest)
    if previous:
        return job_out(await crud.get_live(session, BackgroundJob, uuid.UUID(previous["job_id"])))
    job = BackgroundJob(
        school_id=principal.school_id,
        kind=JobKind.INVOICE_RUN,
        status=JobStatus.QUEUED,
        idempotency_key=key,
        requested_by=principal.user_id,
        created_by=principal.user_id,
    )
    job.input_file_key = get_storage().put(
        service.params_key(principal.school_id, job.id), body.model_dump_json().encode()
    )
    session.add(job)
    idempotency.remember(session, principal, "POST /invoices/generate", key, digest, 202, {"job_id": str(job.id)})
    await session.commit()
    get_dispatcher().send("invoices.generate", job_id=str(job.id), school_id=str(principal.school_id))
    return job_out(job)


@router.get("/invoices", response_model=Page[InvoiceListItem])
async def list_invoices(
    _: Annotated[Principal, require_permission("finance.read")],
    session: Session,
    status: Annotated[InvoiceStatus | None, Query()] = None,
    class_id: uuid.UUID | None = None,
    term_id: uuid.UUID | None = None,
    due_before: date | None = None,
    student_id: uuid.UUID | None = None,
    limit: Limit = 50,
    cursor: Cursor = None,
):
    stmt = service.list_query(status, class_id, term_id, due_before, student_id)
    rows, next_cursor = await paginate(session, stmt, [Invoice.invoice_no, Invoice.id], limit, cursor)
    return Page[InvoiceListItem](items=[service.list_item(r) for r in rows], next_cursor=next_cursor)


@router.get("/invoices/{invoice_id}", response_model=InvoiceOut, summary="Staff with finance.read, or a guardian")
async def get_invoice(invoice_id: uuid.UUID, principal: Signed, session: Session):
    return await service.detail(session, principal, invoice_id)


@router.get("/invoices/{invoice_id}/pdf", response_class=Response, responses={200: {"content": {PDF: {}}}})
async def invoice_pdf(
    invoice_id: uuid.UUID,
    principal: Signed,
    session: Session,
    lang: Annotated[Literal["sw", "en"] | None, Query()] = None,
):
    number, data = await service.pdf(session, principal, invoice_id, lang or principal.language)
    return Response(data, media_type=PDF, headers={"Content-Disposition": f'attachment; filename="{number}.pdf"'})


@router.post(
    "/invoices/{invoice_id}/cancel",
    response_model=InvoiceOut,
    responses={409: {"description": "has payments (reverse them or add a discount instead)"}},
)
async def cancel(invoice_id: uuid.UUID, body: CancelIn, principal: Manager, session: Session):
    return await service.cancel(session, principal, invoice_id, body.reason)


@router.post(
    "/invoices/{invoice_id}/control-number",
    status_code=202,
    responses={409: {"description": "an open bill exists, or nothing to pay"}},
    summary="Ask GePG for a control number for the balance (answer arrives by callback)",
)
async def control_number(invoice_id: uuid.UUID, principal: Manager, session: Session):
    bill = await gepg.request_bill(session, principal, invoice_id)
    get_dispatcher().send("gepg.submit", bill_id=str(bill.id), school_id=str(principal.school_id))
    return {
        "bill_id": str(bill.id),
        "bill_ref": bill.bill_ref,
        "status": bill.status,
        "amount_tzs": str(bill.amount_tzs),
    }


@router.get(
    "/students/{student_id}/statement",
    response_model=StatementOut,
    summary="Invoices, payments, outstanding and credit (staff, guardian or the student)",
)
async def statement(student_id: uuid.UUID, principal: Signed, session: Session):
    return await service.statement(session, principal, student_id)
