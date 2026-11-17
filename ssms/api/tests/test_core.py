"""Unit tests for the core building blocks (no HTTP)."""

import base64
import os
import time
import uuid
from datetime import date

import jwt
import pytest
from cryptography.exceptions import InvalidTag

from app.core import security
from app.core.crypto import CryptoNotConfigured, FieldCipher
from app.core.errors import AppError
from app.core.i18n import message, pick_language
from app.core.ids import uuid7
from app.core.pagination import _decode, encode_cursor
from app.core.phone import mask_phone, normalise_phone
from app.core.ratelimit import MemoryLimiter, enforce, get_limiter
from app.core.storage import LocalStorage
from app.models import School
from app.services.onboarding import default_terms
from app.services.sms import segments


def test_uuid7_is_version_7_and_time_ordered():
    first = uuid7()
    time.sleep(0.002)
    second = uuid7()
    assert first.version == 7 and second.version == 7 and first < second
    assert first.variant == uuid.RFC_4122


@pytest.mark.parametrize(
    "raw, expected",
    [
        ("0754 123 456", "255754123456"),
        ("+255-754-123-456", "255754123456"),
        ("255754123456", "255754123456"),
        ("754123456", "255754123456"),
        ("0222123456", "255222123456"),
    ],
)
def test_phone_normalisation(raw, expected):
    assert normalise_phone(raw) == expected


@pytest.mark.parametrize("raw", ["12345", "0154123456", "25575412345", "+1 202 555 0100", ""])
def test_phone_rejects_bad_numbers(raw):
    with pytest.raises(ValueError):
        normalise_phone(raw)


def test_mask_phone():
    assert mask_phone("0021") == "****0021" and mask_phone(None) is None


def test_field_cipher_round_trip_rotation_and_binding():
    old, new = os.urandom(32), os.urandom(32)
    blind = os.urandom(32)
    v1 = FieldCipher({1: old}, 1, blind)
    blob = v1.encrypt("255754000021", "users.phone")
    v2 = FieldCipher({1: old, 2: new}, 2, blind)
    assert v2.decrypt(blob, "users.phone") == "255754000021"  # old key still readable
    assert v2.needs_rotation(blob) and not v2.needs_rotation(v2.encrypt("x", "f"))
    with pytest.raises(InvalidTag):
        v2.decrypt(blob, "students.nida")  # ciphertext bound to its field
    assert v1.blind_index("x", "a") == v2.blind_index("x", "a") != v2.blind_index("x", "b")
    with pytest.raises(CryptoNotConfigured):
        FieldCipher({}, 1, blind).encrypt("x", "f")
    with pytest.raises(CryptoNotConfigured):
        FieldCipher({1: old}, 1, b"").blind_index("x", "f")
    with pytest.raises(ValueError):
        v2.decrypt(b"\x09garbage", "users.phone")


def test_tokens_are_typed_and_audience_bound():
    user, school = uuid.uuid4(), uuid.uuid4()
    access = security.create_access_token(user, school, ["teacher"])
    assert security.decode_token(access, "access")["sch"] == str(school)
    with pytest.raises(jwt.InvalidTokenError):
        security.decode_token(access, "select")
    platform = security.create_platform_token(user)
    with pytest.raises(jwt.InvalidAudienceError):
        security.decode_token(platform, "platform")  # wrong audience
    assert security.decode_token(platform, "platform", security.PLATFORM_AUDIENCE)["sub"] == str(user)


def test_passwords_and_otp_hash():
    hashed = security.hash_password("Kilimanjaro2026")
    assert hashed.startswith("$argon2id$")
    assert security.verify_password("Kilimanjaro2026", hashed)[0]
    assert security.verify_password("wrong", hashed) == (False, None)
    assert security.verify_password("x", None) == (False, None)
    assert security.is_strong_password("abcdefghij1") and not security.is_strong_password("abcdefghij")
    temp = security.temporary_password()
    assert len(temp) == 11 and security.is_strong_password(temp)
    user = uuid.uuid4()
    assert security.otp_hash("123456", user) != security.otp_hash("123456", uuid.uuid4())
    assert len(security.new_otp_code()) == 6


def test_cursor_round_trip_and_tampering():
    keys = [School.code, School.id]
    school_id = uuid.uuid4()
    assert _decode(encode_cursor(["mfano", school_id]), keys) == ["mfano", school_id]
    for bad in ("x", encode_cursor(["only-one"]), base64.urlsafe_b64encode(b"{}").decode()):
        with pytest.raises(AppError):
            _decode(bad, keys)


async def test_rate_limiter_window():
    limiter = MemoryLimiter()
    assert [await limiter.hit("k", 60) for _ in range(3)] == [1, 2, 3]
    assert await limiter.hit("k", 0) == 1  # window over: counting restarts
    get_limiter().reset()
    await enforce("unit", 1, 60)
    with pytest.raises(AppError) as raised:
        await enforce("unit", 1, 60)
    assert raised.value.status_code == 429 and raised.value.headers["Retry-After"] == "60"


def test_i18n():
    assert pick_language(None) == "sw" and pick_language("en-GB,en;q=0.9") == "en" and pick_language("fr") == "sw"
    assert message("RATE_LIMITED", "en", minutes=5).endswith("5 minutes.")
    assert message("NO_SUCH_CODE", "en") == message("INTERNAL_ERROR", "en")
    assert "{until}" in message("ACCOUNT_LOCKED", "en")  # missing parameter: text kept


def test_sms_segments():
    assert segments("a" * 160) == 1 and segments("a" * 161) == 2
    assert segments("’" * 70) == 1 and segments("’" * 71) == 2  # non-GSM character: UCS-2


def test_default_terms_fall_on_school_days():
    (n1, *_, start1, end1), (n2, *_, start2, end2) = default_terms(2027)
    assert (n1, n2) == (1, 2)
    assert start1.weekday() == 0 and start2.weekday() == 0 and end1.weekday() == 4 and end2.weekday() == 4
    assert date(2027, 1, 8) <= start1 < end1 < start2 < end2 <= date(2027, 12, 31)


def test_local_storage_rejects_unsafe_keys(tmp_path):
    storage = LocalStorage(str(tmp_path))
    storage.put("school/imports/a.csv", b"x")
    assert storage.get("school/imports/a.csv") == b"x" and storage.exists("school/imports/a.csv")
    for key in ("../etc/passwd", "/abs", "a//b", "a/../b"):
        with pytest.raises(ValueError):
            storage.put(key, b"x")


async def test_request_id_is_echoed_and_security_headers_set(client):
    response = await client.get("/health/live", headers={"X-Request-ID": "abc12345-req"})
    assert response.headers["x-request-id"] == "abc12345-req"
    assert response.headers["x-frame-options"] == "DENY" and response.headers["x-content-type-options"] == "nosniff"
    generated = await client.get("/health/live", headers={"X-Request-ID": "<script>"})
    assert generated.headers["x-request-id"] != "<script>"


async def test_readiness_checks_the_database(client):
    assert (await client.get("/health/ready")).json() == {"status": "ok"}


async def test_unhandled_errors_use_the_error_format_without_leaking():
    from fastapi import FastAPI
    from httpx import ASGITransport, AsyncClient

    from app.core.errors import register_error_handlers
    from app.core.middleware import RequestContextMiddleware

    app = FastAPI()
    register_error_handlers(app)
    app.add_middleware(RequestContextMiddleware)

    @app.get("/boom")
    async def boom():
        raise RuntimeError("secret detail")

    async with AsyncClient(transport=ASGITransport(app=app, raise_app_exceptions=False), base_url="http://t") as c:
        response = await c.get("/boom", headers={"Accept-Language": "en"})
    assert response.status_code == 500
    assert response.json()["error_code"] == "INTERNAL_ERROR" and "secret" not in response.text
