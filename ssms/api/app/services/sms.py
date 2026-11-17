"""Outgoing SMS: a row in sms_messages (status QUEUED) plus a Celery job that calls the provider.

Provider HTTP details are marked VERIFY: confirm against the provider's current API documentation and the
school's account before go-live.

Every message costs its segment count in SMS credit (sms_credit_transactions, an append-only ledger): DEBIT when
queued, REFUND when the provider refuses it for good. Without enough credit a message is stored as SKIPPED
(`no_credit`) and never sent, except sign-in codes and new-account passwords, which always go out. Delivery reports
mark messages DELIVERED or FAILED.
"""

import base64
import logging
import uuid
from datetime import UTC, datetime

import httpx
from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.crypto import get_cipher
from app.db.session import DbContext, provider, set_context
from app.models import Notification, Permission, RolePermission, SmsCreditTransaction, SmsMessage, User, UserRole
from app.models.enums import CreditKind, SmsStatus, UserStatus

log = logging.getLogger(__name__)
PHONE_FIELD = "users.phone"  # associated data / blind-index domain for phone numbers
LOW_CREDIT = 100
ESSENTIAL = {"otp_login", "account_created"}  # never blocked by credit: people must be able to sign in
# GSM 03.38 basic character set: messages using only these fit 160 characters per SMS, otherwise 70 (UCS-2).
GSM7 = set(
    "@£$¥èéùìòÇ\nØø\rÅåΔ_ΦΓΛ"
    "ΩΠΨΣΘΞÆæßÉ !\"#¤%&'()*+,-./0123456789:;<=>?"
    "¡ABCDEFGHIJKLMNOPQRSTUVWXYZÄÖÑÜ§¿abcdefghijklmnopqrstuvwxyz"
    "äöñüà"
)


class TransientSmsError(Exception):
    """Provider unreachable, 429 or 5xx: the Celery task retries with backoff."""


def segments(text: str) -> int:
    single, multi = (160, 153) if set(text) <= GSM7 else (70, 67)
    return 1 if len(text) <= single else -(-len(text) // multi)


async def queue_sms(
    session: AsyncSession,
    *,
    school_id: uuid.UUID,
    phone: str,
    body: str,
    language: str,
    idempotency_key: str,
    to_user_id: uuid.UUID | None = None,
    template_key: str | None = None,
    related_entity: str | None = None,
    related_id: uuid.UUID | None = None,
) -> SmsMessage:
    """Store the message (phone encrypted). `body` is what is kept in the database; secrets such as OTP codes
    are masked there and passed to the send task instead."""
    count = segments(body)
    await session.execute(
        text("SELECT pg_advisory_xact_lock(hashtextextended('sms_credit:' || :school, 0))"), {"school": str(school_id)}
    )
    left = await credits_left(session, school_id)
    blocked = template_key not in ESSENTIAL and left < count
    sms = SmsMessage(
        school_id=school_id,
        to_user_id=to_user_id,
        to_phone_enc=get_cipher().encrypt(phone, PHONE_FIELD),
        to_phone_last4=phone[-4:],
        template_key=template_key,
        language=language,
        body=body[:480],
        segments=min(count, 3),
        provider=get_settings().sms_provider.upper(),
        status=SmsStatus.SKIPPED if blocked else SmsStatus.QUEUED,
        cost_credits=0 if blocked else count,
        error="no_credit" if blocked else None,
        idempotency_key=idempotency_key,
        related_entity=related_entity,
        related_id=related_id,
    )
    session.add(sms)
    await session.flush()
    if blocked:
        log.warning("SMS skipped: no credit (school %s)", school_id)
        return sms
    session.add(SmsCreditTransaction(school_id=school_id, kind=CreditKind.DEBIT, credits=count, sms_message_id=sms.id))
    if left >= LOW_CREDIT > left - count:
        await low_credit_notice(session, school_id, left - count)
    await session.flush()
    return sms


async def credits_left(session: AsyncSession, school_id: uuid.UUID) -> int:
    """Explicit school filter: the console role bypasses RLS."""
    query = text("SELECT coalesce(sum(credits_left), 0) FROM v_sms_credit_balance WHERE school_id = :school")
    return int((await session.execute(query, {"school": school_id})).scalar())


async def low_credit_notice(session: AsyncSession, school_id: uuid.UUID, left: int) -> None:
    """In-app notice to everybody who manages SMS when the balance drops below LOW_CREDIT."""
    managers = (
        await session.execute(
            select(User.id, User.preferred_language)
            .join(UserRole, UserRole.user_id == User.id)
            .join(RolePermission, RolePermission.role_id == UserRole.role_id)
            .join(Permission, Permission.id == RolePermission.permission_id)
            .where(Permission.code == "sms.manage", UserRole.revoked_at.is_(None), User.status == UserStatus.ACTIVE)
            .distinct()
        )
    ).all()
    for user_id, lang in managers:
        sw = lang != "en"
        session.add(
            Notification(
                school_id=school_id,
                user_id=user_id,
                kind="LOW_SMS_CREDIT",
                title="Salio la SMS linakaribia kuisha" if sw else "SMS credit is running low",
                body=f"Zimebaki SMS {left}. Ongeza salio ili ujumbe uendelee kutumwa."
                if sw
                else f"{left} SMS left. Top up so messages keep going out.",
                link="/sms",
            )
        )


class ConsoleProvider:
    """Development only (refused in production): writes the message to the log instead of sending it."""

    async def send(self, phone: str, text: str, sender: str) -> str:
        log.warning("CONSOLE SMS to ****%s from %s: %s", phone[-4:], sender, text)
        return f"console-{uuid.uuid4().hex[:12]}"


class BeemProvider:
    URL = "https://apisms.beem.africa/v1/send"  # VERIFY endpoint and payload with Beem Africa docs

    async def send(self, phone: str, text: str, sender: str) -> str:
        s = get_settings()
        payload = {
            "source_addr": sender,
            "encoding": 0,
            "message": text,
            "recipients": [{"recipient_id": 1, "dest_addr": phone}],
        }
        data = await _post(self.URL, payload, auth=(s.beem_api_key, s.beem_secret_key))
        return str(data.get("request_id", ""))


class NextSmsProvider:
    URL = "https://messaging-service.co.tz/api/sms/v1/text/single"  # VERIFY with NextSMS docs

    async def send(self, phone: str, text: str, sender: str) -> str:
        s = get_settings()
        token = base64.b64encode(f"{s.nextsms_username}:{s.nextsms_password}".encode()).decode()
        data = await _post(
            self.URL, {"from": sender, "to": phone, "text": text}, headers={"Authorization": f"Basic {token}"}
        )
        messages = data.get("messages") or [{}]
        return str(messages[0].get("messageId", ""))


async def _post(url: str, payload: dict, **kwargs) -> dict:
    try:
        async with httpx.AsyncClient(timeout=15) as client:
            response = await client.post(url, json=payload, **kwargs)
    except httpx.HTTPError as exc:
        raise TransientSmsError(type(exc).__name__) from exc
    if response.status_code >= 500 or response.status_code == 429:
        raise TransientSmsError(f"HTTP {response.status_code}")
    response.raise_for_status()
    return response.json()


PROVIDERS = {"console": ConsoleProvider, "beem": BeemProvider, "nextsms": NextSmsProvider}


def get_provider():
    return PROVIDERS[get_settings().sms_provider]()


async def deliver(session: AsyncSession, sms_id: uuid.UUID, text: str | None = None, sender: str | None = None) -> str:
    """Send one queued message. Idempotent: a message that is no longer QUEUED is not sent again."""
    sms = (
        await session.execute(select(SmsMessage).where(SmsMessage.id == sms_id).with_for_update())
    ).scalar_one_or_none()
    if sms is None or sms.status != SmsStatus.QUEUED:
        return "skipped"
    phone = get_cipher().decrypt(sms.to_phone_enc, PHONE_FIELD)
    try:
        sms.provider_message_id = await get_provider().send(
            phone, text or sms.body, sender or get_settings().sms_default_sender
        )
    except TransientSmsError:
        raise
    except Exception as exc:  # permanent failure (4xx, bad response): do not retry, give the credit back
        sms.status, sms.error = SmsStatus.FAILED, type(exc).__name__[:300]
        if sms.cost_credits:
            session.add(
                SmsCreditTransaction(
                    school_id=sms.school_id, kind=CreditKind.REFUND, credits=sms.cost_credits, note=f"refund:{sms.id}"
                )
            )
        await session.commit()
        return "failed"
    sms.status, sms.sent_at = SmsStatus.SENT, datetime.now(UTC)
    await session.commit()
    return "sent"


# ---------------------------------------------------------------- delivery reports

DELIVERED = {"DELIVERED", "DELIVRD", "SUCCESS"}
UNDELIVERED = {"FAILED", "UNDELIVERED", "UNDELIV", "UNDELIVERABLE", "REJECTED", "EXPIRED"}


def parse_reports(data) -> list[tuple[str, str]]:
    """(provider message id, upper-case status) pairs from one report, a list, or {"results": [...]} (NextSMS
    style); Beem reports carry request_id. VERIFY both formats with the providers."""
    items = data.get("results", [data]) if isinstance(data, dict) else data
    out = []
    for item in items if isinstance(items, list) else []:
        if not isinstance(item, dict):
            continue
        ref = item.get("messageId") or item.get("message_id") or item.get("request_id") or item.get("id")
        status = item.get("status") or item.get("deliveryStatus") or ""
        if isinstance(status, dict):
            status = status.get("groupName") or status.get("name") or ""
        if ref:
            out.append((str(ref)[:80], str(status).upper()))
    return out


async def apply_reports(provider_name: str, reports: list[tuple[str, str]]) -> int:
    """Mark messages DELIVERED or FAILED; unknown ids and in-between states are ignored. Returns rows changed."""
    changed = 0
    async with provider.app() as session:
        for ref, status in reports:
            new = SmsStatus.DELIVERED if status in DELIVERED else SmsStatus.FAILED if status in UNDELIVERED else None
            if new is None:
                continue
            row = (
                await session.execute(
                    select(func.resolve_sms_message(provider_name.upper(), ref).table_valued("school_id", "sms_id"))
                )
            ).first()
            if row is None:
                continue
            await set_context(session, DbContext(school_id=row.school_id))
            sms = (
                await session.execute(select(SmsMessage).where(SmsMessage.id == row.sms_id).with_for_update())
            ).scalar_one()
            if sms.status in (SmsStatus.SENT, SmsStatus.QUEUED):
                sms.status = new
                if new == SmsStatus.DELIVERED:
                    sms.delivered_at = datetime.now(UTC)
                else:
                    sms.error = f"provider:{status}"[:300]
                changed += 1
            await session.commit()
    return changed
