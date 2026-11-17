"""GePG (Government e-Payment Gateway): control-number requests, signed callbacks, acknowledgements.

Message layout follows the GePG SP integration documents as understood at design time; element names, the
signature algorithm (RSA PKCS#1 v1.5 with SHA-256 here) and acknowledgement codes are VERIFY items (design V4).
The signature covers the exact bytes of the inner element, e.g. <gepgBillSubResp>…</gepgBillSubResp>.

Modes: `simulator` answers a bill request at once with a test control number (development and tests);
`live` posts the signed request to SSMS_GEPG_URL and waits for GePG's callback.
"""

import base64
import hashlib
import logging
import re
import uuid
import xml.etree.ElementTree as ET
from datetime import UTC, datetime, time, timedelta, timezone
from decimal import Decimal, InvalidOperation

import httpx
from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding
from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import Principal
from app.core.config import get_settings
from app.core.errors import AppError, not_found
from app.core.ids import uuid7
from app.db.session import DbContext, provider, set_context
from app.models import FeeItem, GepgBill, Invoice, InvoiceLine, Payment, School, SchoolSettings, Student, User
from app.models.enums import Channel, GepgStatus, LineKind, PaymentStatus
from app.services import ledger, sms
from app.services.payments import _primary_guardian, phone_fields, template_text
from app.services.people import decrypt_phone, now
from app.tasks.dispatch import get_dispatcher

log = logging.getLogger(__name__)
ACK_OK = "7101"  # VERIFY: GePG "received successfully" code
MAX_BODY = 64 * 1024
EAT = timezone(timedelta(hours=3), "EAT")


class SignatureError(Exception):
    pass


class GatewayUnavailable(Exception):
    """GePG unreachable or 5xx: the Celery task retries with backoff."""


# ---------------------------------------------------------------- signing and XML


def _private_key():
    return serialization.load_pem_private_key(get_settings().gepg_private_key.encode(), password=None)


def _public_key():
    data = get_settings().gepg_public_key.encode()
    if b"CERTIFICATE" in data:
        from cryptography import x509

        return x509.load_pem_x509_certificate(data).public_key()
    return serialization.load_pem_public_key(data)


def sign(data: bytes) -> str:
    if not get_settings().gepg_private_key:
        return ""  # simulator without keys: unsigned
    return base64.b64encode(_private_key().sign(data, padding.PKCS1v15(), hashes.SHA256())).decode()


def verify(data: bytes, signature: str) -> None:
    if not get_settings().gepg_public_key:
        raise SignatureError("no GePG public key configured")
    try:
        _public_key().verify(base64.b64decode(signature), data, padding.PKCS1v15(), hashes.SHA256())
    except (InvalidSignature, ValueError) as exc:
        raise SignatureError("bad signature") from exc


def _element(tag: str, fields: dict) -> ET.Element:
    el = ET.Element(tag)
    for key, value in fields.items():
        if isinstance(value, dict):
            el.append(_element(key, value))
        elif isinstance(value, list):
            for item in value:
                el.append(_element(key, item))
        else:
            ET.SubElement(el, key).text = "" if value is None else str(value)
    return el


def envelope(inner_tag: str, fields: dict, sign_with=sign) -> bytes:
    inner = ET.tostring(_element(inner_tag, fields), encoding="unicode").encode()
    return b"<Gepg>" + inner + b"<gepgSignature>" + sign_with(inner).encode() + b"</gepgSignature></Gepg>"


def parse(body: bytes, inner_tag: str) -> dict:
    """Verify and flatten a GePG message. Refuses DOCTYPE/ENTITY declarations (no entity expansion)."""
    if len(body) > MAX_BODY or b"<!DOCTYPE" in body.upper() or b"<!ENTITY" in body.upper():
        raise SignatureError("message refused")
    inner = re.search(rb"<" + inner_tag.encode() + rb">.*</" + inner_tag.encode() + rb">", body, re.S)
    signature = re.search(rb"<gepgSignature>(.*?)</gepgSignature>", body, re.S)
    if not inner or not signature:
        raise SignatureError("malformed message")
    verify(inner.group(0), signature.group(1).decode().strip())
    fields: dict[str, str] = {}
    for el in ET.fromstring(inner.group(0)).iter():
        if len(el) == 0 and el.text is not None:
            fields[el.tag] = el.text.strip()
    return fields


def ack(inner_tag: str) -> bytes:
    return envelope(inner_tag, {"TrxStsCode": ACK_OK})


# ---------------------------------------------------------------- bill request


async def request_bill(session: AsyncSession, principal: Principal, invoice_id: uuid.UUID) -> GepgBill:
    invoice = (
        await session.execute(select(Invoice).where(Invoice.id == invoice_id).with_for_update())
    ).scalar_one_or_none()
    if invoice is None:
        raise not_found()
    if invoice.cancelled_at is not None or invoice.balance_tzs <= 0:
        raise AppError(409, "NOT_ALLOWED", [{"field": "invoice", "code": "invalid_value"}])
    school = (await session.execute(select(School.code, School.name))).one()
    settings_row = (await session.execute(select(SchoolSettings.gepg_sp_code, SchoolSettings.gepg_sub_sp_code))).first()
    attempt = (await session.execute(select(func.count()).where(GepgBill.invoice_id == invoice.id))).scalar() + 1
    student = (
        await session.execute(
            select(Student.admission_no, User.first_name, User.last_name)
            .join(User, User.id == Student.user_id)
            .where(Student.id == invoice.student_id)
        )
    ).one()
    items = (
        await session.execute(
            select(InvoiceLine.amount_tzs, InvoiceLine.kind, FeeItem.gfs_code, FeeItem.code)
            .join(FeeItem, FeeItem.id == InvoiceLine.fee_item_id)
            .where(InvoiceLine.invoice_id == invoice.id, InvoiceLine.deleted_at.is_(None))
        )
    ).all()
    expires = datetime.combine(
        max(invoice.due_date, (now() + timedelta(days=get_settings().gepg_bill_days)).date()), time(23, 59), UTC
    )
    bill_ref = f"{school.code}-{invoice.invoice_no}-{attempt}"[:40]
    payload = {
        "BillHdr": {"SpCode": settings_row.gepg_sp_code if settings_row else None, "RtrRespFlg": "true"},
        "BillTrxInf": {
            "BillId": bill_ref,
            "SubSpCode": settings_row.gepg_sub_sp_code if settings_row else None,
            "SpSysId": "SSMS",
            "BillAmt": str(invoice.balance_tzs),
            "MiscBillAmt": "0",
            "Ccy": "TZS",
            "BillExprDt": expires.strftime("%Y-%m-%dT%H:%M:%S"),
            "PyrId": student.admission_no,
            "PyrName": f"{student.first_name} {student.last_name}",
            "BillDesc": f"{school.name[:60]} {invoice.invoice_no}",
            "BillGenDt": now().strftime("%Y-%m-%dT%H:%M:%S"),
            "BillGenBy": "SSMS",
            "BillApprBy": "SSMS",
            "BillPayOpt": "3",
            "RemFlag": "true",  # VERIFY: partial payments allowed
            "BillItems": {
                "BillItem": [
                    {"BillItemRef": code, "BillItemAmt": str(amount), "GfsCode": gfs}
                    for amount, kind, gfs, code in items
                    if kind == LineKind.CHARGE
                ]
            },
        },
    }
    bill = GepgBill(
        school_id=principal.school_id,
        invoice_id=invoice.id,
        bill_ref=bill_ref,
        amount_tzs=invoice.balance_tzs,
        status=GepgStatus.REQUESTED,
        expires_at=expires,
        request_payload=payload,
        created_by=principal.user_id,
    )
    session.add(bill)
    try:
        await session.flush()
    except Exception as exc:  # uq_gepg_bills_open
        if getattr(getattr(exc, "orig", None), "sqlstate", None) == "23505":
            raise AppError(409, "DUPLICATE", [{"field": "invoice", "code": "open_bill"}]) from None
        raise
    await session.commit()
    return bill


def simulated_control_number(bill_ref: str) -> str:
    return "99" + str(int(hashlib.sha256(bill_ref.encode()).hexdigest(), 16))[:10]


async def submit(bill_id: str, school_id: str) -> str:
    """Celery entry point: send the signed request (live) or answer it at once (simulator)."""
    async with provider.app() as session:
        await set_context(session, DbContext(school_id=uuid.UUID(school_id)))
        bill = (await session.execute(select(GepgBill).where(GepgBill.id == uuid.UUID(bill_id)))).scalar_one()
        if bill.status != GepgStatus.REQUESTED:
            return "skipped"
        body = envelope("gepgBillSubReq", bill.request_payload)
    if get_settings().gepg_mode == "simulator":
        return await bill_response(
            {
                "BillId": bill.bill_ref,
                "TrxSts": "GS",
                "TrxStsCode": ACK_OK,
                "PayCntrNum": simulated_control_number(bill.bill_ref),
            }
        )
    async with httpx.AsyncClient(timeout=20) as client:
        response = await client.post(
            get_settings().gepg_url,
            content=body,
            headers={"Content-Type": "application/xml", "Gepg-Com": "default.sp.in"},
        )
    if response.status_code >= 500:
        raise GatewayUnavailable(f"GePG HTTP {response.status_code}")
    return "sent"


# ---------------------------------------------------------------- callbacks (signature already verified)


async def _route(
    session: AsyncSession, control_number: str | None, bill_ref: str | None
) -> tuple[uuid.UUID, uuid.UUID] | None:
    row = (
        await session.execute(
            select(func.resolve_gepg_bill(control_number, bill_ref).table_valued("school_id", "bill_id"))
        )
    ).first()
    return (row.school_id, row.bill_id) if row else None


async def bill_response(fields: dict) -> str:
    """Control number issued (or refused) for a bill we requested. Idempotent."""
    calls = []
    async with provider.app() as session:
        routed = await _route(session, None, fields.get("BillId"))
        if routed is None:
            log.warning("GePG bill response for unknown bill")
            return "unknown"
        school_id, bill_id = routed
        await set_context(session, DbContext(school_id=school_id))
        bill = (await session.execute(select(GepgBill).where(GepgBill.id == bill_id).with_for_update())).scalar_one()
        if bill.status != GepgStatus.REQUESTED:
            return "duplicate"
        bill.response_payload = fields
        if fields.get("TrxSts") == "GS" and re.fullmatch(r"\d{12}", fields.get("PayCntrNum", "")):
            bill.control_number, bill.status = fields["PayCntrNum"], GepgStatus.ISSUED
            bill.signature_verified, bill.issued_at = True, now()
            call = await _invoice_sms(session, bill)
            if call:
                calls.append(call)
        else:
            bill.status = GepgStatus.FAILED
        await session.commit()
    for call in calls:
        get_dispatcher().send("sms.send", **call)
    return "issued" if fields.get("TrxSts") == "GS" else "failed"


async def _invoice_sms(session: AsyncSession, bill: GepgBill) -> dict | None:
    invoice = (await session.execute(select(Invoice).where(Invoice.id == bill.invoice_id))).scalar_one()
    guardian = await _primary_guardian(session, invoice.student_id)
    phone = decrypt_phone(guardian) if guardian else None
    if not phone:
        return None
    school = (await session.execute(select(School.name))).scalar_one()
    body = (await template_text(session, "invoice_issued", guardian.preferred_language)).format(
        school=school[:40],
        invoice_no=invoice.invoice_no,
        amount=ledger.tzs(bill.amount_tzs),
        control_no=bill.control_number,
        due=f"{invoice.due_date:%d/%m/%Y}",
    )
    message = await sms.queue_sms(
        session,
        school_id=bill.school_id,
        phone=phone,
        body=body,
        language=guardian.preferred_language,
        to_user_id=guardian.id,
        template_key="invoice_issued",
        idempotency_key=f"bill:{bill.id.hex}",
        related_entity="gepg_bills",
        related_id=bill.id,
    )
    return {"sms_id": str(message.id), "school_id": str(bill.school_id)}


def _money(value: str | None) -> Decimal | None:
    try:
        amount = Decimal(value or "")
    except InvalidOperation:
        return None
    return amount if amount > 0 else None


def _when(value: str | None) -> datetime:
    try:
        moment = datetime.fromisoformat(value or "")
    except ValueError:
        return now()
    return moment if moment.tzinfo else moment.replace(tzinfo=EAT)  # GePG times are local (VERIFY)


async def payment_notification(fields: dict) -> str:
    """A payment against a control number. Inserted once per PayRefId (ON CONFLICT DO NOTHING), then processed."""
    async with provider.app() as session:
        routed = await _route(session, fields.get("PayCtrNum"), fields.get("BillId"))
        amount = _money(fields.get("PaidAmt"))
        if routed is None or amount is None or not fields.get("PayRefId"):
            log.warning("GePG payment that cannot be routed (kept for reconciliation by GePG)")
            return "unknown"
        school_id, bill_id = routed
        await set_context(session, DbContext(school_id=school_id))
        bill = (await session.execute(select(GepgBill).where(GepgBill.id == bill_id))).scalar_one()
        student_id = (await session.execute(select(Invoice.student_id).where(Invoice.id == bill.invoice_id))).scalar()
        phone = fields.get("PyrCellNum")
        redacted = {k: v for k, v in fields.items() if k not in ("PyrCellNum", "PyrEmail")}
        redacted["amount_matches_bill"] = amount == bill.amount_tzs
        try:
            extra = phone_fields(phone)
        except ValueError:
            extra = {}
        payment_id = (
            await session.execute(
                insert(Payment)
                .values(
                    id=uuid7(),
                    school_id=school_id,
                    student_id=student_id,
                    channel=Channel.GEPG,
                    external_ref=fields["PayRefId"][:60],
                    amount_tzs=amount,
                    payer_name=(fields.get("PyrName") or "")[:100] or None,
                    gepg_bill_id=bill.id,
                    status=PaymentStatus.CONFIRMED,
                    received_at=_when(fields.get("TrxDtTm")),
                    confirmed_at=now(),
                    raw_payload=redacted,
                    **extra,
                )
                .on_conflict_do_nothing(constraint="uq_payments_external_ref")
                .returning(Payment.id)
            )
        ).scalar()
        await session.commit()
    if payment_id is None:
        return "duplicate"
    get_dispatcher().send("payments.process", payment_id=str(payment_id), school_id=str(school_id))
    return "accepted"
