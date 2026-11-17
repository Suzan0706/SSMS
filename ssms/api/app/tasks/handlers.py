"""Async task handlers. Celery wraps each one (app/tasks/worker.py); tests call them directly.

Every handler is idempotent: running it twice with the same arguments has the same effect as running it once.
"""

import uuid

from sqlalchemy import select

from app.db.session import school_session
from app.models import SchoolSettings
from app.services import (
    alerts,
    communication,
    compliance,
    email,
    fee_reports,
    gepg,
    imports,
    invoices,
    marks,
    payments,
    promotions,
    report_cards,
    reports,
    sms,
    student_life,
)


async def sms_send(sms_id: str, school_id: str, text: str | None = None) -> str:
    async with school_session(uuid.UUID(school_id)) as session:
        sender = (
            await session.execute(
                select(SchoolSettings.sms_sender_id).where(SchoolSettings.school_id == uuid.UUID(school_id))
            )
        ).scalar()
        return await sms.deliver(session, uuid.UUID(sms_id), text, sender)


async def email_send(email_id: str, school_id: str) -> str:
    async with school_session(uuid.UUID(school_id)) as session:
        return await email.deliver(session, uuid.UUID(email_id))


HANDLERS = {
    "sms.send": sms_send,
    "email.send": email_send,
    "imports.run": imports.run_job,
    "promotions.run": promotions.run_job,
    "marks.upload": marks.run_upload,
    "report_cards.run": report_cards.run_job,
    "invoices.generate": invoices.run_generation,
    "payments.process": payments.run_processing,
    "gepg.submit": gepg.submit,
    "reminders.run": fee_reports.run_reminders,
    "reminders.fanout": fee_reports.fanout,
    "absence.run": alerts.run,
    "absence.fanout": alerts.fanout,
    "announcements.sms": communication.run_sms,
    "library.remind": student_life.run_reminders,
    "library.fanout": student_life.fanout,
    "reports.export": reports.run_export,
    "compliance.export": compliance.run,
}
