"""Phase 13 deployment features: virus scanning of uploads (clamd INSTREAM) and S3-compatible file storage.

A small clamd stand-in speaks the real INSTREAM framing, so the client's bytes are checked, not mocked away. The live
S3 test runs whenever SSMS_TEST_S3_URL is set (CI starts MinIO for it; locally: a MinIO container).
"""

import asyncio
import contextlib
import io
import os
import struct
import uuid
import zipfile

import pytest
from sqlalchemy import func, select

from app.core import scanner
from app.core.config import get_settings
from app.core.storage import S3Storage
from app.models import StoredFile
from tests.helpers import SCHOOL_A, as_school, bearer, login

API = "/api/v1"
PNG = b"\x89PNG\r\n\x1a\n" + b"0" * 200
# The standard antivirus test string (harmless by design); clamd reports it as Eicar-Test-Signature.
EICAR = rb"X5O!P%@AP[4\PZX54(P^)7CC)7}$EICAR-STANDARD-ANTIVIRUS-TEST-FILE!$H+H*"


async def _fake_clamd(reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
    assert await reader.readexactly(10) == b"zINSTREAM\0"
    body = b""
    while size := struct.unpack(">I", await reader.readexactly(4))[0]:
        body += await reader.readexactly(size)
    writer.write(b"stream: Eicar-Test-Signature FOUND\0" if b"EICAR-STANDARD" in body else b"stream: OK\0")
    await writer.drain()
    writer.close()


@pytest.fixture
async def clamd(monkeypatch):
    server = await asyncio.start_server(_fake_clamd, "127.0.0.1", 0)
    port = server.sockets[0].getsockname()[1]
    monkeypatch.setattr(get_settings(), "clamav_address", f"127.0.0.1:{port}")
    yield port
    server.close()
    await server.wait_closed()


def _docx(payload: bytes) -> bytes:
    out = io.BytesIO()
    with zipfile.ZipFile(out, "w", zipfile.ZIP_STORED) as archive:
        archive.writestr("[Content_Types].xml", "<Types/>")
        archive.writestr("word/document.xml", "<document/>")
        archive.writestr("eicar.com", payload)
    return out.getvalue()


async def test_clean_uploads_are_marked_and_infected_ones_never_stored(client, db, clamd):
    admin = bearer(await login(client))
    teacher = bearer(await login(client, username="tch.mwita"))  # materials.publish
    clean = await client.post(f"{API}/files", headers=admin, data={"purpose": "PHOTO"}, files={"file": ("a.png", PNG)})
    assert clean.status_code == 201, clean.text

    await as_school(db, SCHOOL_A)
    before = (await db.execute(select(func.count()).select_from(StoredFile))).scalar()
    # a valid study material (a Word document) carrying the EICAR file, as the real scanner sees it (install drill)
    infected = await client.post(
        f"{API}/files", headers=teacher, data={"purpose": "STUDY_MATERIAL"}, files={"file": ("somo.docx", _docx(EICAR))}
    )
    assert infected.status_code == 422 and infected.json()["error_code"] == "FILE_INFECTED"
    assert (await db.execute(select(func.count()).select_from(StoredFile))).scalar() == before
    status = (
        await db.execute(select(StoredFile.scan_status).where(StoredFile.id == uuid.UUID(clean.json()["id"])))
    ).scalar()
    assert status == "CLEAN"


async def test_uploads_wait_while_the_scanner_is_down(client, monkeypatch):
    monkeypatch.setattr(get_settings(), "clamav_address", "127.0.0.1:1")  # nothing listens there
    admin = bearer(await login(client))
    down = await client.post(f"{API}/files", headers=admin, data={"purpose": "PHOTO"}, files={"file": ("a.png", PNG)})
    assert down.status_code == 503 and down.json()["error_code"] == "SCANNER_UNAVAILABLE"


async def test_a_clamd_error_is_not_taken_as_clean(monkeypatch):
    async def limit_exceeded(reader, writer):
        await reader.read(64)
        writer.write(b"INSTREAM size limit exceeded. ERROR\0")
        await writer.drain()
        writer.close()

    server = await asyncio.start_server(limit_exceeded, "127.0.0.1", 0)
    monkeypatch.setattr(get_settings(), "clamav_address", f"127.0.0.1:{server.sockets[0].getsockname()[1]}")
    try:
        with pytest.raises(scanner.ScannerUnavailable):
            await scanner.scan(b"x" * 10)
    finally:
        server.close()
        await server.wait_closed()


class _Missing(Exception):
    pass


class _FakeS3:
    """Just enough of a boto3 client to check how S3Storage maps answers."""

    class exceptions:
        NoSuchKey = _Missing

    def __init__(self):
        self.objects: dict[str, bytes] = {}

    def put_object(self, Bucket, Key, Body):
        self.objects[Key] = Body

    def get_object(self, Bucket, Key):
        if Key not in self.objects:
            raise _Missing()
        return {"Body": type("B", (), {"read": lambda _self, data=self.objects[Key]: data})()}

    def head_object(self, Bucket, Key):
        from botocore.exceptions import ClientError

        if Key not in self.objects:
            raise ClientError({"Error": {"Code": "404"}}, "HeadObject")

    def delete_object(self, Bucket, Key):
        self.objects.pop(Key, None)


def _contract(storage) -> None:
    key = f"school/files/{uuid.uuid4().hex}.png"
    assert not storage.exists(key)
    storage.put(key, PNG)
    assert storage.exists(key) and storage.get(key) == PNG
    storage.delete(key)
    assert not storage.exists(key)
    with pytest.raises(FileNotFoundError):
        storage.get(key)
    for bad in ("../etc/passwd", "/abs", "a//b", "a/../b"):
        with pytest.raises(ValueError):
            storage.put(bad, b"x")


def test_s3_storage_behaves_like_local_storage():
    _contract(S3Storage("bucket", _FakeS3()))


@pytest.mark.skipif(not os.environ.get("SSMS_TEST_S3_URL"), reason="set SSMS_TEST_S3_URL (and keys) to test real S3")
def test_s3_storage_against_a_real_object_store(monkeypatch):

    settings = get_settings()
    for name, value in {
        "s3_endpoint_url": os.environ["SSMS_TEST_S3_URL"],
        "s3_bucket": os.environ.get("SSMS_TEST_S3_BUCKET", "ssms-test"),
        "s3_access_key": os.environ.get("SSMS_TEST_S3_ACCESS_KEY", "minioadmin"),
        "s3_secret_key": os.environ.get("SSMS_TEST_S3_SECRET_KEY", "minioadmin"),
    }.items():
        monkeypatch.setattr(settings, name, value)
    storage = S3Storage.from_settings()
    with contextlib.suppress(
        storage.client.exceptions.BucketAlreadyOwnedByYou, storage.client.exceptions.BucketAlreadyExists
    ):
        storage.client.create_bucket(Bucket=settings.s3_bucket)
    _contract(storage)


def test_production_needs_a_scanner_or_an_explicit_opt_out(monkeypatch):
    from app.core import config

    monkeypatch.setenv("SSMS_ENVIRONMENT", "production")
    monkeypatch.setenv("SSMS_STORAGE_BACKEND", "s3")
    for name in ("SSMS_CLAMAV_ADDRESS", "SSMS_ALLOW_UNSCANNED_UPLOADS", "SSMS_S3_BUCKET"):
        monkeypatch.delenv(name, raising=False)
    config.get_settings.cache_clear()
    try:
        with pytest.raises(RuntimeError) as refused:
            config.get_settings()
        assert "SSMS_CLAMAV_ADDRESS" in str(refused.value) and "SSMS_S3_BUCKET" in str(refused.value)
        monkeypatch.setenv("SSMS_ALLOW_UNSCANNED_UPLOADS", "true")
        config.get_settings.cache_clear()
        with pytest.raises(RuntimeError) as still:
            config.get_settings()
        assert "SSMS_CLAMAV_ADDRESS" not in str(still.value)
    finally:
        config.get_settings.cache_clear()


async def test_the_runtime_role_survives_a_rolled_back_request(connection):
    """The console login has no privileges of its own; the engine switches it to ssms_platform on connect. That switch
    must outlive a request that fails and rolls back, or the pooled connection is left powerless (Phase 13 drill)."""
    from sqlalchemy import text

    from app.db.session import _make_engine
    from tests.conftest import TESTER_URL

    engine = _make_engine(TESTER_URL, "ssms_platform")
    try:
        async with engine.connect() as conn:  # first use of the connection ends in a rollback, like a failed sign-in
            assert (await conn.execute(text("SELECT current_user"))).scalar() == "ssms_platform"
            await conn.rollback()
        async with engine.connect() as conn:  # the same pooled connection, next request
            assert (await conn.execute(text("SELECT current_user"))).scalar() == "ssms_platform"
            assert (await conn.execute(text("SELECT count(*) FROM platform_admins"))).scalar() >= 1
    finally:
        await engine.dispose()


SMTP_STARTTLS = os.environ.get("SSMS_TEST_SMTP_STARTTLS")  # host:port of a server requiring STARTTLS
SMTP_TLS = os.environ.get("SSMS_TEST_SMTP_TLS")  # host:port of a server with implicit TLS
SMTP_API = os.environ.get("SSMS_TEST_SMTP_API")  # Mailpit HTTP API of the STARTTLS server
SMTP_CA = os.environ.get("SSMS_TEST_SMTP_CA")  # the servers' certificate (self-signed for the test)
live_smtp = pytest.mark.skipif(
    not (SMTP_STARTTLS and SMTP_TLS and SMTP_API and SMTP_CA), reason="set SSMS_TEST_SMTP_* to test a real SMTP server"
)


def _smtp(monkeypatch, address: str, **more) -> None:
    host, _, port = address.rpartition(":")
    values = {
        "smtp_host": host,
        "smtp_port": int(port),
        "smtp_user": "ssms",
        "smtp_password": "app-password",
        "smtp_ca_file": SMTP_CA,
        "smtp_starttls": True,
        "smtp_implicit_tls": False,
        "email_from": "ssms@mfano.sc.tz",
    }
    for name, value in {**values, **more}.items():
        monkeypatch.setattr(get_settings(), name, value)


@live_smtp
def test_smtp_starttls_and_implicit_tls_with_a_verified_certificate(monkeypatch):
    import httpx

    from app.services.email import SmtpProvider

    _smtp(monkeypatch, SMTP_STARTTLS)
    subject = f"SSMS test {uuid.uuid4().hex[:8]}"
    message_id = SmtpProvider().send("mzazi@example.org", subject, "Habari.", "Shule <ssms@mfano.sc.tz>")
    assert message_id.startswith("<") and message_id.endswith("@mfano.sc.tz>")
    found = httpx.get(f"{SMTP_API}/api/v1/search", params={"query": f'subject:"{subject}"'}).json()["messages"]
    assert len(found) == 1 and found[0]["To"][0]["Address"] == "mzazi@example.org"
    headers = httpx.get(f"{SMTP_API}/api/v1/message/{found[0]['ID']}/headers").json()
    assert headers["Date"] and headers["Message-Id"][0] == message_id

    _smtp(monkeypatch, SMTP_TLS, smtp_implicit_tls=True, smtp_starttls=False)
    assert SmtpProvider().send("mzazi@example.org", "implicit TLS", "Habari.", "ssms@mfano.sc.tz")


@live_smtp
def test_smtp_refuses_an_untrusted_certificate_and_a_password_without_tls(monkeypatch):
    import smtplib
    import ssl

    from app.services.email import SmtpProvider

    _smtp(monkeypatch, SMTP_STARTTLS, smtp_ca_file="")  # the self-signed certificate is not in the system store
    with pytest.raises(ssl.SSLCertVerificationError):
        SmtpProvider().send("mzazi@example.org", "x", "x", "ssms@mfano.sc.tz")
    _smtp(monkeypatch, SMTP_STARTTLS, smtp_starttls=False)
    with pytest.raises(smtplib.SMTPException, match="without TLS"):
        SmtpProvider().send("mzazi@example.org", "x", "x", "ssms@mfano.sc.tz")


@live_smtp
async def test_a_queued_email_is_delivered_through_smtp(client, monkeypatch, dispatcher):
    from app.tasks.handlers import email_send

    _smtp(monkeypatch, SMTP_STARTTLS)
    monkeypatch.setattr(get_settings(), "email_provider", "smtp")
    admin = bearer(await login(client))
    assert (await client.post(f"{API}/email-messages/test", headers=admin)).status_code == 200
    assert await email_send(**dispatcher.take("email.send")[-1]) == "SENT"
    sent = (await client.get(f"{API}/email-messages", headers=admin)).json()[0]
    assert sent["status"] == "SENT" and sent["error"] is None


async def test_passwords_are_checked_off_the_event_loop(client, monkeypatch):
    """Argon2 takes about 0.4 s: on the event loop it would stall every other request of the worker (Phase 13)."""
    import threading

    from app.core import security

    loop_thread, seen = threading.current_thread(), []
    real = security.verify_password

    def recording(raw, hashed):
        seen.append(threading.current_thread() is loop_thread)
        return real(raw, hashed)

    monkeypatch.setattr(security, "verify_password", recording)
    await login(client)
    assert seen == [False]
