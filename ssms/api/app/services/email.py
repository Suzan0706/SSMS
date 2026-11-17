"""Email channel (FR-98), beside SMS. Behind a provider adapter like SMS (ADR 0009): console (development, writes to the
log) or SMTP. A message is queued only for a user who has an email address; others keep getting SMS only.
Sending is a task (email.send) and is idempotent: a message is sent once and its status recorded.
"""

import asyncio
import logging
import smtplib
import ssl
import uuid
from email.message import EmailMessage as MimeMessage
from email.utils import formatdate, make_msgid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.models import EmailMessage, School, User
from app.services.people import now

log = logging.getLogger(__name__)


class ConsoleProvider:
    name = "CONSOLE"

    def send(self, to: str, subject: str, body: str, sender: str) -> str:
        log.info("EMAIL to %s… subject=%r (%d characters)", to[:3], subject, len(body))
        return f"console-{uuid.uuid4().hex[:12]}"


class SmtpProvider:
    """SMTP with TLS whose certificate is verified: implicit TLS (port 465 or SSMS_SMTP_IMPLICIT_TLS), otherwise
    STARTTLS. A password is never sent over a connection without TLS."""

    name = "SMTP"

    def send(self, to: str, subject: str, body: str, sender: str) -> str:
        s = get_settings()
        message = MimeMessage()
        message["From"], message["To"], message["Subject"] = sender, to, subject
        message["Date"] = formatdate(localtime=True)
        message["Message-ID"] = make_msgid(domain=s.email_from.rpartition("@")[2] or None)
        message.set_content(body)
        context = ssl.create_default_context(cafile=s.smtp_ca_file or None)  # verifies the server's certificate
        implicit = s.smtp_implicit_tls or s.smtp_port == 465
        if implicit:
            client = smtplib.SMTP_SSL(s.smtp_host, s.smtp_port, timeout=20, context=context)
        else:
            client = smtplib.SMTP(s.smtp_host, s.smtp_port, timeout=20)
        with client:
            encrypted = implicit
            if not encrypted and s.smtp_starttls:
                client.starttls(context=context)
                encrypted = True
            if s.smtp_user:
                if not encrypted:
                    raise smtplib.SMTPException("refusing to send the SMTP password without TLS")
                client.login(s.smtp_user, s.smtp_password)
            client.send_message(message)
        return message["Message-ID"]


def get_provider():
    return SmtpProvider() if get_settings().email_provider == "smtp" else ConsoleProvider()


async def queue_email(
    session: AsyncSession,
    *,
    school_id: uuid.UUID,
    user_id: uuid.UUID,
    subject: str,
    body: str,
    idempotency_key: str,
    template_key: str | None = None,
    related_entity: str | None = None,
    related_id: uuid.UUID | None = None,
) -> EmailMessage | None:
    """Store a message for a user with an email address (None when they have none, it was queued before, or email
    is not set up)."""
    if not get_settings().email_enabled:
        return None
    user = (await session.execute(select(User.email, User.preferred_language).where(User.id == user_id))).one_or_none()
    if user is None or not user.email:
        return None
    if (await session.execute(select(EmailMessage.id).where(EmailMessage.idempotency_key == idempotency_key))).first():
        return None
    item = EmailMessage(
        school_id=school_id,
        to_user_id=user_id,
        template_key=template_key,
        language=user.preferred_language,
        subject=subject[:200],
        body=body,
        provider=get_provider().name,
        idempotency_key=idempotency_key,
        related_entity=related_entity,
        related_id=related_id,
    )
    session.add(item)
    await session.flush()
    return item


async def deliver(session: AsyncSession, email_id: uuid.UUID) -> str:
    item = await session.get(EmailMessage, email_id, with_for_update=True)
    if item is None or item.status != "QUEUED":
        return "skipped"
    to = (await session.execute(select(User.email).where(User.id == item.to_user_id))).scalar()
    if not to:
        item.status, item.error = "SKIPPED", "no_address"
        await session.commit()
        return "skipped"
    school = (await session.execute(select(School.name))).scalar_one()
    sender = f"{school[:60]} <{get_settings().email_from}>"
    try:
        item.provider_message_id = await asyncio.to_thread(get_provider().send, to, item.subject, item.body, sender)
        item.status, item.sent_at = "SENT", now()
    except (OSError, smtplib.SMTPException) as exc:
        item.status, item.error = "FAILED", f"{type(exc).__name__}: {exc}"[:300]
        log.warning("email %s failed: %s", item.id, item.error)
    await session.commit()
    return item.status


async def history(session: AsyncSession, limit: int = 100) -> list[dict]:
    rows = (
        await session.execute(
            select(EmailMessage, User.first_name, User.last_name)
            .join(User, User.id == EmailMessage.to_user_id)
            .order_by(EmailMessage.queued_at.desc())
            .limit(limit)
        )
    ).all()
    return [
        {
            "id": m.id,
            "to": f"{first} {last}",
            "subject": m.subject,
            "status": m.status,
            "error": m.error,
            "queued_at": m.queued_at,
            "sent_at": m.sent_at,
            "related_entity": m.related_entity,
        }
        for m, first, last in rows
    ]
