from datetime import date, datetime
from decimal import Decimal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.models.enums import PaymentMethod, TransactionSource, TransactionStatus, TransactionType
from app.schemas.common import TzPhone

AmountTzs = Field(gt=0, max_digits=14, decimal_places=2)


class PaymentIn(BaseModel):
    student_id: int
    invoice_id: int | None = None
    amount_tzs: Decimal = AmountTzs
    payment_method: PaymentMethod
    reference_no: str | None = Field(default=None, max_length=50)
    payer_name: str | None = Field(default=None, max_length=100)
    payer_phone: TzPhone | None = None
    trans_date: datetime | None = None
    trans_name: str | None = Field(default=None, max_length=120)

    @model_validator(mode="after")
    def reference_unless_cash(self) -> "PaymentIn":
        if self.payment_method != PaymentMethod.CASH and not self.reference_no:
            raise ValueError("reference_no is required for non-cash payments")
        if self.payment_method == PaymentMethod.GEPG:
            raise ValueError("GePG payments are posted by the GePG callback, not manually")
        return self


class ReverseIn(BaseModel):
    reason: str = Field(min_length=5, max_length=100)


class TransactionOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    trans_id: int
    trans_no: str
    trans_type: TransactionType
    trans_name: str
    student_id: int
    invoice_id: int | None
    amount_tzs: Decimal
    payment_method: PaymentMethod | None
    reference_no: str | None
    payer_name: str | None
    payer_phone: str | None
    status: TransactionStatus
    source: TransactionSource
    reverses_trans_id: int | None
    trans_date: datetime
    recorded_by: int | None


class InvoiceBalanceOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    invoice_id: int
    invoice_no: str
    term_id: int
    gepg_control_no: str | None
    due_date: date
    total_tzs: Decimal
    paid_tzs: Decimal
    balance_tzs: Decimal
    payment_status: str


class PaymentRecorded(BaseModel):
    transaction: TransactionOut
    invoice: InvoiceBalanceOut | None


class StatementOut(BaseModel):
    student_id: int
    admission_no: str
    student_name: str
    invoices: list[InvoiceBalanceOut]
    transactions: list[TransactionOut]
    total_balance_tzs: Decimal
