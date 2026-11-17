import logging
from datetime import timedelta

from sqlalchemy import select

from app.core.config import get_settings
from app.core.i18n import tzs
from app.db import SessionLocal
from app.integrations import gepg
from app.models import Invoice, Student, invoice_balances
from app.services.common import now_eat
from app.services.notify import sms_guardians
from app.tasks.celery_app import celery_app

log = logging.getLogger(__name__)


@celery_app.task
def request_control_number(invoice_id: int) -> str | None:
    """Submit the bill to GePG. The control number arrives later through the GePG bill callback."""
    if not get_settings().gepg_enabled:
        log.info("GePG disabled: no control number requested for invoice %s", invoice_id)
        return None
    with SessionLocal() as db:
        row = db.execute(select(invoice_balances).where(invoice_balances.c.invoice_id == invoice_id)).mappings().one()
        student = db.get(Student, row["student_id"])
        return gepg.request_control_number(row["invoice_no"], row["balance_tzs"], student.user.full_name,
                                           student.user.phone, row["due_date"].isoformat())


@celery_app.task
def send_fee_reminders(days_before_due: int = 7) -> int:
    """Celery beat, weekdays 08:00 EAT: SMS guardians of unpaid invoices due within a week."""
    today = now_eat().date()
    sent = 0
    with SessionLocal() as db:
        rows = db.execute(select(invoice_balances).where(
            invoice_balances.c.payment_status.in_(("UNPAID", "PARTIALLY_PAID")),
            invoice_balances.c.due_date.between(today, today + timedelta(days=days_before_due)),
        )).mappings().all()
        for row in rows:
            invoice = db.get(Invoice, row["invoice_id"])
            student = db.get(Student, invoice.student_id)
            sent += sms_guardians(db, student, "fee_reminder", primary_only=True,
                                  balance=tzs(row["balance_tzs"]), due=row["due_date"].strftime("%d/%m/%Y"),
                                  control_no=row["gepg_control_no"] or "-")
    return sent
