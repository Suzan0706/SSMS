"""Absence alerts: one SMS per absent student per school day to the primary guardian (who receives SMS).

Celery beat runs `fanout` every 5 minutes, Monday to Saturday; each school's job does nothing before its cut-off
(school_settings.absence_sms_cutoff, default 08:30 EAT) or after ALERT_UNTIL, on weekends, holidays and outside
terms. A student counts as absent only when the school has recorded something for them that day, so a school that
did not take registers or use the gate never alarms every parent:
  * the stream's morning register was taken and marks the student ABSENT, or
  * the stream has no register that day, but the gate is in use (at least one tap) and the student has no tap.
A gate tap or a PRESENT/LATE/EXCUSED register mark always wins. `absence_alerts` (unique per student and day) and
the SMS idempotency key `absence:<student>:<date>` make every run safe to repeat.
"""

import uuid
from datetime import date, datetime, time

from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import DbContext, provider, school_session, set_context
from app.models import AbsenceAlert, School, SchoolSettings, Student, User
from app.services import calendar, sms
from app.services.payments import _primary_guardian, template_text
from app.services.people import decrypt_phone
from app.tasks.dispatch import get_dispatcher

ALERT_UNTIL = time(12, 0)  # registers taken later than this do not trigger SMS (VERIFY with schools)

ABSENT_SQL = text("""
WITH active AS (
    SELECT e.student_id, e.stream_id FROM enrolments e
    JOIN terms t ON t.academic_year_id = e.academic_year_id AND :day BETWEEN t.start_date AND t.end_date
    WHERE e.status = 'ACTIVE' AND t.deleted_at IS NULL),
registers AS (
    SELECT s.id, s.stream_id FROM attendance_sessions s WHERE s.session_date = :day AND s.kind = 'REGISTER'),
gate AS (
    SELECT r.student_id FROM attendance_records r JOIN attendance_sessions s ON s.id = r.session_id
    WHERE s.session_date = :day AND s.kind = 'GATE'),
marked_absent AS (
    SELECT r.student_id FROM attendance_records r JOIN registers g ON g.id = r.session_id WHERE r.status = 'ABSENT'),
attended AS (
    SELECT r.student_id FROM attendance_records r JOIN registers g ON g.id = r.session_id
    WHERE r.status IN ('PRESENT','LATE','EXCUSED')
    UNION SELECT student_id FROM gate),
no_register_no_tap AS (
    SELECT a.student_id FROM active a
    WHERE EXISTS (SELECT 1 FROM gate)
      AND NOT EXISTS (SELECT 1 FROM registers g WHERE g.stream_id = a.stream_id))
SELECT DISTINCT a.student_id FROM active a
WHERE (a.student_id IN (SELECT student_id FROM marked_absent)
       OR a.student_id IN (SELECT student_id FROM no_register_no_tap))
  AND a.student_id NOT IN (SELECT student_id FROM attended)
  AND NOT EXISTS (SELECT 1 FROM absence_alerts x WHERE x.student_id = a.student_id AND x.absence_date = :day)
""")


async def absent_students(session: AsyncSession, day: date) -> list[uuid.UUID]:
    return list((await session.execute(ABSENT_SQL, {"day": day})).scalars())


async def alert(session: AsyncSession, school_id: uuid.UUID, day: date, moment: datetime | None = None) -> list[dict]:
    """Queue the day's alerts; returns the sms.send calls to dispatch after commit."""
    local = calendar.local(moment) if moment else datetime.now(calendar.EAT)
    cutoff = (
        await session.execute(select(SchoolSettings.absence_sms_cutoff).where(SchoolSettings.school_id == school_id))
    ).scalar() or time(8, 30)
    if local.date() != day or not cutoff <= local.time() <= ALERT_UNTIL:
        return []
    if await calendar.closed_reason(session, day):
        return []
    school = (await session.execute(select(School.name).where(School.id == school_id))).scalar_one()
    calls = []
    for student_id in await absent_students(session, day):
        learner = (
            await session.execute(
                select(User.first_name, User.last_name)
                .join(Student, Student.user_id == User.id)
                .where(Student.id == student_id)
            )
        ).first()
        guardian = await _primary_guardian(session, student_id)
        phone = decrypt_phone(guardian) if guardian else None
        row = AbsenceAlert(school_id=school_id, student_id=student_id, absence_date=day)
        if phone:
            lang = guardian.preferred_language
            body = (await template_text(session, "absence_alert", lang)).format(
                school=school[:40], student=f"{learner.first_name} {learner.last_name}", date=day.strftime("%d/%m/%Y")
            )
            message = await sms.queue_sms(
                session,
                school_id=school_id,
                phone=phone,
                body=body,
                language=lang,
                to_user_id=guardian.id,
                template_key="absence_alert",
                idempotency_key=f"absence:{student_id}:{day.isoformat()}",
                related_entity="students",
                related_id=student_id,
            )
            row.sms_message_id = message.id
            if message.status == "QUEUED":
                calls.append({"sms_id": str(message.id), "school_id": str(school_id)})
        session.add(row)
        await session.flush()
    await session.commit()
    return calls


async def run(school_id: str, day: str | None = None, moment: str | None = None) -> str:
    async with school_session(uuid.UUID(school_id)) as session:
        calls = await alert(
            session,
            uuid.UUID(school_id),
            date.fromisoformat(day) if day else calendar.today(),
            datetime.fromisoformat(moment) if moment else None,
        )
    for call in calls:
        get_dispatcher().send("sms.send", **call)
    return f"{len(calls)} absence alerts"


async def fanout() -> str:
    """Every 5 minutes, Monday to Saturday (Celery beat): one absence job per active school."""
    async with provider.app() as session:
        await set_context(session, DbContext())
        schools = (await session.execute(select(func.list_active_school_ids()))).scalars().all()
    for school_id in schools:
        get_dispatcher().send("absence.run", school_id=str(school_id))
    return f"{len(schools)} schools"
