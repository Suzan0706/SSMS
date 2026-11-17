"""Tests run against a real PostgreSQL 16+ database (TEST_DATABASE_URL); the schema and seed are
loaded once, and every test runs inside a transaction that is rolled back afterwards."""
import os
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

os.environ.setdefault("SMS_SMS_PROVIDER", "console")
os.environ.setdefault("SMS_GEPG_ENABLED", "false")

from app.db import get_db  # noqa: E402
from app.deps import get_storage  # noqa: E402
from app.main import app  # noqa: E402
from app.services.storage import LocalStorage  # noqa: E402
from app.tasks.celery_app import celery_app  # noqa: E402

TEST_DB = os.environ.get("TEST_DATABASE_URL", "postgresql+psycopg://postgres:postgres@localhost:5432/sms_test")
ROOT = Path(__file__).resolve().parents[2]
PASSWORD = "Mfano@2026"            # every seeded account

celery_app.conf.task_always_eager = True   # Celery tasks run inline; SMS provider is "console"


@pytest.fixture(scope="session")
def connection():
    engine = create_engine(TEST_DB)
    with engine.connect() as conn:
        raw = conn.connection.dbapi_connection
        with raw.cursor() as cur:
            cur.execute("DROP SCHEMA IF EXISTS public CASCADE; CREATE SCHEMA public;")
            cur.execute((ROOT / "db" / "schema.sql").read_text(encoding="utf-8"))
            cur.execute((ROOT / "db" / "seed.sql").read_text(encoding="utf-8"))
        raw.commit()
        yield conn
    engine.dispose()


@pytest.fixture
def db(connection):
    outer = connection.begin()
    session = Session(bind=connection, join_transaction_mode="create_savepoint",
                      autoflush=False, expire_on_commit=False)
    yield session
    session.close()
    outer.rollback()


@pytest.fixture
def client(db, tmp_path):
    def override_db():
        try:
            yield db
        except Exception:
            db.rollback()
            raise

    app.dependency_overrides[get_db] = override_db
    app.dependency_overrides[get_storage] = lambda: LocalStorage(tmp_path)
    with TestClient(app) as c:
        yield c
    app.dependency_overrides.clear()


def login(client: TestClient, username: str, password: str = PASSWORD) -> dict:
    r = client.post("/api/v1/auth/login", data={"username": username, "password": password})
    assert r.status_code == 200, r.text
    return {"Authorization": f"Bearer {r.json()['access_token']}"}


@pytest.fixture
def as_admin(client):
    return login(client, "admin")


@pytest.fixture
def as_registrar(client):
    return login(client, "registrar")


@pytest.fixture
def as_bursar(client):
    return login(client, "bursar")
