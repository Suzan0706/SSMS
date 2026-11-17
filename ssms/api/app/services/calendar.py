"""School days in East Africa Time: registers, gate taps and absence alerts only count on them."""

from datetime import date, datetime, timedelta, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import PublicHoliday, Term, TimetableSlot

EAT = timezone(timedelta(hours=3), "EAT")


def today() -> date:
    return datetime.now(EAT).date()


def local(moment: datetime) -> datetime:
    """A device or phone time in EAT (naive times are taken as EAT)."""
    return moment.astimezone(EAT) if moment.tzinfo else moment.replace(tzinfo=EAT)


async def term_on(session: AsyncSession, day: date) -> Term | None:
    return (
        await session.execute(
            select(Term).where(Term.start_date <= day, Term.end_date >= day, Term.deleted_at.is_(None)).limit(1)
        )
    ).scalar_one_or_none()


async def _saturday_lessons(session: AsyncSession, term: Term) -> bool:
    lessons = select(TimetableSlot.id).where(
        TimetableSlot.term_id == term.id, TimetableSlot.day_of_week == 6, TimetableSlot.deleted_at.is_(None)
    )
    return (await session.execute(lessons.limit(1))).first() is not None


async def closed_reason(session: AsyncSession, day: date) -> str | None:
    """None on a school day, else 'weekend', 'holiday' (national or school closure) or 'outside_term'.

    Sunday is always closed; Saturday is a school day only where the term's timetable has Saturday lessons.
    """
    if day.weekday() == 6:
        return "weekend"
    term = await term_on(session, day)
    if day.weekday() == 5 and (term is None or not await _saturday_lessons(session, term)):
        return "weekend"
    holiday = (
        await session.execute(
            select(PublicHoliday.id).where(PublicHoliday.holiday_date == day, PublicHoliday.deleted_at.is_(None))
        )
    ).first()
    if holiday:
        return "holiday"
    if term is None:
        return "outside_term"
    return None
