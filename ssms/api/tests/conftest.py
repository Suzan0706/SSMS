"""Test harness on a real PostgreSQL 16.

* A superuser URL (SSMS_TEST_ADMIN_URL) is used ONLY to create the test database, run the migrations and load
  design/sql/seed.sql, exactly as operations would.
* The tests log in as ssms_tester (NOSUPERUSER, NOBYPASSRLS, NOINHERIT), a member of ssms_app and ssms_platform.
  Every app session starts with SET LOCAL ROLE ssms_app, so every test runs as ssms_app and exercises RLS;
  console sessions use SET LOCAL ROLE ssms_platform, as the production console login does.
* Each test runs inside one outer transaction that is rolled back; the app's commits become savepoints, so rows
  created through the console are visible to app sessions of the same test.
"""

import asyncio
import base64
import os
import sys
import tempfile
import warnings
from pathlib import Path

warnings.filterwarnings("ignore", category=DeprecationWarning)
if sys.platform == "win32":  # psycopg async needs the selector loop on Windows
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

ADMIN_URL = os.environ.get("SSMS_TEST_ADMIN_URL", "postgresql://postgres@localhost:55433/postgres")
TEST_DB = os.environ.get("SSMS_TEST_DB", "ssms_test")
_host_part = ADMIN_URL.split("://", 1)[1].split("@", 1)[1].rsplit("/", 1)[0]
TESTER_URL = os.environ.get("SSMS_TEST_TESTER_URL", f"postgresql+psycopg://ssms_tester@{_host_part}/{TEST_DB}")

os.environ.update(
    {
        "SSMS_ENVIRONMENT": "test",
        "SSMS_DATABASE_URL": TESTER_URL,
        "SSMS_DATABASE_SET_ROLE": "ssms_app",
        "SSMS_PLATFORM_DATABASE_URL": TESTER_URL,
        "SSMS_PLATFORM_DATABASE_SET_ROLE": "ssms_platform",
        "SSMS_MIGRATION_DATABASE_URL": ADMIN_URL.replace("postgresql://", "postgresql+psycopg://").rsplit("/", 1)[0]
        + f"/{TEST_DB}",
        "SSMS_ENC_KEYS": "1:" + base64.b64encode(os.urandom(32)).decode(),  # throw-away keys for this run
        "SSMS_BLIND_INDEX_KEY": base64.b64encode(os.urandom(32)).decode(),
        "SSMS_COOKIE_SECURE": "false",  # the test client speaks plain http
        "SSMS_SMS_PROVIDER": "console",
        "SSMS_STORAGE_DIR": tempfile.mkdtemp(prefix="ssms-test-storage-"),  # uploads and reports of this run
    }
)

import psycopg  # noqa: E402
import pytest  # noqa: E402
from httpx import ASGITransport, AsyncClient  # noqa: E402
from sqlalchemy import event, text  # noqa: E402
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine  # noqa: E402
from sqlalchemy.orm import Session  # noqa: E402
from sqlalchemy.pool import NullPool  # noqa: E402

API_DIR = Path(__file__).resolve().parents[1]
REPO = API_DIR.parents[1]
SEED = REPO / "design" / "sql" / "seed.sql"


def _prepare_database() -> None:
    with psycopg.connect(ADMIN_URL, autocommit=True) as admin:
        admin.execute(f'DROP DATABASE IF EXISTS "{TEST_DB}" WITH (FORCE)')
        admin.execute(f'CREATE DATABASE "{TEST_DB}"')
    from alembic import command
    from alembic.config import Config

    config = Config(str(API_DIR / "alembic.ini"))
    config.set_main_option("script_location", str(API_DIR / "migrations"))
    command.upgrade(config, "head")
    with psycopg.connect(ADMIN_URL.rsplit("/", 1)[0] + f"/{TEST_DB}", autocommit=True) as db:
        db.execute(SEED.read_text(encoding="utf-8"))
        # Test login: no privileges of its own; it must SET ROLE to ssms_app or ssms_platform.
        db.execute("""DO $$ BEGIN
            IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'ssms_tester') THEN
                CREATE ROLE ssms_tester LOGIN NOINHERIT NOSUPERUSER NOBYPASSRLS NOCREATEDB NOCREATEROLE;
            END IF; END $$""")
        db.execute("GRANT ssms_app, ssms_platform TO ssms_tester")


@event.listens_for(Session, "after_begin")
def _test_role(session, transaction, connection) -> None:
    """Re-applied at every (savepoint) begin, so a rolled-back savepoint cannot leave another role active."""
    role = session.info.get("role")
    if role:
        connection.execute(text(f"SET LOCAL ROLE {role}"))


@pytest.fixture(scope="session")
def database():
    _prepare_database()
    yield


@pytest.fixture(scope="session")
async def engine(database):
    eng = create_async_engine(TESTER_URL, poolclass=NullPool)
    yield eng
    await eng.dispose()


@pytest.fixture
async def connection(engine, monkeypatch):
    """One rolled-back transaction per test; every app session joins it through a savepoint."""
    from contextlib import asynccontextmanager

    from app.db import session as db_session

    async with engine.connect() as conn:
        outer = await conn.begin()

        await conn.execute(text("SET LOCAL ROLE ssms_app"))

        def joined(role: str):
            @asynccontextmanager
            async def factory():
                session = AsyncSession(
                    bind=conn,
                    join_transaction_mode="create_savepoint",
                    expire_on_commit=False,
                    autoflush=False,
                    info={"role": role},
                )
                try:
                    await db_session.set_context(session, db_session.DbContext())  # no tenant until set
                    yield session
                finally:
                    await session.close()

            return factory

        monkeypatch.setattr(db_session.provider, "app", joined("ssms_app"))
        monkeypatch.setattr(db_session.provider, "platform", joined("ssms_platform"))
        yield conn
        await outer.rollback()


@pytest.fixture
async def db(connection):
    """A session in the test transaction, for arranging data and checking results (as ssms_app)."""
    from app.db.session import provider

    async with provider.app() as session:
        yield session


@pytest.fixture
def dispatcher(monkeypatch):
    from app.tasks import dispatch

    recorder = dispatch.RecordingDispatcher()
    monkeypatch.setattr(dispatch, "_dispatcher", recorder)
    return recorder


@pytest.fixture(autouse=True)
def _reset_rate_limits():
    from app.core.ratelimit import get_limiter

    get_limiter().reset()


@pytest.fixture
async def client(connection, dispatcher):
    from app.main import app

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        yield c
