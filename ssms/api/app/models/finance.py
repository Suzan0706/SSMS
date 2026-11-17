"""Finance: fee structures, discounts, invoices, GePG bills, payments, allocations, reversals, receipts, double-entry
ledger, bank deposits and reconciliation (design/sql/schema.sql §9). Invoice totals, paid amount and status are
derived by the database trigger trg_invoices_derive; the application never writes them."""

import uuid
from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import CHAR, Computed, DateTime, LargeBinary, Numeric, SmallInteger, String, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, SoftDeleteMixin, TenantMixin
from app.models.enums import (
    Channel,
    DepositStatus,
    DiscountKind,
    FeeStructureStatus,
    GepgStatus,
    InvoiceStatus,
    JournalSource,
    LineKind,
    MatchStatus,
    PaymentStatus,
    RequestStatus,
    RunStatus,
)

Money = Numeric(14, 2)


class FeeStructure(TenantMixin, SoftDeleteMixin, Base):
    __tablename__ = "fee_structures"
    academic_year_id: Mapped[uuid.UUID]
    class_id: Mapped[uuid.UUID]
    name: Mapped[str] = mapped_column(String(80))
    status: Mapped[FeeStructureStatus] = mapped_column(default=FeeStructureStatus.DRAFT)
    approved_by: Mapped[uuid.UUID | None]
    approved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class FeeStructureLine(TenantMixin, SoftDeleteMixin, Base):
    __tablename__ = "fee_structure_lines"
    fee_structure_id: Mapped[uuid.UUID]
    fee_item_id: Mapped[uuid.UUID]
    term_id: Mapped[uuid.UUID | None]
    amount_tzs: Mapped[Decimal] = mapped_column(Money)
    is_optional: Mapped[bool] = mapped_column(default=False)


class DiscountRule(TenantMixin, SoftDeleteMixin, Base):
    __tablename__ = "discount_rules"
    code: Mapped[str] = mapped_column(String(20))
    name_en: Mapped[str] = mapped_column(String(80))
    name_sw: Mapped[str] = mapped_column(String(80))
    kind: Mapped[DiscountKind]
    percent: Mapped[Decimal | None] = mapped_column(Numeric(5, 2))
    amount_tzs: Mapped[Decimal | None] = mapped_column(Money)


class StudentDiscount(TenantMixin, SoftDeleteMixin, Base):
    __tablename__ = "student_discounts"
    student_id: Mapped[uuid.UUID]
    discount_rule_id: Mapped[uuid.UUID]
    academic_year_id: Mapped[uuid.UUID]
    reason: Mapped[str] = mapped_column(String(200))
    approved_by: Mapped[uuid.UUID]
    approved_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=text("now()"))


class Invoice(TenantMixin, Base):
    __tablename__ = "invoices"
    invoice_no: Mapped[str] = mapped_column(String(20))
    student_id: Mapped[uuid.UUID]
    term_id: Mapped[uuid.UUID]
    issued_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=text("now()"))
    due_date: Mapped[date]
    total_tzs: Mapped[Decimal] = mapped_column(Money, server_default=text("0"))  # trigger-derived
    paid_tzs: Mapped[Decimal] = mapped_column(Money, server_default=text("0"))  # trigger-derived
    balance_tzs: Mapped[Decimal | None] = mapped_column(Money, Computed("total_tzs - paid_tzs"))  # generated column
    status: Mapped[InvoiceStatus] = mapped_column(server_default=text("'UNPAID'"))  # trigger-derived
    cancelled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    cancel_reason: Mapped[str | None] = mapped_column(String(300))


class InvoiceLine(TenantMixin, SoftDeleteMixin, Base):
    __tablename__ = "invoice_lines"
    invoice_id: Mapped[uuid.UUID]
    fee_item_id: Mapped[uuid.UUID]
    kind: Mapped[LineKind] = mapped_column(default=LineKind.CHARGE)
    description: Mapped[str] = mapped_column(String(120))
    amount_tzs: Mapped[Decimal] = mapped_column(Money)
    discount_rule_id: Mapped[uuid.UUID | None]


class InvoiceInstallment(TenantMixin, Base):
    __tablename__ = "invoice_installments"
    invoice_id: Mapped[uuid.UUID]
    seq: Mapped[int] = mapped_column(SmallInteger)
    due_date: Mapped[date]
    amount_tzs: Mapped[Decimal] = mapped_column(Money)


class GepgBill(TenantMixin, Base):
    __tablename__ = "gepg_bills"
    invoice_id: Mapped[uuid.UUID]
    bill_ref: Mapped[str] = mapped_column(String(40))
    control_number: Mapped[str | None] = mapped_column(String(12))
    amount_tzs: Mapped[Decimal] = mapped_column(Money)
    status: Mapped[GepgStatus] = mapped_column(default=GepgStatus.REQUESTED)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    request_payload: Mapped[dict] = mapped_column(JSONB)
    response_payload: Mapped[dict | None] = mapped_column(JSONB)
    signature_verified: Mapped[bool] = mapped_column(default=False)
    requested_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=text("now()"))
    issued_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class Payment(TenantMixin, Base):
    __tablename__ = "payments"  # money fields immutable after insert (trigger)
    student_id: Mapped[uuid.UUID]
    channel: Mapped[Channel]
    external_ref: Mapped[str] = mapped_column(String(60))
    amount_tzs: Mapped[Decimal] = mapped_column(Money)
    payer_name: Mapped[str | None] = mapped_column(String(100))
    payer_phone_hash: Mapped[bytes | None] = mapped_column(LargeBinary)
    payer_phone_last4: Mapped[str | None] = mapped_column(CHAR(4))
    gepg_bill_id: Mapped[uuid.UUID | None]
    status: Mapped[PaymentStatus] = mapped_column(default=PaymentStatus.PENDING)
    received_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    confirmed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    recorded_by: Mapped[uuid.UUID | None]
    raw_payload: Mapped[dict | None] = mapped_column(JSONB)


class PaymentAllocation(TenantMixin, Base):
    __tablename__ = "payment_allocations"  # append-only
    payment_id: Mapped[uuid.UUID]
    invoice_id: Mapped[uuid.UUID]
    amount_tzs: Mapped[Decimal] = mapped_column(Money)


class PaymentReversal(TenantMixin, Base):
    __tablename__ = "payment_reversals"  # append-only; insert sets the payment REVERSED
    payment_id: Mapped[uuid.UUID]
    reason: Mapped[str] = mapped_column(String(300))
    reversed_by: Mapped[uuid.UUID]
    approved_by: Mapped[uuid.UUID]


class PaymentReversalRequest(TenantMixin, Base):
    __tablename__ = "payment_reversal_requests"
    payment_id: Mapped[uuid.UUID]
    reason: Mapped[str] = mapped_column(String(300))
    requested_by: Mapped[uuid.UUID]
    status: Mapped[RequestStatus] = mapped_column(default=RequestStatus.PENDING)
    decided_by: Mapped[uuid.UUID | None]
    decided_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    decision_note: Mapped[str | None] = mapped_column(String(300))
    reversal_id: Mapped[uuid.UUID | None]


class Receipt(TenantMixin, Base):
    __tablename__ = "receipts"  # only pdf_file_key and sms_sent_at may change
    receipt_no: Mapped[str] = mapped_column(String(20))
    payment_id: Mapped[uuid.UUID]
    issued_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=text("now()"))
    pdf_file_key: Mapped[str | None] = mapped_column(String(255))
    sms_sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class Journal(TenantMixin, Base):
    __tablename__ = "journals"  # append-only; balanced at COMMIT (deferred trigger)
    journal_no: Mapped[str] = mapped_column(String(20))
    posted_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=text("now()"))
    source_type: Mapped[JournalSource]
    source_id: Mapped[uuid.UUID]
    memo: Mapped[str] = mapped_column(String(200))
    posted_by: Mapped[uuid.UUID | None]


class LedgerEntry(TenantMixin, Base):
    __tablename__ = "ledger_entries"
    journal_id: Mapped[uuid.UUID]
    account_id: Mapped[uuid.UUID]
    student_id: Mapped[uuid.UUID | None]
    debit_tzs: Mapped[Decimal] = mapped_column(Money, default=Decimal("0"))
    credit_tzs: Mapped[Decimal] = mapped_column(Money, default=Decimal("0"))


class BankDeposit(TenantMixin, Base):
    __tablename__ = "bank_deposit_confirmations"
    bank_reference: Mapped[str] = mapped_column(String(60))
    deposit_date: Mapped[date]
    amount_tzs: Mapped[Decimal] = mapped_column(Money)
    student_id: Mapped[uuid.UUID | None]
    depositor_name: Mapped[str | None] = mapped_column(String(100))
    status: Mapped[DepositStatus] = mapped_column(default=DepositStatus.SUBMITTED)
    submitted_by: Mapped[uuid.UUID]
    confirmed_by: Mapped[uuid.UUID | None]
    confirmed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    payment_id: Mapped[uuid.UUID | None]
    note: Mapped[str | None] = mapped_column(String(300))


class ReconciliationRun(TenantMixin, Base):
    __tablename__ = "reconciliation_runs"
    run_date: Mapped[date]
    channel: Mapped[Channel]
    statement_file_key: Mapped[str | None] = mapped_column(String(255))
    statement_total_tzs: Mapped[Decimal] = mapped_column(Money, default=Decimal("0"))
    system_total_tzs: Mapped[Decimal] = mapped_column(Money, default=Decimal("0"))
    status: Mapped[RunStatus] = mapped_column(default=RunStatus.RUNNING)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class ReconciliationItem(TenantMixin, Base):
    __tablename__ = "reconciliation_items"
    run_id: Mapped[uuid.UUID]
    external_ref: Mapped[str] = mapped_column(String(60))
    statement_amount_tzs: Mapped[Decimal | None] = mapped_column(Money)
    payment_id: Mapped[uuid.UUID | None]
    status: Mapped[MatchStatus]
    resolved_by: Mapped[uuid.UUID | None]
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    note: Mapped[str | None] = mapped_column(String(300))


class FinanceCategory(TenantMixin, SoftDeleteMixin, Base):
    """A kind of other income or expense, posted to one ledger account."""

    __tablename__ = "finance_categories"
    kind: Mapped[str] = mapped_column(String(7))
    name_en: Mapped[str] = mapped_column(String(80))
    name_sw: Mapped[str] = mapped_column(String(80))
    ledger_account_id: Mapped[uuid.UUID]


class CashEntry(TenantMixin, Base):
    """Other income or an expense. Posted entries never change (trigger); a reversal needs a second person."""

    __tablename__ = "cash_entries"
    entry_no: Mapped[str] = mapped_column(String(20))
    category_id: Mapped[uuid.UUID]
    entry_date: Mapped[date]
    amount_tzs: Mapped[Decimal] = mapped_column(Numeric(14, 2))
    method: Mapped[str] = mapped_column(String(12))
    reference: Mapped[str | None] = mapped_column(String(60))
    party: Mapped[str | None] = mapped_column(String(120))
    description: Mapped[str] = mapped_column(String(300))
    attachment_file_id: Mapped[uuid.UUID | None]
    journal_id: Mapped[uuid.UUID]
    status: Mapped[str] = mapped_column(String(8), default="POSTED")
    reversal_requested_by: Mapped[uuid.UUID | None]
    reversal_approved_by: Mapped[uuid.UUID | None]
    reversal_reason: Mapped[str | None] = mapped_column(String(300))
    reversal_journal_id: Mapped[uuid.UUID | None]


class FineRule(TenantMixin, Base):
    __tablename__ = "fine_rules"
    kind: Mapped[str] = mapped_column(String(12))
    fee_item_id: Mapped[uuid.UUID]
    amount_tzs: Mapped[Decimal] = mapped_column(Numeric(14, 2))
    grace_days: Mapped[int] = mapped_column(SmallInteger, default=0)
    active: Mapped[bool] = mapped_column(default=True)
