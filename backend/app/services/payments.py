"""UC-08 Record Transaction: invoices, manual payments, GePG payments, reversals, statements."""
from datetime import timedelta
from decimal import Decimal

from sqlalchemy import or_, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from app.core.errors import AppError, not_found, rule_violation
from app.integrations.gepg import PaymentNotification
from app.models import (CourseOffering, FeeStructure, Invoice, InvoiceItem, Student, Term, Transaction, User,
                        invoice_balances)
from app.models.enums import (PaymentMethod, TransactionSource, TransactionStatus, TransactionType)
from app.schemas.transactions import PaymentIn
from app.services.common import next_number, now_eat

INVOICE_DUE_DAYS = 30


def raise_invoice(db: Session, student: Student, offering: CourseOffering, term: Term,
                  actor: User | None) -> Invoice | None:
    """Bill the term's fee structure for the student's level and course. None if no fees apply."""
    fees = db.scalars(select(FeeStructure).where(
        FeeStructure.term_id == term.term_id, FeeStructure.level_id == offering.level_id,
        or_(FeeStructure.course_id.is_(None), FeeStructure.course_id == offering.course_id),
        FeeStructure.amount_tzs > 0,
    ).order_by(FeeStructure.fee_structure_id)).all()
    if not fees:
        return None
    invoice = Invoice(invoice_no=next_number(db, "invoice"), student_id=student.student_id, term_id=term.term_id,
                      due_date=max(term.start_date, now_eat().date()) + timedelta(days=INVOICE_DUE_DAYS),
                      issued_by=actor.user_id if actor else None,
                      items=[InvoiceItem(fee_structure_id=f.fee_structure_id, description=f.description,
                                         amount_tzs=f.amount_tzs) for f in fees])
    db.add(invoice)
    db.flush()
    return invoice


def invoice_balance(db: Session, invoice_id: int):
    return db.execute(select(invoice_balances).where(invoice_balances.c.invoice_id == invoice_id)).mappings().one()


def record_manual(db: Session, data: PaymentIn, actor: User) -> Transaction:
    student = db.get(Student, data.student_id)
    if student is None:
        raise not_found("Student")
    if data.invoice_id is not None:
        invoice = db.get(Invoice, data.invoice_id)
        if invoice is None or invoice.student_id != data.student_id:
            raise rule_violation("Invoice does not belong to this student", "Ankara si ya mwanafunzi huyu")
        if invoice.cancelled_at is not None:
            raise rule_violation("Invoice is cancelled", "Ankara imefutwa", status_code=409)
    trans = Transaction(
        trans_no=next_number(db, "transaction"), trans_type=TransactionType.PAYMENT,
        trans_name=data.trans_name or f"Fee payment ({data.payment_method.value})",
        student_id=data.student_id, invoice_id=data.invoice_id, amount_tzs=data.amount_tzs,
        payment_method=data.payment_method, reference_no=data.reference_no, payer_name=data.payer_name,
        payer_phone=data.payer_phone, status=TransactionStatus.COMPLETED, source=TransactionSource.MANUAL,
        trans_date=data.trans_date or now_eat(), recorded_by=actor.user_id,
    )
    db.add(trans)
    db.flush()                         # UNIQUE (payment_method, reference_no) -> 409 on double posting
    return trans


def reverse(db: Session, trans_id: int, reason: str, actor: User) -> Transaction:
    original = db.get(Transaction, trans_id)
    if original is None:
        raise not_found("Transaction")
    if original.trans_type not in (TransactionType.PAYMENT, TransactionType.WAIVER) \
            or original.status != TransactionStatus.COMPLETED:
        raise rule_violation("Only completed payments and waivers can be reversed",
                             "Malipo na misamaha iliyokamilika pekee ndiyo inaweza kubatilishwa", status_code=409)
    reversal = Transaction(
        trans_no=next_number(db, "transaction"), trans_type=TransactionType.REVERSAL,
        trans_name=f"Reversal of {original.trans_no}: {reason}"[:120], student_id=original.student_id,
        invoice_id=original.invoice_id, amount_tzs=original.amount_tzs, status=TransactionStatus.COMPLETED,
        source=TransactionSource.MANUAL, reverses_trans_id=original.trans_id, recorded_by=actor.user_id,
    )
    db.add(reversal)
    db.flush()                         # UNIQUE reverses_trans_id -> a transaction is reversed once
    return reversal


def record_gateway_payment(db: Session, n: PaymentNotification) -> Transaction | None:
    """Idempotent: the same GePG receipt posted twice creates one transaction. None = unknown bill."""
    invoice = db.scalar(select(Invoice).where(Invoice.gepg_control_no == n.control_no))
    if invoice is None:
        return None
    stmt = insert(Transaction).values(
        trans_no=next_number(db, "transaction"), trans_type=TransactionType.PAYMENT.value,
        trans_name=f"GePG payment {n.control_no} via {n.channel or 'PSP'}"[:120],
        student_id=invoice.student_id, invoice_id=invoice.invoice_id, amount_tzs=n.amount_tzs,
        payment_method=PaymentMethod.GEPG.value, reference_no=n.receipt_no, payer_name=n.payer_name,
        payer_phone=n.payer_phone, status=TransactionStatus.COMPLETED.value,
        source=TransactionSource.GEPG.value, trans_date=n.paid_at,
    ).on_conflict_do_nothing(constraint="uq_trans_reference").returning(Transaction.trans_id)
    trans_id = db.execute(stmt).scalar_one_or_none()
    if trans_id is None:
        trans_id = db.scalar(select(Transaction.trans_id).where(
            Transaction.payment_method == PaymentMethod.GEPG, Transaction.reference_no == n.receipt_no))
    return db.get(Transaction, trans_id)


def statement(db: Session, student: Student) -> dict:
    invoices = db.execute(select(invoice_balances).where(invoice_balances.c.student_id == student.student_id)
                          .order_by(invoice_balances.c.invoice_id)).mappings().all()
    transactions = db.scalars(select(Transaction).where(Transaction.student_id == student.student_id)
                              .order_by(Transaction.trans_date)).all()
    total = sum((i["balance_tzs"] for i in invoices if i["payment_status"] != "CANCELLED"), Decimal("0"))
    return {"student_id": student.student_id, "admission_no": student.admission_no,
            "student_name": student.user.full_name, "invoices": [dict(i) for i in invoices],
            "transactions": list(transactions), "total_balance_tzs": total}


def set_control_number(db: Session, invoice_id: int, control_no: str) -> Invoice:
    invoice = db.get(Invoice, invoice_id)
    if invoice is None:
        raise not_found("Invoice")
    if invoice.gepg_control_no and invoice.gepg_control_no != control_no:
        raise AppError(409, "CONTROL_NO_EXISTS", "Invoice already has a control number",
                       "Ankara tayari ina namba ya malipo")
    invoice.gepg_control_no = control_no
    db.flush()
    return invoice
