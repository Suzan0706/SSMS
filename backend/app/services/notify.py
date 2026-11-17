"""Builds bilingual SMS texts from the database and hands them to Celery.

Tasks receive ready-made (phone, text) pairs, so workers never need request data.
"""
import logging

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.i18n import render
from app.models import Guardian, Student, StudentGuardian, User

log = logging.getLogger(__name__)


def enqueue_sms(phone: str | None, message: str) -> None:
    if not phone:
        return
    from app.tasks.notifications import send_sms
    try:
        send_sms.delay(phone, message)
    except Exception:                       # broker down must not fail the request
        log.exception("could not enqueue SMS to %s", phone)


def sms_user(user: User, key: str, **values) -> None:
    """Values may be {"sw": ..., "en": ...} dicts; the recipient's language is picked."""
    lang = user.preferred_language
    resolved = {k: (v.get(lang, v.get("en")) if isinstance(v, dict) else v) for k, v in values.items()}
    enqueue_sms(user.phone, render(key, lang, school=get_settings().school_name, **resolved))


def sms_guardians(db: Session, student: Student, key: str, primary_only: bool = False, **values) -> int:
    stmt = (select(User)
            .join(Guardian, Guardian.user_id == User.user_id)
            .join(StudentGuardian, StudentGuardian.guardian_id == Guardian.guardian_id)
            .where(StudentGuardian.student_id == student.student_id))
    if primary_only:
        stmt = stmt.where(StudentGuardian.is_primary)
    guardians = db.scalars(stmt).all()
    for g in guardians:
        sms_user(g, key, name=student.user.full_name, **values)
    return len(guardians)
