"""Fee reports (aging, defaulters, collections) and overdue reminders.

Reminders: one SMS per overdue installment (or per overdue invoice without installments) and guardian, ever —
the idempotency key makes a second run send nothing new. A daily Celery beat job fans out over active schools.
"""

import io
import uuid
from datetime import date
from decimal import Decimal

from openpyxl import Workbook
from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import DbContext, provider, school_session, set_context
from app.models import GepgBill, Invoice, School, SmsMessage, Student, User
from app.models.enums import GepgStatus
from app.services import ledger, sms
from app.services.payments import _primary_guardian, template_text
from app.services.people import decrypt_phone
from app.tasks.dispatch import get_dispatcher

BUCKETS = ["NOT_DUE", "1-30", "31-60", "61-90", "90+"]


async def aging(session: AsyncSession, limit: int = 200) -> dict:
    summary = {b: {"count": 0, "balance_tzs": Decimal("0")} for b in BUCKETS}
    for bucket, count, total in (
        await session.execute(
            text("SELECT aging_bucket, count(*), sum(balance_tzs) FROM v_invoice_aging GROUP BY aging_bucket")
        )
    ).all():
        summary[bucket] = {"count": count, "balance_tzs": total}
    rows = (
        (
            await session.execute(
                text(
                    "SELECT a.invoice_no, st.admission_no, u.first_name || ' ' || u.last_name AS student, a.due_date, "
                    "a.balance_tzs, a.aging_bucket FROM v_invoice_aging a JOIN students st ON st.id = a.student_id "
                    "JOIN users u ON u.id = st.user_id ORDER BY a.balance_tzs DESC, a.invoice_no LIMIT :limit"
                ).bindparams(limit=limit)
            )
        )
        .mappings()
        .all()
    )
    return {"summary": summary, "rows": [dict(r) for r in rows]}


async def defaulters(
    session: AsyncSession, class_id: uuid.UUID | None, min_balance: Decimal, limit: int = 200
) -> list[dict]:
    rows = (
        (
            await session.execute(
                text(
                    "SELECT p.student_id, st.admission_no, u.first_name || ' ' || u.last_name AS student, "
                    "c.code AS class_code, "
                    "s.name AS stream, p.outstanding_tzs, p.credit_tzs "
                    "FROM v_student_fee_position p JOIN students st ON st.id = p.student_id "
                    "JOIN users u ON u.id = st.user_id "
                    "LEFT JOIN enrolments e ON e.student_id = st.id AND e.status = 'ACTIVE' "
                    "LEFT JOIN streams s ON s.id = e.stream_id LEFT JOIN classes c ON c.id = s.class_id "
                    "WHERE p.outstanding_tzs > :min AND (CAST(:class AS uuid) IS NULL OR c.id = CAST(:class AS uuid)) "
                    "ORDER BY p.outstanding_tzs DESC, st.admission_no LIMIT :limit"
                ).bindparams(min=min_balance, limit=limit, **{"class": str(class_id) if class_id else None})
            )
        )
        .mappings()
        .all()
    )
    return [dict(r) for r in rows]


async def collections(session: AsyncSession, start: date, end: date) -> dict:
    rows = (
        (
            await session.execute(
                text(
                    "SELECT (received_at AT TIME ZONE 'Africa/Dar_es_Salaam')::date AS day, channel, "
                    "count(*) AS payments, "
                    "sum(amount_tzs) AS amount_tzs FROM payments WHERE status = 'CONFIRMED' "
                    "AND (received_at AT TIME ZONE 'Africa/Dar_es_Salaam')::date BETWEEN :start AND :end "
                    "GROUP BY 1, 2 ORDER BY 1, 2"
                ).bindparams(start=start, end=end)
            )
        )
        .mappings()
        .all()
    )
    by_channel: dict[str, Decimal] = {}
    for r in rows:
        by_channel[r["channel"]] = by_channel.get(r["channel"], Decimal("0")) + r["amount_tzs"]
    return {
        "from": start,
        "to": end,
        "total_tzs": sum(by_channel.values(), Decimal("0")),
        "by_channel": by_channel,
        "rows": [dict(r) for r in rows],
    }


def money_json(value):
    """Decimals as "680000.00" strings in JSON (the API never sends money as floats)."""
    if isinstance(value, Decimal):
        return f"{value:.2f}"
    if isinstance(value, dict):
        return {k: money_json(v) for k, v in value.items()}
    if isinstance(value, list):
        return [money_json(v) for v in value]
    return value


def xlsx(rows: list[dict]) -> bytes:
    wb = Workbook()
    ws = wb.active
    if rows:
        ws.append(list(rows[0].keys()))
        for r in rows:
            ws.append(
                [
                    float(v) if isinstance(v, Decimal) else (str(v) if isinstance(v, uuid.UUID) else v)
                    for v in r.values()
                ]
            )
    out = io.BytesIO()
    wb.save(out)
    return out.getvalue()


# ---------------------------------------------------------------- reminders


async def remind(session: AsyncSession, school_id: uuid.UUID, today: date) -> list[dict]:
    """Queue overdue reminders for one school (current context). Returns the SMS task calls."""
    overdue = (
        await session.execute(
            text(
                "SELECT i.id AS invoice_id, v.seq, v.due_date, v.amount_tzs - v.covered_tzs AS due_tzs "
                "FROM v_installment_status v JOIN invoices i ON i.id = v.invoice_id "
                "WHERE v.status <> 'PAID' AND v.due_date < :today AND i.cancelled_at IS NULL "
                "UNION ALL "
                "SELECT i.id, 0, i.due_date, i.balance_tzs FROM invoices i "
                "WHERE i.cancelled_at IS NULL AND i.balance_tzs > 0 AND i.due_date < :today "
                "AND NOT EXISTS (SELECT 1 FROM invoice_installments ii WHERE ii.invoice_id = i.id)"
            ).bindparams(today=today)
        )
    ).all()
    if not overdue:
        return []
    school = (await session.execute(select(School.name))).scalar_one()
    calls = []
    for invoice_id, seq, due, amount in overdue:
        key = f"reminder:{invoice_id.hex}:{seq}"
        if (await session.execute(select(SmsMessage.id).where(SmsMessage.idempotency_key == key))).first():
            continue
        invoice = (await session.execute(select(Invoice).where(Invoice.id == invoice_id))).scalar_one()
        guardian = await _primary_guardian(session, invoice.student_id)
        phone = decrypt_phone(guardian) if guardian else None
        if not phone:
            continue
        learner = (
            await session.execute(
                select(User.first_name)
                .join(Student, Student.user_id == User.id)
                .where(Student.id == invoice.student_id)
            )
        ).scalar()
        control = (
            await session.execute(
                select(GepgBill.control_number).where(
                    GepgBill.invoice_id == invoice.id, GepgBill.status == GepgStatus.ISSUED
                )
            )
        ).scalar() or invoice.invoice_no
        body = (await template_text(session, "fee_reminder", guardian.preferred_language)).format(
            school=school[:40],
            student=learner,
            amount=ledger.tzs(Decimal(amount)),
            due=f"{due:%d/%m/%Y}",
            control_no=control,
        )
        message = await sms.queue_sms(
            session,
            school_id=school_id,
            phone=phone,
            body=body,
            language=guardian.preferred_language,
            to_user_id=guardian.id,
            template_key="fee_reminder",
            idempotency_key=key,
            related_entity="invoices",
            related_id=invoice.id,
        )
        calls.append({"sms_id": str(message.id), "school_id": str(school_id)})
    await session.commit()
    return calls


async def run_reminders(school_id: str, today: str | None = None) -> str:
    async with school_session(uuid.UUID(school_id)) as session:
        calls = await remind(session, uuid.UUID(school_id), date.fromisoformat(today) if today else date.today())
    for call in calls:
        get_dispatcher().send("sms.send", **call)
    return f"{len(calls)} reminders"


async def fanout(today: str | None = None) -> str:
    """Daily (Celery beat): one reminders job per active school, each under its own tenant context."""
    async with provider.app() as session:
        await set_context(session, DbContext())
        schools = (await session.execute(select(func.list_active_school_ids()))).scalars().all()
    for school_id in schools:
        get_dispatcher().send("reminders.run", school_id=str(school_id), today=today)
    return f"{len(schools)} schools"
