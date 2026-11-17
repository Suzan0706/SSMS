"""Announcements (feed + optional SMS job), the in-app inbox, editable message templates, SMS log and credit.

SMS recipients: guardians who receive SMS (receives_sms on a link to an actively enrolled student, which is cleared
when consent is withdrawn) and active staff with a phone. The credit needed (recipients x segments) is checked
before the announcement is saved, so a school never half-sends an announcement.
"""

import string
import uuid
from datetime import UTC, datetime

from sqlalchemy import func, or_, select, text, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import Principal
from app.core.errors import AppError, not_found
from app.db.session import DbContext, school_session, set_context
from app.models import (
    Announcement,
    BackgroundJob,
    Enrolment,
    Guardian,
    MessageTemplate,
    Notification,
    School,
    SchoolClass,
    SmsCreditTransaction,
    SmsMessage,
    Staff,
    Stream,
    Student,
    StudentGuardian,
    User,
)
from app.models.enums import Audience, EnrolmentStatus, JobKind, JobStatus
from app.schemas.communication import (
    AnnouncementCreated,
    AnnouncementIn,
    AnnouncementOut,
    CreditOut,
    CreditRow,
    NotificationOut,
    SmsRow,
    TemplateOut,
)
from app.services import crud, email, imports, sms
from app.services.onboarding import TEMPLATES
from app.services.people import decrypt_phone
from app.tasks.dispatch import get_dispatcher

GUARDIANS_SQL = text("""
SELECT DISTINCT u.id FROM users u
JOIN guardians g ON g.user_id = u.id AND g.deleted_at IS NULL
JOIN student_guardians sg ON sg.guardian_id = g.id AND sg.deleted_at IS NULL AND sg.receives_sms
JOIN enrolments e ON e.student_id = sg.student_id AND e.status = 'ACTIVE'
JOIN academic_years y ON y.id = e.academic_year_id AND y.is_current
JOIN streams s ON s.id = e.stream_id
WHERE u.status = 'ACTIVE' AND u.deleted_at IS NULL AND u.phone_enc IS NOT NULL
  AND (CAST(:stream AS uuid) IS NULL OR s.id = CAST(:stream AS uuid))
  AND (CAST(:class AS uuid) IS NULL OR s.class_id = CAST(:class AS uuid))
""")
STAFF_SQL = text("""
SELECT u.id FROM users u JOIN staff st ON st.user_id = u.id AND st.deleted_at IS NULL AND st.status = 'ACTIVE'
WHERE u.status = 'ACTIVE' AND u.deleted_at IS NULL AND u.phone_enc IS NOT NULL
""")
CONSENTING_SQL = text("""
SELECT 1 FROM guardians g JOIN student_guardians sg ON sg.guardian_id = g.id AND sg.deleted_at IS NULL
WHERE g.user_id = :user AND g.deleted_at IS NULL AND sg.receives_sms LIMIT 1
""")


def out(item: Announcement) -> AnnouncementOut:
    return AnnouncementOut.model_validate(item, from_attributes=True)


async def recipients(session: AsyncSession, item: Announcement) -> list[uuid.UUID]:
    """Users who get the SMS of an announcement (consent rules in the module docstring)."""

    async def guardians(stream=None, klass=None) -> set[uuid.UUID]:
        rows = await session.execute(GUARDIANS_SQL, {"stream": stream, "class": klass})
        return set(rows.scalars())

    async def staff() -> set[uuid.UUID]:
        return set((await session.execute(STAFF_SQL)).scalars())

    if item.audience == Audience.SCHOOL:
        users = await guardians() | await staff()
    elif item.audience == Audience.STAFF:
        users = await staff()
    elif item.audience == Audience.PARENTS:
        users = await guardians()
    elif item.audience == Audience.CLASS:
        users = await guardians(klass=item.class_id)
    elif item.audience == Audience.STREAM:
        users = await guardians(stream=item.stream_id)
    else:
        target = item.target_user_id
        is_staff = target in await staff()
        consents = (await session.execute(CONSENTING_SQL, {"user": target})).first() is not None
        has_phone = (await session.execute(select(User.phone_enc).where(User.id == target))).scalar() is not None
        users = {target} if has_phone and (is_staff or consents) else set()
    return sorted(users)


def sms_text(school: str, item: Announcement) -> str:
    """'<school>: <title>. <body>' cut to at most 3 SMS segments."""
    full = f"{school[:30]}: {item.title}. {item.body}"
    if sms.segments(full) <= 3:
        return full
    limit = 3 * (153 if set(full) <= sms.GSM7 else 67)
    return full[: limit - 3].rstrip() + "..."


async def _check_references(session: AsyncSession, body: AnnouncementIn) -> None:
    for model, value in ((SchoolClass, body.class_id), (Stream, body.stream_id), (User, body.target_user_id)):
        if value is not None:
            try:
                await crud.get_live(session, model, value)
            except AppError:
                field = {SchoolClass: "class_id", Stream: "stream_id", User: "target_user_id"}[model]
                raise AppError(422, "INVALID_REFERENCE", [{"field": field, "code": "invalid_value"}]) from None


async def create(
    session: AsyncSession, principal: Principal, body: AnnouncementIn, idempotency_key: str | None
) -> AnnouncementCreated:
    await _check_references(session, body)
    item = Announcement(
        school_id=principal.school_id,
        created_by=principal.user_id,
        **body.model_dump(exclude={"publish_at", "send_email"}),
        publish_at=body.publish_at or datetime.now(UTC),
    )
    session.add(item)
    await session.flush()
    if body.audience == Audience.INDIVIDUAL:
        session.add(
            Notification(
                school_id=principal.school_id,
                user_id=body.target_user_id,
                kind="ANNOUNCEMENT",
                title=body.title,
                body=body.body[:500],
                link="/announcements",
                created_by=principal.user_id,
            )
        )
    created = AnnouncementCreated(**out(item).model_dump())
    if body.send_sms:
        users = await recipients(session, item)
        school = (await session.execute(select(School.name).where(School.id == principal.school_id))).scalar_one()
        needed, left = (
            len(users) * sms.segments(sms_text(school, item)),
            await sms.credits_left(session, principal.school_id),
        )
        if needed > left:
            raise AppError(422, "NO_SMS_CREDIT", [{"field": "send_sms", "code": "no_credit"}], needed=needed, left=left)
        job = BackgroundJob(
            school_id=principal.school_id,
            kind=JobKind.SMS_BATCH,
            status=JobStatus.QUEUED,
            total_items=len(users),
            idempotency_key=idempotency_key,
            requested_by=principal.user_id,
            created_by=principal.user_id,
        )
        session.add(job)
        created.sms_recipients, created.sms_job_id = len(users), job.id
    emails = []
    if body.send_email:
        for user_id in await recipients(session, item):
            message = await email.queue_email(
                session,
                school_id=principal.school_id,
                user_id=user_id,
                subject=item.title,
                body=item.body,
                idempotency_key=f"ann:{item.id}:{user_id}",
                template_key="announcement",
                related_entity="announcements",
                related_id=item.id,
            )
            if message is not None:
                emails.append(message.id)
        created.email_recipients = len(emails)
    await session.commit()
    for email_id in emails:
        get_dispatcher().send("email.send", email_id=str(email_id), school_id=str(principal.school_id))
    if created.sms_job_id:
        get_dispatcher().send(
            "announcements.sms",
            job_id=str(created.sms_job_id),
            school_id=str(principal.school_id),
            announcement_id=str(item.id),
        )
    return created


async def run_sms(job_id: str, school_id: str, announcement_id: str) -> str:
    """SMS_BATCH job: queue one SMS per recipient (key ann:<announcement>:<user>), then send them."""
    school_uuid = uuid.UUID(school_id)
    async with school_session(school_uuid) as session:
        job = (
            await session.execute(select(BackgroundJob).where(BackgroundJob.id == uuid.UUID(job_id)).with_for_update())
        ).scalar_one_or_none()
        if job is None or job.status not in (JobStatus.QUEUED, JobStatus.RUNNING):
            return "skipped"
        job.status, job.started_at = JobStatus.RUNNING, datetime.now(UTC)
        await session.commit()
        await set_context(session, DbContext(school_id=school_uuid, user_id=job.requested_by))
        item = (
            await session.execute(select(Announcement).where(Announcement.id == uuid.UUID(announcement_id)))
        ).scalar_one()
        school = (await session.execute(select(School.name).where(School.id == school_uuid))).scalar_one()
        body = sms_text(school, item)
        calls, skipped = [], 0
        for user_id in await recipients(session, item):
            key = f"ann:{item.id.hex}:{user_id.hex}"
            if (await session.execute(select(SmsMessage.id).where(SmsMessage.idempotency_key == key))).first():
                continue
            user = (await session.execute(select(User).where(User.id == user_id))).scalar_one()
            phone = decrypt_phone(user)
            if not phone:
                skipped += 1
                continue
            message = await sms.queue_sms(
                session,
                school_id=school_uuid,
                phone=phone,
                body=body,
                language=item.language,
                to_user_id=user_id,
                template_key="announcement",
                idempotency_key=key,
                related_entity="announcements",
                related_id=item.id,
            )
            if message.status == "QUEUED":
                calls.append({"sms_id": str(message.id), "school_id": school_id})
            else:
                skipped += 1
        job.processed_items = len(calls)
        imports.finish_job(job, JobStatus.SUCCEEDED, skipped)
        await session.commit()
    for call in calls:
        get_dispatcher().send("sms.send", **call)
    return f"{len(calls)} sent"


async def _viewer_scope(session: AsyncSession, principal: Principal) -> tuple[bool, set, set]:
    """(is staff, class ids, stream ids) of the viewer's own (student) or children's (guardian) enrolments."""
    is_staff = (
        await session.execute(select(Staff.id).where(Staff.user_id == principal.user_id, Staff.deleted_at.is_(None)))
    ).first() is not None
    students = (
        select(StudentGuardian.student_id)
        .join(Guardian, Guardian.id == StudentGuardian.guardian_id)
        .where(Guardian.user_id == principal.user_id, StudentGuardian.deleted_at.is_(None))
    )
    own = select(Student.id).where(Student.user_id == principal.user_id)
    rows = (
        await session.execute(
            select(Stream.id, Stream.class_id)
            .join(Enrolment, Enrolment.stream_id == Stream.id)
            .where(
                Enrolment.status == EnrolmentStatus.ACTIVE,
                or_(Enrolment.student_id.in_(students), Enrolment.student_id.in_(own)),
            )
        )
    ).all()
    return is_staff, {r.class_id for r in rows}, {r.id for r in rows}


async def feed(session: AsyncSession, principal: Principal, limit: int = 50) -> list[AnnouncementOut]:
    stmt = select(Announcement).where(Announcement.deleted_at.is_(None))
    if not principal.has("announcements.send"):
        is_staff, classes, streams = await _viewer_scope(session, principal)
        visible = [Announcement.audience == Audience.SCHOOL, Announcement.target_user_id == principal.user_id]
        if is_staff:
            visible.append(Announcement.audience == Audience.STAFF)
        if principal.has("portal.parent"):
            visible.append(Announcement.audience == Audience.PARENTS)
        if classes:
            visible.append(Announcement.class_id.in_(classes))
        if streams:
            visible.append(Announcement.stream_id.in_(streams))
        stmt = stmt.where(or_(*visible), Announcement.publish_at <= datetime.now(UTC))
    rows = (await session.execute(stmt.order_by(Announcement.publish_at.desc()).limit(limit))).scalars()
    return [out(r) for r in rows]


async def remove(session: AsyncSession, announcement_id: uuid.UUID) -> None:
    item = await crud.get_live(session, Announcement, announcement_id, lock=True)
    item.deleted_at = datetime.now(UTC)
    await session.commit()


# ---------------------------------------------------------------- inbox


async def inbox(session: AsyncSession, principal: Principal) -> tuple[int, list[NotificationOut]]:
    mine = Notification.user_id == principal.user_id
    unread = (await session.execute(select(func.count()).where(mine, Notification.read_at.is_(None)))).scalar_one()
    rows = (
        await session.execute(
            select(Notification)
            .where(mine)
            .order_by(Notification.read_at.is_not(None), Notification.created_at.desc())
            .limit(50)
        )
    ).scalars()
    return unread, [NotificationOut.model_validate(r, from_attributes=True) for r in rows]


async def mark_read(session: AsyncSession, principal: Principal, notification_id: uuid.UUID | None) -> None:
    where = [Notification.user_id == principal.user_id, Notification.read_at.is_(None)]
    if notification_id:
        where.append(Notification.id == notification_id)
    result = await session.execute(update(Notification).where(*where).values(read_at=datetime.now(UTC)))
    if notification_id and result.rowcount == 0:
        exists = (
            await session.execute(
                select(Notification.id).where(
                    Notification.id == notification_id, Notification.user_id == principal.user_id
                )
            )
        ).first()
        if not exists:
            raise not_found()
    await session.commit()


# ---------------------------------------------------------------- templates

SAMPLE = {"school": "S" * 40}  # longest school name an SMS carries; other placeholders count 12 characters


def placeholders(body: str) -> list[str]:
    try:
        return sorted({name for _, name, _, _ in string.Formatter().parse(body) if name})
    except ValueError:
        return ["{"]


async def templates(session: AsyncSession) -> list[TemplateOut]:
    rows = {
        (t.key, t.language): t
        for t in (await session.execute(select(MessageTemplate).where(MessageTemplate.deleted_at.is_(None)))).scalars()
    }
    result = []
    for key, defaults in TEMPLATES.items():
        for lang, default in zip(("sw", "en"), defaults, strict=True):
            row = rows.get((key, lang))
            result.append(
                TemplateOut(
                    key=key,
                    language=lang,
                    body=row.body if row else default,
                    is_active=row.is_active if row else True,
                    customised=row is not None,
                    placeholders=placeholders(default),
                )
            )
    return result


async def save_template(
    session: AsyncSession, principal: Principal, key: str, lang: str, body: str, is_active: bool
) -> TemplateOut:
    if key not in TEMPLATES or lang not in ("sw", "en"):
        raise not_found()
    allowed = set(placeholders(TEMPLATES[key][0]))
    for name in placeholders(body):
        if name not in allowed:
            raise AppError(422, "VALIDATION_ERROR", [{"field": "body", "code": "bad_placeholder"}], name=name)
    sample = body.format(**{n: SAMPLE.get(n, "X" * 12) for n in allowed})
    if sms.segments(sample) > 3:
        raise AppError(
            422, "VALIDATION_ERROR", [{"field": "body", "code": "sms_too_long"}], segments=sms.segments(sample)
        )
    row = (
        await session.execute(
            select(MessageTemplate)
            .where(MessageTemplate.key == key, MessageTemplate.language == lang, MessageTemplate.deleted_at.is_(None))
            .with_for_update()
        )
    ).scalar_one_or_none()
    if row is None:
        row = MessageTemplate(school_id=principal.school_id, key=key, language=lang, created_by=principal.user_id)
        session.add(row)
    row.body, row.is_active = body, is_active
    await session.commit()
    return next(t for t in await templates(session) if t.key == key and t.language == lang)


# ---------------------------------------------------------------- SMS log and credit


async def sms_log(session: AsyncSession, status: str | None, limit: int = 100) -> list[SmsRow]:
    stmt = select(SmsMessage).order_by(SmsMessage.queued_at.desc()).limit(limit)
    if status:
        stmt = stmt.where(SmsMessage.status == status)
    return [
        SmsRow(
            id=m.id,
            to=f"****{m.to_phone_last4}",
            template_key=m.template_key,
            language=m.language,
            body=m.body,
            segments=m.segments,
            status=m.status,
            cost_credits=m.cost_credits,
            error=m.error,
            queued_at=m.queued_at,
            sent_at=m.sent_at,
            delivered_at=m.delivered_at,
        )
        for m in (await session.execute(stmt)).scalars()
    ]


async def credit(session: AsyncSession, school_id: uuid.UUID) -> CreditOut:
    left = await sms.credits_left(session, school_id)
    history = (
        await session.execute(
            select(SmsCreditTransaction)
            .where(SmsCreditTransaction.school_id == school_id, SmsCreditTransaction.kind != "DEBIT")
            .order_by(SmsCreditTransaction.created_at.desc())
            .limit(50)
        )
    ).scalars()
    return CreditOut(
        credits_left=left,
        low=left < sms.LOW_CREDIT,
        history=[CreditRow.model_validate(h, from_attributes=True) for h in history],
    )
