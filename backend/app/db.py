"""Engine, session and the audit context that feeds the fn_audit_row trigger."""
import enum
from collections.abc import Iterator

from sqlalchemy import Enum as SAEnum
from sqlalchemy import create_engine, event, text
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from app.core.config import get_settings

engine = create_engine(get_settings().database_url, pool_pre_ping=True, pool_size=10, max_overflow=20)
SessionLocal = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)


class Base(DeclarativeBase):
    # Enumerations are VARCHAR + CHECK in the database, not native ENUM types.
    type_annotation_map = {
        enum.Enum: SAEnum(enum.Enum, native_enum=False, create_constraint=False, length=20),
    }


_AUDIT_SQL = text(
    "SELECT set_config('app.user_id', :user_id, true),"
    "       set_config('app.user_role', :user_role, true),"
    "       set_config('app.client_ip', :client_ip, true),"
    "       set_config('app.request_id', :request_id, true)"
)


def set_audit_context(
    session: Session,
    *,
    user_id: int | None,
    user_role: str | None,
    client_ip: str | None,
    request_id: str | None,
) -> None:
    """Remember who is acting; applied with SET LOCAL to every transaction of this session."""
    ctx = {
        "user_id": str(user_id or ""),
        "user_role": user_role or "",
        "client_ip": client_ip or "",
        "request_id": request_id or "",
    }
    session.info["audit"] = ctx
    if session.in_transaction():
        session.execute(_AUDIT_SQL, ctx)


@event.listens_for(Session, "after_begin")
def _apply_audit_context(session: Session, transaction, connection) -> None:
    ctx = session.info.get("audit")
    if ctx:
        connection.execute(_AUDIT_SQL, ctx)


def get_db() -> Iterator[Session]:
    db = SessionLocal()
    try:
        yield db
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()
