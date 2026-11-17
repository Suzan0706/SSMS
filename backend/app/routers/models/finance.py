"""Fee structures, invoices and the append-only transaction ledger."""
from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import (BigInteger, Column, Date, DateTime, ForeignKey, ForeignKeyConstraint, Identity, Integer,
                        Numeric, String, Table, func, text)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db import Base
from app.models.enums import (FeeItem, PaymentMethod, TransactionSource, TransactionStatus, TransactionType)

Money = Numeric(14, 2)


class FeeStructure(Base):
    __tablename__ = "fee_structures"

    fee_structure_id: Mapped[int] = mapped_column(BigInteger, Identity(always=True), primary_key=True)
    term_id: Mapped[int] = mapped_column(ForeignKey("terms.term_id"))
    level_id: Mapped[int] = mapped_column(ForeignKey("class_levels.level_id"))
    course_id: Mapped[int | None] = mapped_column(ForeignKey("courses.course_id"))
    fee_item: Mapped[FeeItem]
    description: Mapped[str] = mapped_column(String(120))
    amount_tzs: Mapped[Decimal] = mapped_column(Money)
    is_mandatory: Mapped[bool] = mapped_column(server_default=text("true"))


class Invoice(Base):
    __tablename__ = "invoices"

    invoice_id: Mapped[int] = mapped_column(BigInteger, Identity(always=True), primary_key=True)
    invoice_no: Mapped[str] = mapped_column(String(20))
    student_id: Mapped[int] = mapped_column(ForeignKey("students.student_id"))
    term_id: Mapped[int] = mapped_column(ForeignKey("terms.term_id"))
    gepg_control_no: Mapped[str | None] = mapped_column(String(12))
    issued_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    due_date: Mapped[date]
    issued_by: Mapped[int | None] = mapped_column(ForeignKey("users.user_id"))
    cancelled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    cancel_reason: Mapped[str | None] = mapped_column(String(300))

    items: Mapped[list[InvoiceItem]] = relationship(cascade="all, delete-orphan", lazy="selectin")


class InvoiceItem(Base):
    __tablename__ = "invoice_items"

    invoice_item_id: Mapped[int] = mapped_column(BigInteger, Identity(always=True), primary_key=True)
    invoice_id: Mapped[int] = mapped_column(ForeignKey("invoices.invoice_id"))
    fee_structure_id: Mapped[int | None] = mapped_column(ForeignKey("fee_structures.fee_structure_id"))
    description: Mapped[str] = mapped_column(String(120))
    amount_tzs: Mapped[Decimal] = mapped_column(Money)


class Transaction(Base):
    """Never updated or deleted (DB trigger). Corrections are REVERSAL rows."""

    __tablename__ = "transactions"
    # The invoice must belong to the same student (composite FK, as in db/schema.sql).
    __table_args__ = (
        ForeignKeyConstraint(["invoice_id", "student_id"], ["invoices.invoice_id", "invoices.student_id"],
                             name="fk_transactions_invoice"),
    )

    trans_id: Mapped[int] = mapped_column(BigInteger, Identity(always=True), primary_key=True)
    trans_no: Mapped[str] = mapped_column(String(20))
    trans_type: Mapped[TransactionType]
    trans_name: Mapped[str] = mapped_column(String(120))
    student_id: Mapped[int] = mapped_column(ForeignKey("students.student_id"))
    invoice_id: Mapped[int | None] = mapped_column(BigInteger)
    amount_tzs: Mapped[Decimal] = mapped_column(Money)
    payment_method: Mapped[PaymentMethod | None]
    reference_no: Mapped[str | None] = mapped_column(String(50))
    payer_name: Mapped[str | None] = mapped_column(String(100))
    payer_phone: Mapped[str | None] = mapped_column(String(12))
    status: Mapped[TransactionStatus] = mapped_column(server_default=TransactionStatus.PENDING.value)
    source: Mapped[TransactionSource] = mapped_column(server_default=TransactionSource.MANUAL.value)
    reverses_trans_id: Mapped[int | None] = mapped_column(ForeignKey("transactions.trans_id"))
    trans_date: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    recorded_by: Mapped[int | None] = mapped_column(ForeignKey("users.user_id"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


# Read-only view: total, paid, balance and payment status per invoice.
invoice_balances = Table(
    "v_invoice_balances",
    Base.metadata,
    Column("invoice_id", BigInteger, primary_key=True),
    Column("invoice_no", String),
    Column("student_id", BigInteger),
    Column("term_id", Integer),
    Column("gepg_control_no", String),
    Column("due_date", Date),
    Column("total_tzs", Money),
    Column("paid_tzs", Money),
    Column("balance_tzs", Money),
    Column("payment_status", String),
    info={"is_view": True},
)
