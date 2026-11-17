"""Small helpers shared by services: EAT clock, document numbers, security audit events."""
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.models import AuditLog, User

EAT = timezone(timedelta(hours=3), "EAT")      # Tanzania: UTC+3, no daylight saving

_NUMBERS = {
    "admission": ("seq_admission_no", "S{year}-{n:04d}"),
    "enrolment": ("seq_enrolment_no", "ENR-{year}-{n:06d}"),
    "invoice": ("seq_invoice_no", "INV-{year}-{n:06d}"),
    "transaction": ("seq_trans_no", "TXN-{year}-{n:06d}"),
}


def now_eat() -> datetime:
    return datetime.now(EAT)


def next_number(db: Session, kind: str) -> str:
    sequence, pattern = _NUMBERS[kind]          # fixed whitelist, never user input
    n = db.execute(text(f"SELECT nextval('{sequence}')")).scalar_one()
    return pattern.format(year=now_eat().year, n=n)


@dataclass
class RequestMeta:
    ip: str | None = None
    user_agent: str | None = None
    request_id: str | None = None


def record_event(
    db: Session,
    action: str,
    meta: RequestMeta,
    actor: User | None = None,
    entity_type: str = "users",
    entity_id: object = None,
    details: dict | None = None,
) -> None:
    """Security events (LOGIN, LOGIN_FAILED, TOKEN_REUSE ...). Row changes are audited by the DB trigger."""
    db.add(AuditLog(
        actor_user_id=actor.user_id if actor else None,
        actor_role=actor.role.value if actor else None,
        action=action,
        entity_type=entity_type,
        entity_id=None if entity_id is None else str(entity_id),
        new_values=details,
        ip_address=meta.ip,
        user_agent=(meta.user_agent or "")[:255] or None,
        request_id=uuid.UUID(meta.request_id) if meta.request_id else None,
    ))
