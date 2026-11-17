"""Finance requests and responses. Money is TZS as a decimal string with two places ("680000.00")."""

import uuid
from datetime import date, datetime
from decimal import Decimal
from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field, PlainSerializer, model_validator

from app.models.enums import Channel, DiscountKind

Tzs = Annotated[Decimal, Field(ge=0, max_digits=14, decimal_places=2)]
PositiveTzs = Annotated[Decimal, Field(gt=0, max_digits=14, decimal_places=2)]
# Every amount leaves the API as a string with exactly two decimals ("0.00", "680000.00").
MoneyOut = Annotated[Decimal, PlainSerializer(lambda v: f"{v:.2f}", return_type=str, when_used="json")]
FEE_ITEM_CODES = r"^(TUITION|BOARDING|TRANSPORT|MEALS|UNIFORM|EXAMINATION|DEVELOPMENT|OTHER)$"


class _Out(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID


# ---------------------------------------------------------------- fee setup


class LedgerAccountOut(_Out):
    code: str
    name_en: str
    name_sw: str
    kind: str


class FeeItemIn(BaseModel):
    code: str = Field(pattern=FEE_ITEM_CODES)
    name_en: str = Field(min_length=2, max_length=80)
    name_sw: str = Field(min_length=2, max_length=80)
    gfs_code: str | None = Field(default=None, max_length=20, description="GePG revenue (GFS) code — VERIFY")
    income_account_id: uuid.UUID


class FeeItemUpdate(BaseModel):
    name_en: str | None = Field(default=None, min_length=2, max_length=80)
    name_sw: str | None = Field(default=None, min_length=2, max_length=80)
    gfs_code: str | None = Field(default=None, max_length=20)
    income_account_id: uuid.UUID | None = None


class FeeItemOut(_Out):
    code: str
    name_en: str
    name_sw: str
    gfs_code: str | None
    income_account_id: uuid.UUID


class StructureLineIn(BaseModel):
    fee_item_id: uuid.UUID
    term_id: uuid.UUID | None = Field(default=None, description="Empty = billed once a year, on the first term")
    amount_tzs: Tzs
    is_optional: bool = False


class StructureLineOut(StructureLineIn):
    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID


class FeeStructureIn(BaseModel):
    academic_year_id: uuid.UUID
    class_id: uuid.UUID
    name: str = Field(min_length=2, max_length=80)
    lines: list[StructureLineIn] = Field(min_length=1, max_length=60)


class FeeStructureUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=2, max_length=80)
    lines: list[StructureLineIn] | None = Field(default=None, min_length=1, max_length=60)


class FeeStructureOut(_Out):
    academic_year_id: uuid.UUID
    class_id: uuid.UUID
    name: str
    status: str
    approved_by: uuid.UUID | None
    approved_at: datetime | None
    lines: list[StructureLineOut]
    totals: dict[str, MoneyOut] = Field(description="term id (or 'yearly') -> compulsory total")


class DiscountRuleIn(BaseModel):
    code: str = Field(pattern=r"^[A-Z0-9_]{2,20}$")
    name_en: str = Field(min_length=2, max_length=80)
    name_sw: str = Field(min_length=2, max_length=80)
    kind: DiscountKind
    percent: MoneyOut | None = Field(
        default=None, gt=0, le=100, max_digits=5, decimal_places=2, description="Percent of the tuition charges"
    )
    amount_tzs: PositiveTzs | None = Field(default=None, description="Fixed amount off each invoice")

    @model_validator(mode="after")
    def _one_value(self):
        if (self.percent is None) == (self.amount_tzs is None):
            raise ValueError("invalid_value")  # exactly one of percent / amount
        return self


class DiscountRuleOut(_Out):
    code: str
    name_en: str
    name_sw: str
    kind: str
    percent: MoneyOut | None
    amount_tzs: MoneyOut | None


class StudentDiscountIn(BaseModel):
    discount_rule_id: uuid.UUID
    academic_year_id: uuid.UUID
    reason: str = Field(min_length=3, max_length=200)


class StudentDiscountOut(_Out):
    student_id: uuid.UUID
    discount_rule_id: uuid.UUID
    academic_year_id: uuid.UUID
    reason: str
    approved_by: uuid.UUID
    approved_at: datetime


# ---------------------------------------------------------------- invoices


class InstallmentPlan(BaseModel):
    due_date: date
    percent: MoneyOut = Field(gt=0, le=100, max_digits=5, decimal_places=2)


class GenerateInvoicesIn(BaseModel):
    term_id: uuid.UUID
    class_ids: list[uuid.UUID] = Field(min_length=1, max_length=40)
    due_date: date
    installments: list[InstallmentPlan] = Field(default_factory=list, max_length=12)

    @model_validator(mode="after")
    def _plan(self):
        if self.installments and sum(i.percent for i in self.installments) != 100:
            raise ValueError("invalid_value")  # installments must cover the whole invoice
        return self


class InvoiceLineOut(_Out):
    fee_item_id: uuid.UUID
    kind: str
    description: str
    amount_tzs: MoneyOut


class InstallmentOut(BaseModel):
    seq: int
    due_date: date
    amount_tzs: MoneyOut
    covered_tzs: MoneyOut
    status: str


class AllocationOut(BaseModel):
    payment_id: uuid.UUID
    amount_tzs: MoneyOut
    channel: str
    external_ref: str
    received_at: datetime
    status: str


class InvoiceListItem(BaseModel):
    id: uuid.UUID
    invoice_no: str
    student_id: uuid.UUID
    admission_no: str
    student_name: str
    term_id: uuid.UUID
    due_date: date
    total_tzs: MoneyOut
    paid_tzs: MoneyOut
    balance_tzs: MoneyOut
    status: str
    control_number: str | None


class InvoiceOut(InvoiceListItem):
    issued_at: datetime
    cancelled_at: datetime | None
    cancel_reason: str | None
    lines: list[InvoiceLineOut]
    installments: list[InstallmentOut]
    allocations: list[AllocationOut]


class CancelIn(BaseModel):
    reason: str = Field(min_length=5, max_length=300)


class StatementOut(BaseModel):
    student_id: uuid.UUID
    admission_no: str
    full_name: str
    outstanding_tzs: MoneyOut
    credit_tzs: MoneyOut
    invoices: list[InvoiceListItem]
    payments: list["PaymentOut"]


# ---------------------------------------------------------------- payments


class PaymentIn(BaseModel):
    """Cash at the office or a bank deposit the bursar has seen (other channels arrive by callback)."""

    student_id: uuid.UUID
    channel: Channel = Field(description="CASH or BANK")
    external_ref: str = Field(min_length=3, max_length=60, description="Receipt-book number or bank reference")
    amount_tzs: PositiveTzs
    payer_name: str | None = Field(default=None, max_length=100)
    payer_phone: str | None = Field(default=None, description="07XXXXXXXX")
    received_at: datetime

    @model_validator(mode="after")
    def _manual(self):
        if self.channel not in (Channel.CASH, Channel.BANK):
            raise ValueError("invalid_value")
        return self


class ReceiptOut(BaseModel):
    receipt_no: str
    issued_at: datetime


class PaymentOut(BaseModel):
    id: uuid.UUID
    student_id: uuid.UUID
    channel: str
    external_ref: str
    amount_tzs: MoneyOut
    payer_name: str | None
    status: str
    received_at: datetime
    confirmed_at: datetime | None
    allocated_tzs: MoneyOut
    receipt: ReceiptOut | None


class ReversalRequestIn(BaseModel):
    reason: str = Field(min_length=5, max_length=300)


class ReversalRequestOut(BaseModel):
    id: uuid.UUID
    payment_id: uuid.UUID
    external_ref: str
    amount_tzs: MoneyOut
    student_name: str
    reason: str
    status: str
    requested_by: uuid.UUID
    requested_by_name: str
    decided_by: uuid.UUID | None
    decided_at: datetime | None
    decision_note: str | None


class DecisionNoteIn(BaseModel):
    note: str | None = Field(default=None, max_length=300)


class BankDepositIn(BaseModel):
    bank_reference: str = Field(min_length=3, max_length=60)
    deposit_date: date
    amount_tzs: PositiveTzs
    student_id: uuid.UUID
    depositor_name: str | None = Field(default=None, max_length=100)


class BankDepositOut(_Out):
    bank_reference: str
    deposit_date: date
    amount_tzs: MoneyOut
    student_id: uuid.UUID | None
    depositor_name: str | None
    status: str
    submitted_by: uuid.UUID
    confirmed_by: uuid.UUID | None
    confirmed_at: datetime | None
    payment_id: uuid.UUID | None
    note: str | None


class PushIn(BaseModel):
    invoice_id: uuid.UUID
    phone: str
    channel: Channel = Field(description="MPESA, TIGOPESA, AIRTEL or HALOPESA")


# ---------------------------------------------------------------- reconciliation and reports


class ReconciliationItemOut(_Out):
    external_ref: str
    statement_amount_tzs: MoneyOut | None
    payment_id: uuid.UUID | None
    status: str
    resolved_by: uuid.UUID | None
    resolved_at: datetime | None
    note: str | None


class ReconciliationRunOut(_Out):
    run_date: date
    channel: str
    statement_total_tzs: MoneyOut
    system_total_tzs: MoneyOut
    matched_count: int = Field(default=0, description="Counted from the run's items, not stored")
    exception_count: int = Field(default=0, description="Counted from the run's items, not stored")
    status: str
    completed_at: datetime | None
    items: list[ReconciliationItemOut] = []


class ResolveIn(BaseModel):
    note: str = Field(min_length=3, max_length=300)
    payment_id: uuid.UUID | None = None


StatementOut.model_rebuild()
