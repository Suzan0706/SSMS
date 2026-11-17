"""GePG (Government Electronic Payment Gateway) adapter.

Element names follow the GePG Service Provider integration pattern (gepgPmtSpInfo / PymtTrxInf).
Check them against the specification version issued to the school with its SP code and
certificates; only this module changes if they differ.
"""
import base64
import logging
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from functools import lru_cache

from cryptography import x509
from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import padding

from app.core.config import get_settings
from app.services.common import EAT

log = logging.getLogger(__name__)

ACK_SUCCESS = "7101"


class SignatureError(Exception):
    pass


@dataclass
class PaymentNotification:
    control_no: str
    receipt_no: str
    amount_tzs: Decimal
    paid_at: datetime
    payer_name: str | None
    payer_phone: str | None
    channel: str | None


@lru_cache
def _gepg_public_key():
    with open(get_settings().gepg_public_cert_path, "rb") as fh:
        return x509.load_pem_x509_certificate(fh.read()).public_key()


def verify_signature(signed_xml: bytes, signature_b64: str) -> None:
    try:
        _gepg_public_key().verify(base64.b64decode(signature_b64), signed_xml,
                                  padding.PKCS1v15(), hashes.SHA256())
    except (InvalidSignature, ValueError) as exc:
        raise SignatureError("GePG signature check failed") from exc


def _text(node: ET.Element, tag: str) -> str | None:
    found = node.find(tag)
    return found.text.strip() if found is not None and found.text else None


def _normalise_phone(raw: str | None) -> str | None:
    digits = "".join(ch for ch in raw or "" if ch.isdigit())
    if len(digits) == 10 and digits.startswith("0"):
        digits = "255" + digits[1:]
    return digits if len(digits) == 12 and digits.startswith("255") else None


def _signed_part(body: bytes) -> bytes:
    """The exact bytes GePG signed: the <gepgPmtSpInfo> element as received (no re-serialising)."""
    start, end_tag = body.find(b"<gepgPmtSpInfo>"), b"</gepgPmtSpInfo>"
    end = body.find(end_tag)
    if start < 0 or end < 0:
        raise SignatureError("Malformed GePG message")
    return body[start:end + len(end_tag)]


def _paid_at(raw: str | None) -> datetime:
    if not raw:
        return datetime.now(EAT)
    value = datetime.fromisoformat(raw)
    return value if value.tzinfo else value.replace(tzinfo=EAT)   # GePG times are East Africa Time


def parse_payment_notification(body: bytes) -> PaymentNotification:
    """Verify the signature over <gepgPmtSpInfo> and return the payment details."""
    root = ET.fromstring(body)          # expat in Python >= 3.7.1 refuses external entities
    signature = _text(root, "gepgSignature")
    if signature is None:
        raise SignatureError("Missing gepgSignature")
    verify_signature(_signed_part(body), signature)
    trx = root.find("gepgPmtSpInfo/PymtTrxInf")
    if trx is None:
        raise SignatureError("Missing PymtTrxInf")
    return PaymentNotification(
        control_no=_text(trx, "PayCtrNum") or "",
        receipt_no=_text(trx, "PspReceiptNumber") or _text(trx, "TrxId") or "",
        amount_tzs=Decimal(_text(trx, "PaidAmt") or "0"),
        paid_at=_paid_at(_text(trx, "TrxDtTm")),
        payer_name=_text(trx, "PyrName"),
        payer_phone=_normalise_phone(_text(trx, "PyrCellNum")),
        channel=_text(trx, "UsdPayChnl"),
    )


def acknowledgement(status_code: str = ACK_SUCCESS) -> str:
    # In production the acknowledgement is signed with the school's private key as well.
    return f"<Gepg><gepgPmtSpInfoAck><TrxStsCode>{status_code}</TrxStsCode></gepgPmtSpInfoAck></Gepg>"


def request_control_number(invoice_no: str, amount_tzs: Decimal, payer_name: str, payer_phone: str | None,
                           due_date: str) -> str | None:
    """Submit a bill. Returns None here; GePG answers asynchronously with the control number."""
    settings = get_settings()
    if not settings.gepg_enabled:
        log.info("GePG disabled: bill %s for TZS %s not sent", invoice_no, amount_tzs)
        return None
    raise NotImplementedError("Build and sign the gepgBillSubReq message per the issued GePG specification")
