"""Engines, sessions and the per-transaction tenant context.

Every transaction of an app session starts with
    SET LOCAL app.school_id / app.user_id / app.platform_admin_id / app.client_ip / app.request_id
(set_config(..., true)), so PostgreSQL RLS and the audit trigger see who is acting for which school.
SET LOCAL is transaction-scoped, which keeps it safe with PgBouncer transaction pooling.
"""

import re
import uuid
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass
from functools import lru_cache

from sqlalchemy import event, text
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import NullPool

from app.core.config import get_settings

_ROLE_NAME = re.compile(r"^[a-z_][a-z0-9_]{0,62}$")


@dataclass(frozen=True)
class DbContext:
    school_id: uuid.UUID | None = None
    user_id: uuid.UUID | None = None
    platform_admin_id: uuid.UUID | None = None
    client_ip: str | None = None
    request_id: str | None = None

    def params(self) -> dict[str, str]:
        return {k: "" if v is None else str(v) for k, v in vars(self).items()}


_CONTEXT_SQL = text(
    "SELECT set_config('app.school_id', :school_id, true),"
    " set_config('app.user_id', :user_id, true),"
    " set_config('app.platform_admin_id', :platform_admin_id, true),"
    " set_config('app.client_ip', :client_ip, true),"
    " set_config('app.request_id', :request_id, true)"
)


@event.listens_for(Session, "after_begin")
def _apply_context(session: Session, transaction, connection) -> None:
    ctx: DbContext | None = session.info.get("ctx")
    if ctx is not None:
        connection.execute(_CONTEXT_SQL, ctx.params())


async def set_context(session: AsyncSession, ctx: DbContext) -> None:
    """Remember the context for later transactions and apply it to the current one.

    Pending changes are flushed first, so rows added under one school are written under that school's context
    (RLS WITH CHECK), not under the next one."""
    session.info["ctx"] = ctx
    if session.in_transaction():
        await session.flush()
        await session.execute(_CONTEXT_SQL, ctx.params())


def _make_engine(url: str, set_role: str | None) -> AsyncEngine:
    settings = get_settings()
    if _in_worker():
        engine = create_async_engine(url, poolclass=NullPool)
    else:
        engine = create_async_engine(
            url, pool_size=settings.db_pool_size, max_overflow=settings.db_pool_size, pool_pre_ping=True
        )
    if set_role:
        if not _ROLE_NAME.match(set_role):
            raise ValueError("invalid role name")

        @event.listens_for(engine.sync_engine, "connect")
        def _set_role(dbapi_connection, _record) -> None:
            cursor = dbapi_connection.cursor()
            cursor.execute(f"SET ROLE {set_role}")
            cursor.close()
            # psycopg ran SET ROLE inside an implicit transaction: commit it, or the next rollback (SQLAlchemy's own
            # after connecting, or any failed request) undoes it and leaves the connection without privileges.
            dbapi_connection.commit()

    return engine


_worker_mode = False


def use_worker_mode() -> None:
    """Celery workers run each task in a fresh event loop, so they must not reuse pooled connections."""
    global _worker_mode
    _worker_mode = True


def _in_worker() -> bool:
    return _worker_mode


@lru_cache
def get_engine() -> AsyncEngine:
    s = get_settings()
    return _make_engine(s.database_url, s.database_set_role)


@lru_cache
def get_platform_engine() -> AsyncEngine:
    s = get_settings()
    return _make_engine(s.platform_database_url, s.platform_database_set_role)


@lru_cache
def _app_sessions() -> async_sessionmaker[AsyncSession]:
    return async_sessionmaker(get_engine(), expire_on_commit=False, autoflush=False)


@lru_cache
def _platform_sessions() -> async_sessionmaker[AsyncSession]:
    return async_sessionmaker(get_platform_engine(), expire_on_commit=False, autoflush=False)


@asynccontextmanager
async def _session(factory) -> AsyncIterator[AsyncSession]:
    async with factory() as session:
        try:
            yield session
        except BaseException:
            await session.rollback()
            raise


class SessionProvider:
    """Indirection so tests can hand out sessions bound to a rolled-back test transaction."""

    def app(self):
        return _session(_app_sessions())

    def platform(self):
        return _session(_platform_sessions())


provider = SessionProvider()


async def get_session() -> AsyncIterator[AsyncSession]:
    async with provider.app() as session:
        yield session


async def get_platform_session() -> AsyncIterator[AsyncSession]:
    async with provider.platform() as session:
        yield session


@asynccontextmanager
async def school_session(
    school_id: uuid.UUID, user_id: uuid.UUID | None = None, request_id: str | None = None
) -> AsyncIterator[AsyncSession]:
    """Background work for one school (Celery tasks)."""
    async with provider.app() as session:
        await set_context(session, DbContext(school_id=school_id, user_id=user_id, request_id=request_id))
        yield session
