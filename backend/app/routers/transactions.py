"""UC-08 Record Transaction: manual payments, reversals, statements and the GePG callback."""
from datetime import date, datetime, time

from fastapi import APIRouter, Depends, Request, Response, status
from sqlalchemy import select

from app.core.errors import AppError
from app.core.i18n import tzs
from app.deps import CurrentUser, DbSession, require_roles
from app.integrations import gepg
from app.models import Student, Transaction, User
from app.models.enums import STAFF_ROLES, PaymentMethod, Role
from app.schemas.transactions import (InvoiceBalanceOut, PaymentIn, PaymentRecorded, ReverseIn, StatementOut,
                                      TransactionOut)
from app.services import notify
from app.services import payments as svc
from app.services.common import EAT
from app.services.students import ensure_can_view, get_student
from app.tasks.payments import request_control_number

router = APIRouter(tags=["Transactions"])
Bursar = Depends(require_roles(Role.BURSAR, Role.ADMIN))


def _receipt_sms(db, trans: Transaction) -> None:
    student = db.get(Student, trans.student_id)
    balance = svc.invoice_balance(db, trans.invoice_id)["balance_tzs"] if trans.invoice_id else 0
    notify.sms_guardians(db, student, "payment_received", primary_only=True, amount=tzs(trans.amount_tzs),
                         trans_no=trans.trans_no, balance=tzs(balance))


@router.post("/transactions", response_model=PaymentRecorded, status_code=status.HTTP_201_CREATED)
def record_payment(body: PaymentIn, db: DbSession, user: User = Bursar):
    """Cash, bank, M-Pesa, Tigo Pesa or Airtel Money receipt. 409 if the reference was already posted."""
    trans = svc.record_manual(db, body, user)
    db.commit()
    _receipt_sms(db, trans)
    invoice = svc.invoice_balance(db, trans.invoice_id) if trans.invoice_id else None
    return PaymentRecorded(transaction=TransactionOut.model_validate(trans),
                           invoice=InvoiceBalanceOut.model_validate(dict(invoice)) if invoice else None)


@router.post("/transactions/{trans_id}/reverse", response_model=TransactionOut,
             status_code=status.HTTP_201_CREATED)
def reverse(trans_id: int, body: ReverseIn, db: DbSession, user: User = Depends(require_roles(Role.ADMIN))):
    """Never edits the original: posts a linked REVERSAL entry."""
    reversal = svc.reverse(db, trans_id, body.reason, user)
    db.commit()
    return reversal


@router.get("/transactions", response_model=list[TransactionOut],
            dependencies=[Depends(require_roles(*STAFF_ROLES))])
def transaction_history(db: DbSession, student_id: int | None = None, date_from: date | None = None,
                        date_to: date | None = None, method: PaymentMethod | None = None, limit: int = 200):
    stmt = select(Transaction).order_by(Transaction.trans_date.desc())
    if student_id:
        stmt = stmt.where(Transaction.student_id == student_id)
    if date_from:
        stmt = stmt.where(Transaction.trans_date >= datetime.combine(date_from, time.min, EAT))
    if date_to:
        stmt = stmt.where(Transaction.trans_date <= datetime.combine(date_to, time.max, EAT))
    if method:
        stmt = stmt.where(Transaction.payment_method == method)
    return db.scalars(stmt.limit(min(limit, 1000))).all()


@router.get("/students/{student_id}/statement", response_model=StatementOut)
def student_statement(student_id: int, db: DbSession, user: CurrentUser):
    """Invoices with balances and every transaction. Students/parents see only their own."""
    student = get_student(db, student_id)
    ensure_can_view(db, user, student)
    return StatementOut.model_validate(svc.statement(db, student), from_attributes=True)


@router.post("/invoices/{invoice_id}/control-number", status_code=status.HTTP_202_ACCEPTED,
             dependencies=[Bursar])
def request_control_no(invoice_id: int):
    """Queue a GePG bill submission; the control number arrives by callback."""
    request_control_number.delay(invoice_id)
    return {"invoice_id": invoice_id, "status": "queued"}


@router.post("/payments/gepg/callback", include_in_schema=False)
async def gepg_payment_callback(request: Request, db: DbSession):
    """Signed GePG payment notification. Idempotent; always acknowledges a valid message."""
    body = await request.body()
    try:
        notification = gepg.parse_payment_notification(body)
    except gepg.SignatureError:
        raise AppError(401, "BAD_SIGNATURE", "Invalid GePG signature", "Sahihi ya GePG si sahihi")
    trans = svc.record_gateway_payment(db, notification)
    db.commit()
    if trans is not None:
        _receipt_sms(db, trans)
    return Response(gepg.acknowledgement(), media_type="application/xml")
