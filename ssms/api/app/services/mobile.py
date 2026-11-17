"""Mobile money (M-Pesa, Mixx by Yas / Tigo Pesa, Airtel Money, HaloPesa) through an aggregator.

Callback format (VERIFY with the chosen aggregator, design V6): JSON
    {"transaction_id", "reference", "amount", "msisdn", "payer_name", "timestamp"}
signed with header  X-SSMS-Signature: sha256=<hex HMAC-SHA256(secret, raw body)>.
The reference is either a 12-digit GePG control number or "<school code>.<admission no>" (e.g. mfano-sec.MF-2025-0014).
"""

import hashlib
import hmac
import json
import logging
import re
import uuid
from datetime import datetime
from decimal import Decimal, InvalidOperation

from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert

from app.api.deps import Principal
from app.core.config import get_settings
from app.core.errors import AppError, not_found
from app.core.ids import uuid7
from app.core.phone import normalise_phone
from app.core.ratelimit import enforce
from app.db.session import DbContext, provider, set_context
from app.models import GepgBill, Invoice, Payment, School, Student
from app.models.enums import Channel, GepgStatus, PaymentStatus
from app.services.gepg import EAT
from app.services.invoices import may_see_student
from app.services.payments import phone_fields
from app.services.people import now
from app.tasks.dispatch import get_dispatcher

log = logging.getLogger(__name__)
CHANNELS = {
    "mpesa": Channel.MPESA,
    "tigopesa": Channel.TIGOPESA,
    "airtel": Channel.AIRTEL,
    "halopesa": Channel.HALOPESA,
}


def signature_ok(body: bytes, header: str | None) -> bool:
    secret = get_settings().mobile_webhook_secret
    if not secret or not header or not header.startswith("sha256="):
        return False
    expected = hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected, header.removeprefix("sha256="))


async def _route(session, reference: str) -> tuple[uuid.UUID, uuid.UUID, uuid.UUID | None] | None:
    """(school_id, student_id, gepg bill id or None)."""
    if re.fullmatch(r"\d{12}", reference):
        row = (
            await session.execute(select(func.resolve_gepg_bill(reference, None).table_valued("school_id", "bill_id")))
        ).first()
        if row is None:
            return None
        await set_context(session, DbContext(school_id=row.school_id))
        student_id = (
            await session.execute(
                select(Invoice.student_id)
                .join(GepgBill, GepgBill.invoice_id == Invoice.id)
                .where(GepgBill.id == row.bill_id)
            )
        ).scalar()
        return row.school_id, student_id, row.bill_id
    code, _, admission = reference.partition(".")
    school_id = (await session.execute(select(func.resolve_school_by_code(code)))).scalar() if admission else None
    if school_id is None:
        return None
    await set_context(session, DbContext(school_id=school_id))
    student_id = (
        await session.execute(
            select(Student.id).where(
                func.upper(Student.admission_no) == admission.upper(), Student.deleted_at.is_(None)
            )
        )
    ).scalar()
    return (school_id, student_id, None) if student_id else None


async def callback(channel_key: str, body: bytes) -> dict:
    """Record one mobile-money payment. Answers ACCEPTED, DUPLICATE or REJECTED (with a reason)."""
    data = json.loads(body)
    try:
        amount = Decimal(str(data["amount"]))
        transaction_id, reference = str(data["transaction_id"])[:60], str(data["reference"]).strip()
    except (KeyError, InvalidOperation, TypeError):
        return {"status": "REJECTED", "reason": "malformed"}
    if amount <= 0:
        return {"status": "REJECTED", "reason": "amount"}
    async with provider.app() as session:
        routed = await _route(session, reference)
        if routed is None:
            log.warning("mobile money payment with unknown reference")
            return {"status": "REJECTED", "reason": "unknown_reference"}
        school_id, student_id, bill_id = routed
        try:
            received = datetime.fromisoformat(str(data.get("timestamp")))
            received = received if received.tzinfo else received.replace(tzinfo=EAT)
        except ValueError:
            received = now()
        try:
            extra = phone_fields(str(data.get("msisdn") or ""))
        except ValueError:
            extra = {}
        payment_id = (
            await session.execute(
                insert(Payment)
                .values(
                    id=uuid7(),
                    school_id=school_id,
                    student_id=student_id,
                    channel=CHANNELS[channel_key],
                    external_ref=transaction_id,
                    amount_tzs=amount,
                    payer_name=(str(data.get("payer_name") or ""))[:100] or None,
                    gepg_bill_id=bill_id,
                    status=PaymentStatus.CONFIRMED,
                    received_at=received,
                    confirmed_at=now(),
                    raw_payload={
                        "reference": reference,
                        "channel": channel_key,
                        "msisdn_last4": extra.get("payer_phone_last4"),
                    },
                    **extra,
                )
                .on_conflict_do_nothing(constraint="uq_payments_external_ref")
                .returning(Payment.id)
            )
        ).scalar()
        await session.commit()
    if payment_id is None:
        return {"status": "DUPLICATE"}
    get_dispatcher().send("payments.process", payment_id=str(payment_id), school_id=str(school_id))
    return {"status": "ACCEPTED", "payment_id": str(payment_id)}


class ConsolePush:
    """Development only: logs the payment prompt instead of sending it to the phone."""

    async def send(self, channel: Channel, phone: str, amount: Decimal, reference: str) -> str:
        log.warning("PUSH %s to ****%s TZS %s ref %s", channel, phone[-4:], amount, reference)
        return f"push-{uuid.uuid4().hex[:10]}"


PUSH_PROVIDERS = {"console": ConsolePush}


async def push(session, principal: Principal, invoice_id: uuid.UUID, phone_raw: str, channel: Channel) -> dict:
    """Ask the payer's phone to approve a payment (USSD push). The money still arrives by callback."""
    if channel not in CHANNELS.values():
        raise AppError(422, "VALIDATION_ERROR", [{"field": "channel", "code": "invalid_value"}])
    invoice = (await session.execute(select(Invoice).where(Invoice.id == invoice_id))).scalar_one_or_none()
    if invoice is None or not await may_see_student(session, principal, invoice.student_id):
        raise not_found()
    if invoice.cancelled_at is not None or invoice.balance_tzs <= 0:
        raise AppError(409, "NOT_ALLOWED", [{"field": "invoice", "code": "invalid_value"}])
    try:
        phone = normalise_phone(phone_raw)
    except ValueError:
        raise AppError(422, "VALIDATION_ERROR", [{"field": "phone", "code": "invalid_phone"}]) from None
    await enforce(f"push:{phone}", 3, 900)
    control = (
        await session.execute(
            select(GepgBill.control_number).where(
                GepgBill.invoice_id == invoice.id, GepgBill.status == GepgStatus.ISSUED
            )
        )
    ).scalar()
    if control:
        reference = control
    else:
        code = (await session.execute(select(School.code))).scalar_one()
        admission = (
            await session.execute(select(Student.admission_no).where(Student.id == invoice.student_id))
        ).scalar()
        reference = f"{code}.{admission}"
    request_id = await PUSH_PROVIDERS[get_settings().push_provider]().send(
        channel, phone, invoice.balance_tzs, reference
    )
    return {"status": "SENT", "reference": reference, "request_id": request_id}
