"""Role dashboards (FR-67): a few KPI tiles and small series, computed in one round of aggregate queries and cached
for a minute per school and role, so a busy morning does not recompute them on every page view.

admin: students and staff, today's register coverage and attendance, fees billed/collected this term, outstanding,
       SMS credit, chronic absentees, things waiting for a decision; enrolment by class and sex; 30-day collections.
bursar: billed, collected, outstanding, overdue invoices; 30-day collections; collections by channel; aging.
teacher: today's registers of the teacher's streams, open discipline cases they recorded.
"""

import time
import uuid
from datetime import datetime, timedelta
from decimal import Decimal

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import Principal
from app.services import attendance, calendar, sms, years

TTL_SECONDS = 60
_cache: dict[tuple, tuple[float, dict]] = {}


def _money(value) -> str:
    return f"{Decimal(value or 0):.2f}"


async def _one(session: AsyncSession, sql: str, **params):
    return (await session.execute(text(sql), params)).one()


async def _all(session: AsyncSession, sql: str, **params) -> list:
    return list((await session.execute(text(sql), params)).all())


async def _term(session: AsyncSession):
    return await calendar.term_on(session, calendar.today())


async def _collections(session: AsyncSession, days: int = 30) -> list[dict]:
    start = calendar.today() - timedelta(days=days - 1)
    rows = await _all(
        session,
        "SELECT (p.received_at AT TIME ZONE 'Africa/Dar_es_Salaam')::date AS day, sum(p.amount_tzs) "
        "FROM payments p WHERE p.status = 'CONFIRMED' AND p.received_at >= CAST(:start AS date) GROUP BY 1 ORDER BY 1",
        start=start,
    )
    by_day = {r[0]: r[1] for r in rows}
    return [
        {"day": (start + timedelta(days=i)).isoformat(), "amount_tzs": _money(by_day.get(start + timedelta(days=i)))}
        for i in range(days)
    ]


async def _fees(session: AsyncSession) -> dict:
    term = await _term(session)
    billed = await _one(
        session,
        "SELECT coalesce(sum(total_tzs), 0), coalesce(sum(paid_tzs), 0) FROM invoices "
        "WHERE cancelled_at IS NULL AND term_id = CAST(:term AS uuid)",
        term=term.id if term else None,
    )
    owed = await _one(
        session,
        "SELECT coalesce(sum(outstanding_tzs), 0), count(*) FILTER (WHERE outstanding_tzs > 0) "
        "FROM v_student_fee_position",
    )
    overdue = await _one(
        session,
        "SELECT count(*) FROM invoices WHERE cancelled_at IS NULL AND balance_tzs > 0 AND due_date < CAST(:today AS "
        "date)",
        today=calendar.today(),
    )
    return {
        "term_id": str(term.id) if term else None,
        "billed_tzs": _money(billed[0]),
        "collected_tzs": _money(billed[1]),
        "collection_rate_pct": round(float(billed[1]) * 100 / float(billed[0]), 1) if billed[0] else None,
        "outstanding_tzs": _money(owed[0]),
        "students_owing": owed[1],
        "overdue_invoices": overdue[0],
    }


async def admin(session: AsyncSession, principal: Principal) -> dict:
    today = calendar.today()
    people = await _one(
        session,
        "SELECT (SELECT count(*) FROM students WHERE status = 'ACTIVE' AND deleted_at IS NULL), "
        "(SELECT count(*) FROM staff WHERE status = 'ACTIVE' AND deleted_at IS NULL)",
    )
    marks = await _one(
        session,
        "SELECT count(DISTINCT s.stream_id), count(r.id), count(r.id) FILTER (WHERE r.status IN ('PRESENT','LATE')) "
        "FROM attendance_sessions s LEFT JOIN attendance_records r ON r.session_id = s.id "
        "WHERE s.session_date = CAST(:today AS date) AND s.kind = 'REGISTER'",
        today=today,
    )
    streams = (await _one(session, "SELECT count(*) FROM streams WHERE deleted_at IS NULL"))[0]
    pending = await _one(
        session,
        "SELECT (SELECT count(*) FROM accommodation_requests WHERE status = 'PENDING' AND deleted_at IS NULL), "
        "(SELECT count(*) FROM result_amendments WHERE status = 'PENDING'), "
        "(SELECT count(*) FROM payment_reversal_requests WHERE status = 'PENDING'), "
        "(SELECT count(*) FROM bank_deposit_confirmations WHERE status = 'PENDING'), "
        "(SELECT count(*) FROM discipline_records WHERE status = 'OPEN' AND deleted_at IS NULL), "
        "(SELECT count(*) FROM data_subject_requests WHERE status IN ('RECEIVED','IN_PROGRESS'))",
    )
    by_class = await _all(
        session,
        "SELECT c.code, u.gender, count(*) FROM enrolments e "
        "JOIN streams s ON s.id = e.stream_id JOIN classes c ON c.id = s.class_id JOIN students st ON st.id = "
        "e.student_id "
        "JOIN users u ON u.id = st.user_id "
        "WHERE e.academic_year_id = :year AND e.status IN ('ACTIVE', 'PROMOTED', 'REPEATED', 'GRADUATED') "
        "GROUP BY c.code, c.sort_order, u.gender ORDER BY c.sort_order",
        year=await years.viewing_year(session),
    )
    classes: dict[str, dict] = {}
    for code, gender, n in by_class:
        classes.setdefault(code, {"class": code, "M": 0, "F": 0})[gender] = n
    chronic = await attendance.chronic(session, today)
    return {
        "role": "admin",
        "tiles": {
            "students_active": people[0],
            "staff_active": people[1],
            "registers_taken": marks[0],
            "streams": streams,
            "attendance_today_pct": round(marks[2] * 100 / marks[1], 1) if marks[1] else None,
            "chronic_absentees": len(chronic),
            "sms_credit": await sms.credits_left(session, principal.school_id),
            **await _fees(session),
            "pending": {
                "accommodation": pending[0],
                "amendments": pending[1],
                "reversals": pending[2],
                "bank_deposits": pending[3],
                "discipline_open": pending[4],
                "privacy_requests": pending[5],
            },
        },
        "series": {"enrolment_by_class": list(classes.values()), "collections_30_days": await _collections(session)},
    }


async def bursar(session: AsyncSession, principal: Principal) -> dict:
    term = await _term(session)
    channels = await _all(
        session,
        "SELECT channel, sum(amount_tzs) FROM payments WHERE status = 'CONFIRMED' "
        "AND received_at >= CAST(:start AS date) GROUP BY channel ORDER BY 2 DESC",
        start=term.start_date if term else calendar.today().replace(month=1, day=1),
    )
    aging = await _all(
        session,
        "SELECT CASE WHEN days <= 30 THEN '1-30' WHEN days <= 60 THEN '31-60' WHEN days <= 90 THEN '61-90' ELSE "
        "'90+' END, "
        "sum(balance) FROM (SELECT CAST(:today AS date) - due_date AS days, balance_tzs AS balance FROM invoices "
        "WHERE cancelled_at IS NULL AND balance_tzs > 0 AND due_date < CAST(:today AS date)) q GROUP BY 1",
        today=calendar.today(),
    )
    buckets = {b: Decimal(0) for b in ("1-30", "31-60", "61-90", "90+")}
    for bucket, amount in aging:
        buckets[bucket] = amount
    return {
        "role": "bursar",
        "tiles": await _fees(session),
        "series": {
            "collections_30_days": await _collections(session),
            "collections_by_channel": [{"channel": c, "amount_tzs": _money(a)} for c, a in channels],
            "aging": [{"bucket": b, "amount_tzs": _money(a)} for b, a in buckets.items()],
        },
    }


async def teacher(session: AsyncSession, principal: Principal) -> dict:
    today = calendar.today()
    streams = await attendance.my_streams(session, principal)
    taken = {
        r[0]: (r[1], r[2])
        for r in await _all(
            session,
            "SELECT s.stream_id, count(r.id), count(r.id) FILTER (WHERE r.status = 'ABSENT') FROM "
            "attendance_sessions s "
            "LEFT JOIN attendance_records r ON r.session_id = s.id WHERE s.session_date = CAST(:today AS date) "
            "AND s.kind = 'REGISTER' GROUP BY s.stream_id",
            today=today,
        )
    }
    open_cases = (
        await _one(
            session,
            "SELECT count(*) FROM discipline_records WHERE status = 'OPEN' AND deleted_at IS NULL AND recorded_by = "
            ":me",
            me=principal.user_id,
        )
    )[0]
    registers = [
        {
            "stream_id": str(s.stream_id),
            "label": s.label,
            "class_teacher": s.class_teacher,
            "marked": taken.get(s.stream_id, (0, 0))[0],
            "absent": taken.get(s.stream_id, (0, 0))[1],
        }
        for s in streams
    ]
    return {
        "role": "teacher",
        "tiles": {
            "my_streams": len(registers),
            "registers_taken": sum(1 for r in registers if r["marked"]),
            "school_day": await calendar.closed_reason(session, today) is None,
            "open_discipline": open_cases,
        },
        "series": {"registers_today": registers},
    }


async def librarian(session: AsyncSession, principal: Principal) -> dict:
    today = calendar.today()
    stock = await _one(
        session,
        "SELECT count(*), coalesce(sum(copies), 0) FROM library_books WHERE deleted_at IS NULL",
    )
    loans = await _one(
        session,
        "SELECT count(*), count(*) FILTER (WHERE due_date < CAST(:today AS date)), "
        "count(*) FILTER (WHERE due_date BETWEEN CAST(:today AS date) AND CAST(:today AS date) + 7) "
        "FROM library_loans WHERE returned_at IS NULL",
        today=today,
    )
    overdue = await _all(
        session,
        "SELECT b.title, u.first_name || ' ' || u.last_name, l.due_date FROM library_loans l "
        "JOIN library_books b ON b.id = l.book_id JOIN users u ON u.id = l.borrower_user_id "
        "WHERE l.returned_at IS NULL AND l.due_date < CAST(:today AS date) ORDER BY l.due_date LIMIT 10",
        today=today,
    )
    return {
        "role": "librarian",
        "tiles": {
            "titles": stock[0],
            "copies": stock[1],
            "on_loan": loans[0],
            "overdue": loans[1],
            "due_this_week": loans[2],
        },
        "series": {
            "overdue_loans": [
                {"title": t, "borrower": who, "due_date": due.isoformat(), "days_late": (today - due).days}
                for t, who, due in overdue
            ]
        },
    }


async def receptionist(session: AsyncSession, principal: Principal) -> dict:
    """The admissions desk: applications of the year on screen, and recent admissions."""
    today = calendar.today()
    year = await years.viewing_year(session)
    by_status = dict(
        await _all(
            session,
            "SELECT status, count(*) FROM enrolment_applications "
            "WHERE academic_year_id = :year AND deleted_at IS NULL GROUP BY status",
            year=year,
        )
    )
    admitted = (
        await _one(
            session,
            "SELECT count(*) FROM students WHERE admission_date >= CAST(:start AS date) AND deleted_at IS NULL",
            start=today.replace(day=1),
        )
    )[0]
    latest = await _all(
        session,
        "SELECT a.application_no, u.first_name || ' ' || u.last_name, c.code, a.status, a.created_at "
        "FROM enrolment_applications a JOIN students st ON st.id = a.student_id JOIN users u ON u.id = st.user_id "
        "JOIN classes c ON c.id = a.class_id WHERE a.academic_year_id = :year AND a.deleted_at IS NULL "
        "ORDER BY a.created_at DESC LIMIT 10",
        year=year,
    )
    return {
        "role": "receptionist",
        "tiles": {
            "waiting": by_status.get("INQUIRED", 0) + by_status.get("REQUIREMENTS_PENDING", 0),
            "under_review": by_status.get("UNDER_REVIEW", 0),
            "approved": by_status.get("APPROVED", 0),
            "admitted_this_month": admitted,
        },
        "series": {
            "latest_applications": [
                {"application_no": no, "name": name, "class": cls, "status": st, "created_at": at.date().isoformat()}
                for no, name, cls, st, at in latest
            ]
        },
    }


BUILDERS = {
    "admin": admin,
    "bursar": bursar,
    "teacher": teacher,
    "librarian": librarian,
    "receptionist": receptionist,
}
# Who may open each dashboard: by permission, not role name, so custom roles get the right one (FR-73).
PERMISSIONS = {
    "admin": "settings.update",
    "bursar": "finance.read",
    "teacher": "attendance.take",
    "librarian": "library.manage",
    "receptionist": "enrolment.manage",
}


async def build(session: AsyncSession, principal: Principal, role: str) -> dict:
    """Cached per school, role and year on screen (the teacher view per user) for TTL_SECONDS."""
    key: tuple[uuid.UUID, str, uuid.UUID | None, uuid.UUID | None] = (
        principal.school_id,
        role,
        principal.user_id if role == "teacher" else None,
        session.info.get("viewing_year"),
    )
    hit = _cache.get(key)
    if hit and time.monotonic() - hit[0] < TTL_SECONDS:
        return hit[1]
    data = await BUILDERS[role](session, principal)
    data["generated_at"] = datetime.now(calendar.EAT).isoformat(timespec="seconds")
    _cache[key] = (time.monotonic(), data)
    return data


def clear_cache() -> None:
    _cache.clear()
