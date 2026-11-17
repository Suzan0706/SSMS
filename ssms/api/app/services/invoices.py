"""Invoices: generation from the approved fee structure, discounts, installments, credit applied, journals,
cancellation, statement and the invoice PDF (design 13-io-specifications O-03).

Totals, paid amount and status are derived by the database from lines and allocations (trg_invoices_derive).
"""

import io
import json
import uuid
from collections import defaultdict
from datetime import UTC, datetime
from decimal import ROUND_HALF_UP, Decimal

from reportlab.lib.pagesizes import A4
from reportlab.lib.units import mm
from reportlab.pdfgen import canvas
from sqlalchemy import and_, func, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import Principal, load_access
from app.core.errors import AppError, not_found
from app.core.i18n import message
from app.core.storage import get_storage
from app.db.session import DbContext, school_session, set_context
from app.models import (
    AcademicYear,
    BackgroundJob,
    DiscountRule,
    Enrolment,
    FeeItem,
    FeeStructure,
    FeeStructureLine,
    GepgBill,
    Guardian,
    Invoice,
    InvoiceInstallment,
    InvoiceLine,
    Payment,
    PaymentAllocation,
    Receipt,
    School,
    SchoolClass,
    SchoolSettings,
    Stream,
    Student,
    StudentDiscount,
    StudentGuardian,
    Term,
    User,
)
from app.models.enums import (
    EnrolmentStatus,
    FeeStructureStatus,
    GepgStatus,
    JobKind,
    JobStatus,
    JournalSource,
    LineKind,
)
from app.schemas.finance import (
    AllocationOut,
    GenerateInvoicesIn,
    InstallmentOut,
    InvoiceLineOut,
    InvoiceListItem,
    InvoiceOut,
    PaymentOut,
    ReceiptOut,
    StatementOut,
)
from app.services import facility_fees, imports, ledger
from app.services.ledger import Line
from app.services.people import now

CENT = Decimal("0.01")


def _round(value: Decimal) -> Decimal:
    return value.quantize(CENT, rounding=ROUND_HALF_UP)


# ---------------------------------------------------------------- access


async def guardian_of(session: AsyncSession, principal: Principal, student_id: uuid.UUID) -> bool:
    return bool(
        (
            await session.execute(
                select(StudentGuardian.id)
                .join(Guardian, Guardian.id == StudentGuardian.guardian_id)
                .where(
                    StudentGuardian.student_id == student_id,
                    StudentGuardian.deleted_at.is_(None),
                    Guardian.user_id == principal.user_id,
                )
            )
        ).first()
    )


async def may_see_student(session: AsyncSession, principal: Principal, student_id: uuid.UUID) -> bool:
    if principal.has("finance.read") or principal.has("payments.record"):
        return True
    if principal.has("portal.parent") and await guardian_of(session, principal, student_id):
        return True
    student_user = (await session.execute(select(Student.user_id).where(Student.id == student_id))).scalar()
    return principal.has("portal.student") and student_user == principal.user_id


# ---------------------------------------------------------------- credit and journals


async def apply_credit(
    session: AsyncSession, school_id: uuid.UUID, student_id: uuid.UUID, actor: uuid.UUID | None, when: datetime
) -> Decimal:
    """Use the student's unallocated confirmed payments (credit) on open invoices, oldest due first."""
    credits = (
        await session.execute(
            text(
                "SELECT u.payment_id, u.unallocated_tzs FROM v_payment_unallocated u "
                "JOIN payments p ON p.id = u.payment_id "
                "WHERE u.student_id = :student AND u.unallocated_tzs > 0 ORDER BY p.received_at, p.id"
            ).bindparams(student=student_id)
        )
    ).all()
    if not credits:
        return Decimal("0")
    invoices = (
        (
            await session.execute(
                select(Invoice)
                .where(Invoice.student_id == student_id, Invoice.cancelled_at.is_(None), Invoice.balance_tzs > 0)
                .order_by(Invoice.due_date, Invoice.issued_at)
                .with_for_update()
            )
        )
        .scalars()
        .all()
    )
    applied = Decimal("0")
    pool = [[pid, Decimal(amount)] for pid, amount in credits]
    for invoice in invoices:
        need = invoice.balance_tzs
        for entry in pool:
            if need <= 0:
                break
            take = min(entry[1], need)
            if take <= 0:
                continue
            existing = (
                await session.execute(
                    select(PaymentAllocation).where(
                        PaymentAllocation.payment_id == entry[0], PaymentAllocation.invoice_id == invoice.id
                    )
                )
            ).scalar()
            if existing:  # one allocation row per payment and invoice
                continue
            session.add(
                PaymentAllocation(
                    school_id=school_id, payment_id=entry[0], invoice_id=invoice.id, amount_tzs=take, created_by=actor
                )
            )
            await session.flush()
            entry[1] -= take
            need -= take
            applied += take
    if applied > 0:
        await ledger.post(
            session,
            school_id=school_id,
            source_type=JournalSource.ADJUSTMENT,
            source_id=student_id,
            memo="Student credit applied to invoices",
            posted_by=actor,
            when=when,
            lines=[
                Line(await ledger.account(session, ledger.CREDIT), debit=applied, student_id=student_id),
                Line(await ledger.account(session, ledger.RECEIVABLE), credit=applied, student_id=student_id),
            ],
        )
    return applied


async def _invoice_journal(session: AsyncSession, invoice: Invoice, lines: list[InvoiceLine], actor, reverse=False):
    items = {i.id: i.income_account_id for i in (await session.execute(select(FeeItem))).scalars()}
    charges: dict[uuid.UUID, Decimal] = defaultdict(lambda: Decimal("0"))
    discount = Decimal("0")
    for line in lines:
        if line.kind == LineKind.CHARGE:
            charges[items[line.fee_item_id]] += line.amount_tzs
        else:
            discount += line.amount_tzs
    total = sum(charges.values(), Decimal("0")) - discount
    receivable = await ledger.account(session, ledger.RECEIVABLE)
    entries = [Line(receivable, debit=total, student_id=invoice.student_id)]
    if discount:
        entries.append(Line(await ledger.account(session, ledger.DISCOUNTS), debit=discount))
    entries += [Line(account_id, credit=amount) for account_id, amount in charges.items()]
    if reverse:
        entries = [Line(e.account_id, debit=e.credit, credit=e.debit, student_id=e.student_id) for e in entries]
    await ledger.post(
        session,
        school_id=invoice.school_id,
        source_type=JournalSource.INVOICE_CANCEL if reverse else JournalSource.INVOICE,
        source_id=invoice.id,
        memo=f"{'Cancel ' if reverse else ''}Invoice {invoice.invoice_no}",
        lines=entries,
        posted_by=actor,
        when=now(),
    )


# ---------------------------------------------------------------- generation


async def _structure(session: AsyncSession, year_id: uuid.UUID, class_id: uuid.UUID) -> FeeStructure | None:
    return (
        await session.execute(
            select(FeeStructure).where(
                FeeStructure.academic_year_id == year_id,
                FeeStructure.class_id == class_id,
                FeeStructure.status == FeeStructureStatus.APPROVED,
                FeeStructure.deleted_at.is_(None),
            )
        )
    ).scalar_one_or_none()


async def _discount_lines(
    session: AsyncSession,
    student_id: uuid.UUID,
    year_id: uuid.UUID,
    charges: list[tuple[uuid.UUID, str, Decimal]],
    tuition_item: uuid.UUID | None,
):
    rules = (
        (
            await session.execute(
                select(DiscountRule)
                .join(StudentDiscount, StudentDiscount.discount_rule_id == DiscountRule.id)
                .where(
                    StudentDiscount.student_id == student_id,
                    StudentDiscount.academic_year_id == year_id,
                    StudentDiscount.deleted_at.is_(None),
                    DiscountRule.deleted_at.is_(None),
                )
            )
        )
        .scalars()
        .all()
    )
    tuition = sum((a for item, _, a in charges if item == tuition_item), Decimal("0"))
    total = sum((a for _, _, a in charges), Decimal("0"))
    out = []
    for rule in rules:
        amount = _round(tuition * rule.percent / 100) if rule.percent else min(rule.amount_tzs, total)
        amount = min(amount, total - sum((x[2] for x in out), Decimal("0")))
        if amount > 0:
            out.append((rule, tuition_item or charges[0][0], amount))
    return out


async def generate(session: AsyncSession, principal: Principal, body: GenerateInvoicesIn) -> tuple[list, list[dict]]:
    """Invoices for every active student of the classes; returns (created rows, problems). Nothing is written when
    any class has no approved fee structure."""
    term = (
        await session.execute(select(Term).where(Term.id == body.term_id, Term.deleted_at.is_(None)))
    ).scalar_one_or_none()
    if term is None:
        raise not_found()
    year = (await session.execute(select(AcademicYear).where(AcademicYear.id == term.academic_year_id))).scalar_one()
    first_term = (
        await session.execute(
            select(func.min(Term.term_no)).where(Term.academic_year_id == year.id, Term.deleted_at.is_(None))
        )
    ).scalar() == term.term_no
    lang = (await session.execute(select(SchoolSettings.default_language))).scalar() or "sw"
    items = {i.id: i for i in (await session.execute(select(FeeItem).where(FeeItem.deleted_at.is_(None)))).scalars()}
    tuition_item = next((i.id for i in items.values() if i.code == "TUITION"), None)
    term_name = term.name_sw if lang == "sw" else term.name_en

    structures, problems = {}, []
    for class_id in body.class_ids:
        structure = await _structure(session, year.id, class_id)
        if structure is None:
            code = (await session.execute(select(SchoolClass.code).where(SchoolClass.id == class_id))).scalar()
            problems.append(
                {
                    "row": 1,
                    "column": code or str(class_id),
                    "code": "no_fee_structure",
                    "message": message("no_fee_structure", principal.language),
                }
            )
        structures[class_id] = structure
    if problems:
        return [], problems

    created = []
    for class_id, structure in structures.items():
        lines = (
            (
                await session.execute(
                    select(FeeStructureLine).where(
                        FeeStructureLine.fee_structure_id == structure.id,
                        FeeStructureLine.deleted_at.is_(None),
                        FeeStructureLine.is_optional.is_(False),
                    )
                )
            )
            .scalars()
            .all()
        )
        lines = [ln for ln in lines if ln.term_id == term.id or (ln.term_id is None and first_term)]
        charges = [
            (
                ln.fee_item_id,
                f"{(items[ln.fee_item_id].name_sw if lang == 'sw' else items[ln.fee_item_id].name_en)}"
                f" - {term_name if ln.term_id else year.name}",
                ln.amount_tzs,
            )
            for ln in lines
            if ln.amount_tzs > 0
        ]
        if not charges:
            continue
        students = (
            await session.execute(
                select(Enrolment.student_id, Student.admission_no)
                .join(Stream, Stream.id == Enrolment.stream_id)
                .join(Student, Student.id == Enrolment.student_id)
                .where(
                    Stream.class_id == class_id,
                    Enrolment.academic_year_id == year.id,
                    Enrolment.status == EnrolmentStatus.ACTIVE,
                )
                .order_by(Student.admission_no)
            )
        ).all()
        billed = set(
            (
                await session.execute(
                    select(Invoice.student_id).where(
                        Invoice.term_id == term.id,
                        Invoice.cancelled_at.is_(None),
                        Invoice.student_id.in_([s for s, _ in students]),
                    )
                )
            ).scalars()
        )
        for student_id, admission_no in students:
            if student_id in billed:
                continue
            invoice = Invoice(
                school_id=principal.school_id,
                student_id=student_id,
                term_id=term.id,
                due_date=body.due_date,
                created_by=principal.user_id,
                invoice_no=await ledger.next_number(session, principal.school_id, "INVOICE", int(year.name[:4]), "INV"),
            )
            session.add(invoice)
            await session.flush()
            own = charges + await facility_fees.charges(session, student_id, term, lang)  # transport, boarding
            written = [
                InvoiceLine(
                    school_id=principal.school_id,
                    invoice_id=invoice.id,
                    fee_item_id=item,
                    kind=LineKind.CHARGE,
                    description=desc[:120],
                    amount_tzs=amount,
                    created_by=principal.user_id,
                )
                for item, desc, amount in own
            ]
            for rule, item, amount in await _discount_lines(session, student_id, year.id, own, tuition_item):
                written.append(
                    InvoiceLine(
                        school_id=principal.school_id,
                        invoice_id=invoice.id,
                        fee_item_id=item,
                        kind=LineKind.DISCOUNT,
                        discount_rule_id=rule.id,
                        amount_tzs=amount,
                        description=(rule.name_sw if lang == "sw" else rule.name_en)[:120],
                        created_by=principal.user_id,
                    )
                )
            session.add_all(written)
            await session.flush()
            await session.refresh(invoice)  # the trigger has derived the total
            await _installments(session, principal, invoice, body)
            await _invoice_journal(session, invoice, written, principal.user_id)
            await apply_credit(session, principal.school_id, student_id, principal.user_id, now())
            await session.refresh(invoice)
            created.append([invoice.invoice_no, admission_no, str(invoice.total_tzs), str(invoice.balance_tzs)])
    return created, []


async def add_charges(
    session: AsyncSession, school_id: uuid.UUID, student_id: uuid.UUID, term_id: uuid.UUID, charges: list, actor
) -> str | None:
    """Put late charges (transport, boarding) on the student's open invoice for the term: CHARGE lines, their
    journal, the last installment grows, existing credit is used. Returns the invoice number, or None when the term
    is not billed yet (generation adds them then)."""
    invoice = (
        await session.execute(
            select(Invoice)
            .where(Invoice.student_id == student_id, Invoice.term_id == term_id, Invoice.cancelled_at.is_(None))
            .with_for_update()
        )
    ).scalar_one_or_none()
    if invoice is None or not charges:
        return None
    lines = [
        InvoiceLine(
            school_id=school_id,
            invoice_id=invoice.id,
            fee_item_id=item,
            kind=LineKind.CHARGE,
            description=desc[:120],
            amount_tzs=amount,
            created_by=actor,
        )
        for item, desc, amount in charges
    ]
    session.add_all(lines)
    await session.flush()
    last = (
        await session.execute(
            select(InvoiceInstallment)
            .where(InvoiceInstallment.invoice_id == invoice.id)
            .order_by(InvoiceInstallment.seq.desc())
            .limit(1)
        )
    ).scalar_one_or_none()
    if last is not None:
        last.amount_tzs += sum((amount for _, _, amount in charges), Decimal("0"))
    await session.refresh(invoice)
    await _invoice_journal(session, invoice, lines, actor)
    await apply_credit(session, school_id, student_id, actor, now())
    return invoice.invoice_no


async def _installments(session: AsyncSession, principal: Principal, invoice: Invoice, body: GenerateInvoicesIn):
    if not body.installments or invoice.total_tzs <= 0:
        return
    remaining = invoice.total_tzs
    for seq, plan in enumerate(body.installments, start=1):
        amount = remaining if seq == len(body.installments) else _round(invoice.total_tzs * plan.percent / 100)
        remaining -= amount
        if amount > 0:
            session.add(
                InvoiceInstallment(
                    school_id=principal.school_id,
                    invoice_id=invoice.id,
                    seq=seq,
                    due_date=plan.due_date,
                    amount_tzs=amount,
                    created_by=principal.user_id,
                )
            )
    await session.flush()


def params_key(school_id: uuid.UUID, job_id: uuid.UUID) -> str:
    return f"{school_id}/invoices/{job_id}/params.json"


async def run_generation(job_id: str, school_id: str) -> str:
    """INVOICE_RUN job: all classes in one transaction; no approved structure for any class -> nothing billed."""
    job_uuid, school_uuid = uuid.UUID(job_id), uuid.UUID(school_id)
    async with school_session(school_uuid) as session:
        job = (
            await session.execute(
                select(BackgroundJob)
                .where(BackgroundJob.id == job_uuid, BackgroundJob.kind == JobKind.INVOICE_RUN)
                .with_for_update()
            )
        ).scalar_one_or_none()
        if job is None or job.status != JobStatus.QUEUED:
            return "skipped"
        job.status, job.started_at = JobStatus.RUNNING, datetime.now(UTC)
        await session.commit()
        await set_context(session, DbContext(school_id=school_uuid, user_id=job.requested_by))
        lang = (await session.execute(select(User.preferred_language).where(User.id == job.requested_by))).scalar()
        roles, permissions = await load_access(session, job.requested_by)
        principal = Principal(
            user_id=job.requested_by,
            school_id=school_uuid,
            language=lang,
            must_change_password=False,
            roles=roles,
            permissions=permissions,
        )
        body = GenerateInvoicesIn.model_validate(json.loads(get_storage().get(params_key(school_uuid, job.id))))
        try:
            created, problems = await generate(session, principal, body)
        except AppError as exc:
            await session.rollback()
            job = (await session.execute(select(BackgroundJob).where(BackgroundJob.id == job_uuid))).scalar_one()
            return await imports.fail_job(
                session,
                job,
                [{"row": 1, "column": "", "code": exc.error_code, "message": message(exc.error_code, lang)}],
            )
        if problems:
            return await imports.fail_job(session, job, problems)
        key = f"{school_uuid}/invoices/{job.id}/result.xlsx"
        get_storage().put(key, imports.result_file(["invoice_no", "admission_no", "total_tzs", "balance_tzs"], created))
        job.result_file_key, job.total_items, job.processed_items = key, len(created), len(created)
        imports.finish_job(job, JobStatus.SUCCEEDED)
        await session.commit()
    return "succeeded"


# ---------------------------------------------------------------- reads


def _list_columns():
    open_bill = (
        select(GepgBill.control_number)
        .where(GepgBill.invoice_id == Invoice.id, GepgBill.status.in_([GepgStatus.ISSUED, GepgStatus.PAID]))
        .order_by(GepgBill.requested_at.desc())
        .limit(1)
        .scalar_subquery()
    )
    return (
        select(
            Invoice.id,
            Invoice.invoice_no,
            Invoice.student_id,
            Student.admission_no,
            User.first_name,
            User.last_name,
            Invoice.term_id,
            Invoice.due_date,
            Invoice.total_tzs,
            Invoice.paid_tzs,
            Invoice.balance_tzs,
            Invoice.status,
            open_bill.label("control_number"),
            Invoice.issued_at,
        )
        .join(Student, Student.id == Invoice.student_id)
        .join(User, User.id == Student.user_id)
    )


def list_item(r) -> InvoiceListItem:
    return InvoiceListItem(
        id=r.id,
        invoice_no=r.invoice_no,
        student_id=r.student_id,
        admission_no=r.admission_no,
        student_name=f"{r.first_name} {r.last_name}",
        term_id=r.term_id,
        due_date=r.due_date,
        total_tzs=r.total_tzs,
        paid_tzs=r.paid_tzs,
        balance_tzs=r.balance_tzs,
        status=r.status,
        control_number=r.control_number,
    )


def list_query(
    status: str | None, class_id: uuid.UUID | None, term_id: uuid.UUID | None, due_before, student_id: uuid.UUID | None
):
    stmt = _list_columns()
    if status:
        stmt = stmt.where(Invoice.status == status)
    if term_id:
        stmt = stmt.where(Invoice.term_id == term_id)
    if due_before:
        stmt = stmt.where(Invoice.due_date < due_before)
    if student_id:
        stmt = stmt.where(Invoice.student_id == student_id)
    if class_id:
        stmt = stmt.where(
            select(Enrolment.id)
            .join(Stream, Stream.id == Enrolment.stream_id)
            .join(Term, and_(Term.id == Invoice.term_id, Term.academic_year_id == Enrolment.academic_year_id))
            .where(Enrolment.student_id == Invoice.student_id, Stream.class_id == class_id)
            .exists()
        )
    return stmt


async def detail(session: AsyncSession, principal: Principal, invoice_id: uuid.UUID) -> InvoiceOut:
    row = (
        await session.execute(
            _list_columns().add_columns(Invoice.cancelled_at, Invoice.cancel_reason).where(Invoice.id == invoice_id)
        )
    ).first()
    if row is None or not await may_see_student(session, principal, row.student_id):
        raise not_found()
    lines = (
        (
            await session.execute(
                select(InvoiceLine)
                .where(InvoiceLine.invoice_id == invoice_id, InvoiceLine.deleted_at.is_(None))
                .order_by(InvoiceLine.created_at)
            )
        )
        .scalars()
        .all()
    )
    installments = (
        await session.execute(
            text(
                "SELECT seq, due_date, amount_tzs, covered_tzs, status FROM v_installment_status WHERE invoice_id = :i "
                "ORDER BY seq"
            ).bindparams(i=invoice_id)
        )
    ).all()
    allocations = (
        await session.execute(
            select(
                PaymentAllocation.payment_id,
                PaymentAllocation.amount_tzs,
                Payment.channel,
                Payment.external_ref,
                Payment.received_at,
                Payment.status,
            )
            .join(Payment, Payment.id == PaymentAllocation.payment_id)
            .where(PaymentAllocation.invoice_id == invoice_id)
            .order_by(Payment.received_at)
        )
    ).all()
    base = list_item(row).model_dump()
    return InvoiceOut(
        **base,
        issued_at=row.issued_at,
        cancelled_at=row.cancelled_at,
        cancel_reason=row.cancel_reason,
        lines=[InvoiceLineOut.model_validate(ln) for ln in lines],
        installments=[InstallmentOut(**i._mapping) for i in installments],
        allocations=[AllocationOut(**a._mapping) for a in allocations],
    )


async def cancel(session: AsyncSession, principal: Principal, invoice_id: uuid.UUID, reason: str) -> InvoiceOut:
    invoice = (
        await session.execute(select(Invoice).where(Invoice.id == invoice_id).with_for_update())
    ).scalar_one_or_none()
    if invoice is None:
        raise not_found()
    if invoice.cancelled_at is not None:
        raise AppError(409, "NOT_ALLOWED", [{"field": "status", "code": "invalid_value"}])
    invoice.cancelled_at, invoice.cancel_reason = now(), reason
    await session.flush()  # the trigger refuses when payments are allocated
    lines = (
        (
            await session.execute(
                select(InvoiceLine).where(InvoiceLine.invoice_id == invoice.id, InvoiceLine.deleted_at.is_(None))
            )
        )
        .scalars()
        .all()
    )
    await _invoice_journal(session, invoice, list(lines), principal.user_id, reverse=True)
    await session.execute(
        GepgBill.__table__.update()
        .where(GepgBill.invoice_id == invoice.id, GepgBill.status.in_([GepgStatus.REQUESTED, GepgStatus.ISSUED]))
        .values(status=GepgStatus.CANCELLED)
    )
    await session.commit()
    return await detail(session, principal, invoice.id)


async def payment_out(session: AsyncSession, payment: Payment) -> PaymentOut:
    allocated = (
        await session.execute(
            select(func.coalesce(func.sum(PaymentAllocation.amount_tzs), 0)).where(
                PaymentAllocation.payment_id == payment.id
            )
        )
    ).scalar()
    receipt = (await session.execute(select(Receipt).where(Receipt.payment_id == payment.id))).scalar_one_or_none()
    return PaymentOut(
        id=payment.id,
        student_id=payment.student_id,
        channel=payment.channel,
        external_ref=payment.external_ref,
        amount_tzs=payment.amount_tzs,
        payer_name=payment.payer_name,
        status=payment.status,
        received_at=payment.received_at,
        confirmed_at=payment.confirmed_at,
        allocated_tzs=allocated,
        receipt=ReceiptOut(receipt_no=receipt.receipt_no, issued_at=receipt.issued_at) if receipt else None,
    )


async def statement(session: AsyncSession, principal: Principal, student_id: uuid.UUID) -> StatementOut:
    if not await may_see_student(session, principal, student_id):
        raise not_found()
    student = (
        await session.execute(
            select(Student.admission_no, User.first_name, User.middle_name, User.last_name)
            .join(User, User.id == Student.user_id)
            .where(Student.id == student_id)
        )
    ).first()
    if student is None:
        raise not_found()
    position = (
        await session.execute(
            text("SELECT outstanding_tzs, credit_tzs FROM v_student_fee_position WHERE student_id = :s").bindparams(
                s=student_id
            )
        )
    ).one()
    invoices = (await session.execute(list_query(None, None, None, None, student_id).order_by(Invoice.issued_at))).all()
    payments = (
        (await session.execute(select(Payment).where(Payment.student_id == student_id).order_by(Payment.received_at)))
        .scalars()
        .all()
    )
    return StatementOut(
        student_id=student_id,
        admission_no=student.admission_no,
        full_name=" ".join(p for p in (student.first_name, student.middle_name, student.last_name) if p),
        outstanding_tzs=position.outstanding_tzs,
        credit_tzs=position.credit_tzs,
        invoices=[list_item(r) for r in invoices],
        payments=[await payment_out(session, p) for p in payments],
    )


async def pdf(session: AsyncSession, principal: Principal, invoice_id: uuid.UUID, lang: str) -> tuple[str, bytes]:
    """O-03: lines, discounts, total, paid, balance, installments, control number and how to pay (VERIFY wording)."""
    inv = await detail(session, principal, invoice_id)
    school = (await session.execute(select(School.name))).scalar_one()
    sw = lang == "sw"
    out = io.BytesIO()
    c = canvas.Canvas(out, pagesize=A4, pageCompression=1)
    width, height = A4
    y = height - 20 * mm
    c.setFont("Helvetica-Bold", 13)
    c.drawCentredString(width / 2, y, school.upper())
    y -= 8 * mm
    c.setFont("Helvetica-Bold", 11)
    c.drawCentredString(width / 2, y, f"{'ANKARA' if sw else 'INVOICE'} {inv.invoice_no}")
    y -= 10 * mm
    c.setFont("Helvetica", 9.5)
    c.drawString(18 * mm, y, f"{'Mwanafunzi' if sw else 'Student'}: {inv.student_name} ({inv.admission_no})")
    c.drawRightString(width - 18 * mm, y, f"{'Mwisho' if sw else 'Due'}: {inv.due_date:%d/%m/%Y}")
    y -= 9 * mm
    for line in inv.lines:
        sign = "-" if line.kind == "DISCOUNT" else ""
        c.drawString(18 * mm, y, line.description)
        c.drawRightString(width - 18 * mm, y, f"{sign}{ledger.tzs(line.amount_tzs)}")
        y -= 5.5 * mm
    c.line(18 * mm, y + 2 * mm, width - 18 * mm, y + 2 * mm)
    c.setFont("Helvetica-Bold", 9.5)
    for label, amount in (
        (("Jumla", "Total"), inv.total_tzs),
        (("Imelipwa", "Paid"), inv.paid_tzs),
        (("Salio", "Balance"), inv.balance_tzs),
    ):
        y -= 5.5 * mm
        c.drawString(120 * mm, y, label[0] if sw else label[1])
        c.drawRightString(width - 18 * mm, y, f"TZS {ledger.tzs(amount)}")
    c.setFont("Helvetica", 9)
    for inst in inv.installments:
        y -= 5.5 * mm
        c.drawString(
            18 * mm,
            y,
            f"{'Awamu' if sw else 'Installment'} {inst.seq}: {inst.due_date:%d/%m/%Y} · "
            f"TZS {ledger.tzs(inst.amount_tzs)} · {inst.status}",
        )
    y -= 10 * mm
    c.setFont("Helvetica-Bold", 10)
    if inv.control_number:
        c.drawString(18 * mm, y, f"{'Namba ya malipo (GePG)' if sw else 'Control number (GePG)'}: {inv.control_number}")
        y -= 6 * mm
        c.setFont("Helvetica", 8.5)
        c.drawString(
            18 * mm,
            y,
            "Lipa kwa M-Pesa, Mixx by Yas, Airtel Money, HaloPesa au benki kwa namba hii (VERIFY)."
            if sw
            else "Pay with M-Pesa, Mixx by Yas, Airtel Money, HaloPesa or at a bank using this number (VERIFY).",
        )
    c.showPage()
    c.save()
    return inv.invoice_no, out.getvalue()
