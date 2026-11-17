"""Payments: processing (allocation, journal, receipt, SMS), manual cash/bank entry, bank deposits, reversals
(maker-checker) and the receipt PDF (design 13-io-specifications O-02).

Processing is idempotent: a payment that already has a receipt is left alone, so callbacks and retries are safe.
"""

import io
import uuid
from datetime import UTC, datetime
from decimal import Decimal

from reportlab.lib.pagesizes import A5
from reportlab.lib.units import mm
from reportlab.pdfgen import canvas
from sqlalchemy import and_, func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import Principal
from app.core.crypto import get_cipher
from app.core.errors import AppError, forbidden, not_found
from app.core.phone import normalise_phone
from app.db.session import school_session
from app.models import (
    BankDeposit,
    GepgBill,
    Guardian,
    Invoice,
    MessageTemplate,
    Payment,
    PaymentAllocation,
    PaymentReversal,
    PaymentReversalRequest,
    Receipt,
    School,
    SmsMessage,
    Student,
    StudentGuardian,
    User,
)
from app.models.enums import Channel, DepositStatus, GepgStatus, JournalSource, PaymentStatus, RequestStatus, UserStatus
from app.schemas.finance import BankDepositIn, PaymentIn, ReversalRequestOut
from app.services import ledger, sms
from app.services.invoices import guardian_of, may_see_student
from app.services.ledger import Line
from app.services.onboarding import TEMPLATES
from app.services.people import decrypt_phone, now
from app.tasks.dispatch import get_dispatcher


def phone_fields(raw: str | None) -> dict:
    if not raw:
        return {}
    phone = normalise_phone(raw)
    return {"payer_phone_hash": get_cipher().blind_index(phone, sms.PHONE_FIELD), "payer_phone_last4": phone[-4:]}


# ---------------------------------------------------------------- processing


async def process(session: AsyncSession, payment_id: uuid.UUID, actor: uuid.UUID | None) -> dict | None:
    """Allocate a CONFIRMED payment (its GePG bill's invoice first, then oldest due first), post the journal,
    issue the receipt and queue the receipt SMS. Returns the SMS task call, or None."""
    payment = (await session.execute(select(Payment).where(Payment.id == payment_id).with_for_update())).scalar_one()
    if payment.status != PaymentStatus.CONFIRMED:
        return None
    if (await session.execute(select(Receipt.id).where(Receipt.payment_id == payment.id))).first():
        return None  # already processed
    bill = None
    if payment.gepg_bill_id:
        bill = (
            await session.execute(select(GepgBill).where(GepgBill.id == payment.gepg_bill_id).with_for_update())
        ).scalar_one_or_none()
    invoices = (
        (
            await session.execute(
                select(Invoice)
                .where(
                    Invoice.student_id == payment.student_id, Invoice.cancelled_at.is_(None), Invoice.balance_tzs > 0
                )
                .order_by(Invoice.due_date, Invoice.issued_at)
                .with_for_update()
            )
        )
        .scalars()
        .all()
    )
    if bill:
        invoices = sorted(invoices, key=lambda i: i.id != bill.invoice_id)  # the bill's invoice first
    remaining = payment.amount_tzs
    for invoice in invoices:
        if remaining <= 0:
            break
        take = min(remaining, invoice.balance_tzs)
        session.add(
            PaymentAllocation(
                school_id=payment.school_id,
                payment_id=payment.id,
                invoice_id=invoice.id,
                amount_tzs=take,
                created_by=actor,
            )
        )
        await session.flush()  # guard trigger: same student, open, no over-allocation
        remaining -= take
    allocated = payment.amount_tzs - remaining
    when = payment.confirmed_at or now()
    await ledger.post(
        session,
        school_id=payment.school_id,
        source_type=JournalSource.PAYMENT,
        source_id=payment.id,
        memo=f"Payment {payment.channel} {payment.external_ref}",
        posted_by=actor,
        when=when,
        lines=[
            Line(await ledger.account(session, ledger.clearing_code(payment.channel)), debit=payment.amount_tzs),
            Line(await ledger.account(session, ledger.RECEIVABLE), credit=allocated, student_id=payment.student_id),
            Line(await ledger.account(session, ledger.CREDIT), credit=remaining, student_id=payment.student_id),
        ],
    )
    receipt = Receipt(
        school_id=payment.school_id,
        payment_id=payment.id,
        created_by=actor,
        receipt_no=await ledger.next_number(session, payment.school_id, "RECEIPT", when.year, "RCT"),
    )
    session.add(receipt)
    if bill:
        bill_invoice = next((i for i in invoices if i.id == bill.invoice_id), None)
        if bill_invoice is not None:
            await session.refresh(bill_invoice)
            if bill_invoice.balance_tzs <= 0 and bill.status == GepgStatus.ISSUED:
                bill.status = GepgStatus.PAID
    await session.flush()
    return await _receipt_sms(session, payment, receipt)


async def _primary_guardian(session: AsyncSession, student_id: uuid.UUID) -> User | None:
    return (
        await session.execute(
            select(User)
            .join(Guardian, Guardian.user_id == User.id)
            .join(
                StudentGuardian,
                and_(StudentGuardian.guardian_id == Guardian.id, StudentGuardian.student_id == student_id),
            )
            .where(
                StudentGuardian.is_primary.is_(True),
                StudentGuardian.receives_sms.is_(True),
                StudentGuardian.deleted_at.is_(None),
                User.status == UserStatus.ACTIVE,
            )
        )
    ).scalar_one_or_none()


async def template_text(session: AsyncSession, key: str, lang: str) -> str:
    body = (
        await session.execute(
            select(MessageTemplate.body).where(
                MessageTemplate.key == key,
                MessageTemplate.language == lang,
                MessageTemplate.is_active.is_(True),
                MessageTemplate.deleted_at.is_(None),
            )
        )
    ).scalar()
    return body or TEMPLATES[key][0 if lang == "sw" else 1]


async def _receipt_sms(session: AsyncSession, payment: Payment, receipt: Receipt) -> dict | None:
    guardian = await _primary_guardian(session, payment.student_id)
    phone = decrypt_phone(guardian) if guardian else None
    key = f"receipt:{payment.id.hex}"
    if not phone or (await session.execute(select(SmsMessage.id).where(SmsMessage.idempotency_key == key))).first():
        return None
    lang = guardian.preferred_language
    school = (await session.execute(select(School.name))).scalar_one()
    learner = (
        await session.execute(
            select(User.first_name).join(Student, Student.user_id == User.id).where(Student.id == payment.student_id)
        )
    ).scalar()
    balance = (
        await session.execute(
            select(func.coalesce(func.sum(Invoice.balance_tzs), 0)).where(
                Invoice.student_id == payment.student_id, Invoice.cancelled_at.is_(None), Invoice.balance_tzs > 0
            )
        )
    ).scalar()
    body = (await template_text(session, "payment_receipt", lang)).format(
        school=school[:40],
        amount=ledger.tzs(payment.amount_tzs),
        student=learner,
        receipt_no=receipt.receipt_no,
        balance=ledger.tzs(Decimal(balance)),
    )
    message = await sms.queue_sms(
        session,
        school_id=payment.school_id,
        phone=phone,
        body=body,
        language=lang,
        to_user_id=guardian.id,
        template_key="payment_receipt",
        idempotency_key=key,
        related_entity="receipts",
        related_id=receipt.id,
    )
    receipt.sms_sent_at = now()
    return {"sms_id": str(message.id), "school_id": str(payment.school_id)}


async def run_processing(payment_id: str, school_id: str) -> str:
    """Celery entry point for callbacks: idempotent."""
    async with school_session(uuid.UUID(school_id)) as session:
        call = await process(session, uuid.UUID(payment_id), None)
        await session.commit()
    if call:
        get_dispatcher().send("sms.send", **call)
    return "processed"


# ---------------------------------------------------------------- manual entry and bank deposits


async def record_manual(session: AsyncSession, principal: Principal, body: PaymentIn) -> tuple[Payment, dict | None]:
    """Cash (receipt-book number) or a bank slip the bursar has seen: confirmed at once and processed.
    The caller commits (so the Idempotency-Key row is stored in the same transaction)."""
    await _student(session, body.student_id)
    payment = Payment(
        school_id=principal.school_id,
        student_id=body.student_id,
        channel=body.channel,
        external_ref=body.external_ref.strip(),
        amount_tzs=body.amount_tzs,
        payer_name=body.payer_name,
        status=PaymentStatus.CONFIRMED,
        received_at=body.received_at,
        confirmed_at=now(),
        recorded_by=principal.user_id,
        created_by=principal.user_id,
        raw_payload={"entered_by": "bursar"},
        **phone_fields(body.payer_phone),
    )
    session.add(payment)
    await _flush_or_duplicate(session)
    call = await process(session, payment.id, principal.user_id)
    return payment, call


async def _flush_or_duplicate(session: AsyncSession) -> None:
    try:
        await session.flush()
    except IntegrityError as exc:
        if getattr(exc.orig, "sqlstate", None) == "23505":
            raise AppError(409, "DUPLICATE", [{"field": "external_ref", "code": "duplicate_in_school"}]) from None
        raise


async def _student(session: AsyncSession, student_id: uuid.UUID) -> Student:
    student = (
        await session.execute(select(Student).where(Student.id == student_id, Student.deleted_at.is_(None)))
    ).scalar_one_or_none()
    if student is None:
        raise AppError(422, "INVALID_REFERENCE", [{"field": "student_id", "code": "invalid_value"}])
    return student


async def submit_deposit(session: AsyncSession, principal: Principal, body: BankDepositIn) -> BankDeposit:
    await _student(session, body.student_id)
    if not principal.has("payments.record") and not await guardian_of(session, principal, body.student_id):
        raise forbidden()
    deposit = BankDeposit(
        school_id=principal.school_id,
        submitted_by=principal.user_id,
        created_by=principal.user_id,
        status=DepositStatus.SUBMITTED,
        **body.model_dump(),
    )
    session.add(deposit)
    await _flush_or_duplicate(session)
    await session.commit()
    return deposit


async def decide_deposit(
    session: AsyncSession, principal: Principal, deposit_id: uuid.UUID, confirm: bool, note: str | None
) -> tuple[BankDeposit, dict | None]:
    """The bank officer confirms (a BANK payment is created and processed) or rejects the deposit."""
    deposit = (
        await session.execute(select(BankDeposit).where(BankDeposit.id == deposit_id).with_for_update())
    ).scalar_one_or_none()
    if deposit is None:
        raise not_found()
    if deposit.status != DepositStatus.SUBMITTED:
        raise AppError(409, "NOT_ALLOWED", [{"field": "status", "code": "invalid_value"}])
    deposit.confirmed_by, deposit.confirmed_at, deposit.note = principal.user_id, now(), note
    call = None
    if not confirm:
        deposit.status = DepositStatus.REJECTED
    else:
        payment = Payment(
            school_id=principal.school_id,
            student_id=deposit.student_id,
            channel=Channel.BANK,
            external_ref=deposit.bank_reference,
            amount_tzs=deposit.amount_tzs,
            payer_name=deposit.depositor_name,
            status=PaymentStatus.CONFIRMED,
            received_at=datetime.combine(deposit.deposit_date, datetime.min.time(), UTC),
            confirmed_at=now(),
            recorded_by=principal.user_id,
            created_by=principal.user_id,
            raw_payload={"bank_deposit_id": str(deposit.id)},
        )
        session.add(payment)
        await _flush_or_duplicate(session)
        deposit.status, deposit.payment_id = DepositStatus.MATCHED, payment.id
        call = await process(session, payment.id, principal.user_id)
    await session.commit()
    return deposit, call


# ---------------------------------------------------------------- reversals (maker-checker)


async def request_reversal(
    session: AsyncSession, principal: Principal, payment_id: uuid.UUID, reason: str
) -> PaymentReversalRequest:
    payment = (await session.execute(select(Payment).where(Payment.id == payment_id))).scalar_one_or_none()
    if payment is None:
        raise not_found()
    if payment.status != PaymentStatus.CONFIRMED:
        raise AppError(409, "NOT_ALLOWED", [{"field": "status", "code": "invalid_value"}])
    request = PaymentReversalRequest(
        school_id=principal.school_id,
        payment_id=payment.id,
        reason=reason,
        requested_by=principal.user_id,
        created_by=principal.user_id,
    )
    session.add(request)
    try:
        await session.flush()
    except IntegrityError:
        raise AppError(409, "DUPLICATE", [{"field": "payment_id", "code": "pending_request"}]) from None
    await session.commit()
    return request


async def _pending_request(
    session: AsyncSession, principal: Principal, request_id: uuid.UUID
) -> PaymentReversalRequest:
    request = (
        await session.execute(
            select(PaymentReversalRequest).where(PaymentReversalRequest.id == request_id).with_for_update()
        )
    ).scalar_one_or_none()
    if request is None:
        raise not_found()
    if request.requested_by == principal.user_id:
        raise AppError(403, "FORBIDDEN", [{"field": "approver", "code": "maker_checker"}])
    if request.status != RequestStatus.PENDING:
        raise AppError(409, "NOT_ALLOWED", [{"field": "status", "code": "invalid_value"}])
    return request


async def approve_reversal(
    session: AsyncSession, principal: Principal, request_id: uuid.UUID, note: str | None
) -> PaymentReversalRequest:
    """Reverse the payment: REVERSED status (trigger), invoices re-derived, reversing journal."""
    request = await _pending_request(session, principal, request_id)
    payment = (
        await session.execute(select(Payment).where(Payment.id == request.payment_id).with_for_update())
    ).scalar_one()
    if payment.status != PaymentStatus.CONFIRMED:
        raise AppError(409, "NOT_ALLOWED", [{"field": "status", "code": "invalid_value"}])
    allocated = (
        await session.execute(
            select(func.coalesce(func.sum(PaymentAllocation.amount_tzs), 0)).where(
                PaymentAllocation.payment_id == payment.id
            )
        )
    ).scalar()
    reversal = PaymentReversal(
        school_id=payment.school_id,
        payment_id=payment.id,
        reason=request.reason,
        reversed_by=request.requested_by,
        approved_by=principal.user_id,
        created_by=principal.user_id,
    )
    session.add(reversal)
    await session.flush()  # trigger: payment -> REVERSED, invoices re-derived
    await ledger.post(
        session,
        school_id=payment.school_id,
        source_type=JournalSource.REVERSAL,
        source_id=payment.id,
        memo=f"Reversal of {payment.channel} {payment.external_ref}",
        posted_by=principal.user_id,
        when=now(),
        lines=[
            Line(
                await ledger.account(session, ledger.RECEIVABLE),
                debit=Decimal(allocated),
                student_id=payment.student_id,
            ),
            Line(
                await ledger.account(session, ledger.CREDIT),
                debit=payment.amount_tzs - Decimal(allocated),
                student_id=payment.student_id,
            ),
            Line(await ledger.account(session, ledger.clearing_code(payment.channel)), credit=payment.amount_tzs),
        ],
    )
    request.status, request.decided_by, request.decided_at = RequestStatus.APPROVED, principal.user_id, now()
    request.decision_note, request.reversal_id = note, reversal.id
    await session.commit()
    return request


async def reject_reversal(
    session: AsyncSession, principal: Principal, request_id: uuid.UUID, note: str
) -> PaymentReversalRequest:
    request = await _pending_request(session, principal, request_id)
    request.status, request.decided_by, request.decided_at = RequestStatus.REJECTED, principal.user_id, now()
    request.decision_note = note
    await session.commit()
    return request


async def reversal_requests(
    session: AsyncSession, principal: Principal, status: str | None
) -> list[ReversalRequestOut]:
    requester = User.__table__.alias("requester")
    learner = User.__table__.alias("learner")
    stmt = (
        select(
            PaymentReversalRequest,
            Payment.external_ref,
            Payment.amount_tzs,
            learner.c.first_name,
            learner.c.last_name,
            requester.c.first_name.label("r_first"),
            requester.c.last_name.label("r_last"),
        )
        .join(Payment, Payment.id == PaymentReversalRequest.payment_id)
        .join(Student, Student.id == Payment.student_id)
        .join(learner, learner.c.id == Student.user_id)
        .join(requester, requester.c.id == PaymentReversalRequest.requested_by)
    )
    if status:
        stmt = stmt.where(PaymentReversalRequest.status == status)
    if not principal.has("payments.reverse_approve"):
        stmt = stmt.where(PaymentReversalRequest.requested_by == principal.user_id)
    rows = (await session.execute(stmt.order_by(PaymentReversalRequest.created_at.desc()).limit(200))).all()
    return [
        ReversalRequestOut(
            id=r.id,
            payment_id=r.payment_id,
            external_ref=ref,
            amount_tzs=amount,
            student_name=f"{first} {last}",
            reason=r.reason,
            status=r.status,
            requested_by=r.requested_by,
            requested_by_name=f"{rf} {rl}",
            decided_by=r.decided_by,
            decided_at=r.decided_at,
            decision_note=r.decision_note,
        )
        for r, ref, amount, first, last, rf, rl in rows
    ]


# ---------------------------------------------------------------- receipt PDF


async def receipt_pdf(
    session: AsyncSession, principal: Principal, payment_id: uuid.UUID, lang: str
) -> tuple[str, bytes]:
    payment = (await session.execute(select(Payment).where(Payment.id == payment_id))).scalar_one_or_none()
    if payment is None or not await may_see_student(session, principal, payment.student_id):
        raise not_found()
    receipt = (await session.execute(select(Receipt).where(Receipt.payment_id == payment.id))).scalar_one_or_none()
    if receipt is None:
        raise not_found()
    school = (await session.execute(select(School.name))).scalar_one()
    student = (
        await session.execute(
            select(Student.admission_no, User.first_name, User.last_name)
            .join(User, User.id == Student.user_id)
            .where(Student.id == payment.student_id)
        )
    ).one()
    allocations = (
        await session.execute(
            select(Invoice.invoice_no, PaymentAllocation.amount_tzs, Invoice.balance_tzs)
            .join(Invoice, Invoice.id == PaymentAllocation.invoice_id)
            .where(PaymentAllocation.payment_id == payment.id)
        )
    ).all()
    credit = payment.amount_tzs - sum((a.amount_tzs for a in allocations), Decimal("0"))
    sw = lang == "sw"
    out = io.BytesIO()
    c = canvas.Canvas(out, pagesize=A5, pageCompression=1)
    width, height = A5
    y = height - 15 * mm
    c.setFont("Helvetica-Bold", 11)
    c.drawCentredString(width / 2, y, school.upper())
    y -= 8 * mm
    c.drawString(12 * mm, y, f"{'RISITI' if sw else 'RECEIPT'} {receipt.receipt_no}")
    c.setFont("Helvetica", 8.5)
    c.drawRightString(width - 12 * mm, y, f"{receipt.issued_at:%d/%m/%Y %H:%M}")
    rows = [
        (("Mwanafunzi", "Student"), f"{student.first_name} {student.last_name} ({student.admission_no})"),
        (("Kiasi", "Amount"), f"TZS {ledger.tzs(payment.amount_tzs)}"),
        (("", ""), f"({ledger.in_words(payment.amount_tzs, 'sw' if sw else 'en')})"),
        (("Njia", "Channel"), f"{payment.channel} · {'Kumbukumbu' if sw else 'Reference'}: {payment.external_ref}"),
    ]
    rows += [
        (
            ("Imelipiwa ankara", "Paid on invoice"),
            f"{a.invoice_no} (TZS {ledger.tzs(a.amount_tzs)}) · "
            f"{'Salio' if sw else 'Balance'} TZS {ledger.tzs(a.balance_tzs)}",
        )
        for a in allocations
    ]
    rows.append((("Mkopo (credit)", "Credit"), f"TZS {ledger.tzs(credit)}"))
    if payment.status == PaymentStatus.REVERSED:
        rows.append((("HALI", "STATUS"), "IMEBATILISHWA / REVERSED"))
    for label, value in rows:
        y -= 7 * mm
        c.drawString(12 * mm, y, (label[0] if sw else label[1]) + (":" if label[0] else ""))
        c.drawString(45 * mm, y, value[:80])
    c.showPage()
    c.save()
    return receipt.receipt_no, out.getvalue()
