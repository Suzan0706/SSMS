"""Gate devices, RFID/QR cards and taps.

A device authenticates with an API key (X-Device-Key); only its SHA-256 is stored and `resolve_device` finds the
school, the same way GePG callbacks are routed. Cards store only the SHA-256 of the card UID or QR payload. The
first tap of a school day makes the student PRESENT at the gate (LATE after the school's absence cut-off — VERIFY
whether schools want a separate start time); later taps that day are duplicates. Device firmware formats are VERIFY.
"""

import hashlib
import logging
import secrets
import uuid
from datetime import time, timedelta

from sqlalchemy import func, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import Principal
from app.core.errors import AppError
from app.core.ratelimit import enforce
from app.db.session import DbContext, provider, set_context
from app.models import AttendanceRecord, Device, RfidCard, SchoolSettings, Student, User
from app.models.enums import AttendanceSource, AttendanceStatus, CardStatus, DeviceKind, SessionKind
from app.schemas.attendance import CardIn, CardOut, DeviceCreated, DeviceIn, DeviceOut, Tap, TapResult
from app.services import calendar, crud
from app.services.attendance import SYNC_DAYS, open_session
from app.services.people import now

log = logging.getLogger(__name__)
TAPS_PER_MINUTE = 600  # one reader at a busy gate


def digest(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


def device_out(device: Device) -> DeviceOut:
    return DeviceOut.model_validate(device, from_attributes=True)


async def create_device(session: AsyncSession, principal: Principal, body: DeviceIn) -> DeviceCreated:
    key = "ssmsdev_" + secrets.token_urlsafe(32)
    device = Device(
        school_id=principal.school_id,
        name=body.name,
        kind=body.kind,
        location=body.location,
        api_key_hash=digest(key),
        created_by=principal.user_id,
    )
    session.add(device)
    await session.commit()
    return DeviceCreated(**device_out(device).model_dump(), api_key=key)


async def rotate_key(session: AsyncSession, device_id: uuid.UUID) -> DeviceCreated:
    device = await crud.get_live(session, Device, device_id, lock=True)
    key = "ssmsdev_" + secrets.token_urlsafe(32)
    device.api_key_hash = digest(key)
    await session.commit()
    return DeviceCreated(**device_out(device).model_dump(), api_key=key)


# ---------------------------------------------------------------- cards


async def card_rows(session: AsyncSession, *where) -> list[CardOut]:
    rows = (
        await session.execute(
            select(RfidCard, Student.admission_no, User.first_name, User.middle_name, User.last_name)
            .join(Student, Student.id == RfidCard.student_id)
            .join(User, User.id == Student.user_id)
            .where(RfidCard.deleted_at.is_(None), *where)
            .order_by(RfidCard.issued_at.desc())
            .limit(200)
        )
    ).all()
    return [
        CardOut(
            id=card.id,
            student_id=card.student_id,
            admission_no=admission,
            full_name=" ".join(p for p in (first, middle, last) if p),
            kind=card.kind,
            status=card.status,
            issued_at=card.issued_at,
        )
        for card, admission, first, middle, last in rows
    ]


async def issue_card(session: AsyncSession, principal: Principal, body: CardIn) -> CardOut:
    """A new card replaces the student's active card of the same kind (the old one becomes REVOKED)."""
    await crud.get_live(session, Student, body.student_id)
    await session.execute(
        update(RfidCard)
        .where(
            RfidCard.student_id == body.student_id,
            RfidCard.kind == body.kind,
            RfidCard.status == CardStatus.ACTIVE,
            RfidCard.deleted_at.is_(None),
        )
        .values(status=CardStatus.REVOKED)
    )
    card = RfidCard(
        school_id=principal.school_id,
        student_id=body.student_id,
        kind=body.kind,
        token_hash=digest(body.token.strip()),
        created_by=principal.user_id,
    )
    session.add(card)
    try:
        await session.flush()
    except IntegrityError as exc:
        if getattr(exc.orig, "sqlstate", None) == "23505":
            raise AppError(409, "DUPLICATE", [{"field": "token", "code": "card_in_use"}]) from None
        raise
    await session.commit()
    return (await card_rows(session, RfidCard.id == card.id))[0]


async def set_card_status(session: AsyncSession, card_id: uuid.UUID, status: str) -> CardOut:
    card = await crud.get_live(session, RfidCard, card_id, lock=True)
    if card.status != CardStatus.ACTIVE:
        raise AppError(409, "NOT_ALLOWED", [{"field": "status", "code": "invalid_value"}])
    card.status = CardStatus(status)
    await session.commit()
    return (await card_rows(session, RfidCard.id == card.id))[0]


# ---------------------------------------------------------------- taps


async def _cutoff(session: AsyncSession, school_id: uuid.UUID) -> time:
    value = (
        await session.execute(select(SchoolSettings.absence_sms_cutoff).where(SchoolSettings.school_id == school_id))
    ).scalar()
    return value or time(8, 30)


async def taps(api_key: str | None, items: list[Tap]) -> list[TapResult] | None:
    """None when the key is unknown or the device disabled (the route answers 401)."""
    if not api_key:
        return None
    async with provider.app() as session:
        row = (
            await session.execute(select(func.resolve_device(digest(api_key)).table_valued("school_id", "device_id")))
        ).first()
        if row is None:
            return None
        await enforce(f"device:{row.device_id}", TAPS_PER_MINUTE, 60)
        await set_context(session, DbContext(school_id=row.school_id))
        device = (await session.execute(select(Device).where(Device.id == row.device_id))).scalar_one()
        source = AttendanceSource.QR if device.kind == DeviceKind.QR_SCANNER else AttendanceSource.RFID
        cutoff = await _cutoff(session, row.school_id)
        today = calendar.today()
        closed: dict = {}
        results = []
        for tap in items:
            moment = calendar.local(tap.captured_at)
            day = moment.date()
            if day not in closed:
                too_far = day > today or day < today - timedelta(days=SYNC_DAYS)
                closed[day] = "too_far" if too_far else await calendar.closed_reason(session, day)
            if closed[day]:
                outcome = "out_of_window" if closed[day] == "too_far" else "not_school_day"
                results.append(TapResult(client_record_id=tap.client_record_id, result=outcome))
                continue
            seen = (
                await session.execute(
                    select(AttendanceRecord.id).where(AttendanceRecord.client_record_id == tap.client_record_id)
                )
            ).first()
            card = (
                await session.execute(
                    select(RfidCard.student_id, User.first_name, User.last_name)
                    .join(Student, Student.id == RfidCard.student_id)
                    .join(User, User.id == Student.user_id)
                    .where(
                        RfidCard.token_hash == digest(tap.token.strip()),
                        RfidCard.status == CardStatus.ACTIVE,
                        RfidCard.deleted_at.is_(None),
                    )
                )
            ).first()
            if card is None:
                log.warning("gate tap with unknown or inactive card (device %s)", device.id)
                results.append(TapResult(client_record_id=tap.client_record_id, result="unknown_card"))
                continue
            name = f"{card.first_name} {card.last_name}"
            gate = await open_session(session, row.school_id, day, None, SessionKind.GATE, None)
            first = (
                await session.execute(
                    select(AttendanceRecord.id).where(
                        AttendanceRecord.session_id == gate.id, AttendanceRecord.student_id == card.student_id
                    )
                )
            ).first()
            if seen or first:
                results.append(TapResult(client_record_id=tap.client_record_id, result="duplicate", student_name=name))
                continue
            late = moment.time() > cutoff
            session.add(
                AttendanceRecord(
                    school_id=row.school_id,
                    session_id=gate.id,
                    student_id=card.student_id,
                    status=AttendanceStatus.LATE if late else AttendanceStatus.PRESENT,
                    source=source,
                    device_id=device.id,
                    captured_at=moment,
                    client_record_id=tap.client_record_id,
                )
            )
            await session.flush()
            results.append(
                TapResult(
                    client_record_id=tap.client_record_id, result="late" if late else "present", student_name=name
                )
            )
        device.last_seen_at = now()
        await session.commit()
        return results
