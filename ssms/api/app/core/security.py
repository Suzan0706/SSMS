"""Passwords (Argon2id), JWTs and opaque tokens."""

import asyncio
import hashlib
import hmac
import re
import secrets
import uuid
from datetime import UTC, datetime, timedelta

import jwt
from pwdlib import PasswordHash

from app.core.config import get_settings

_hasher = PasswordHash.recommended()  # Argon2id m=64 MiB, t=3, p=4
DUMMY_HASH = _hasher.hash("timing-equaliser-not-a-real-password")
_PASSWORD_RULE = re.compile(r"^(?=.*[A-Za-z])(?=.*\d).{10,128}$")

APP_AUDIENCE = "ssms-app"
PLATFORM_AUDIENCE = "ssms-platform"


def hash_password(raw: str) -> str:
    return _hasher.hash(raw)


def verify_password(raw: str, hashed: str | None) -> tuple[bool, str | None]:
    """(valid, new_hash). Without a stored hash we still verify against DUMMY_HASH so timing is the same."""
    if not hashed:
        _hasher.verify(raw, DUMMY_HASH)
        return False, None
    return _hasher.verify_and_update(raw, hashed)


# Argon2 takes about 0.4 s of CPU and the library releases the interpreter lock while it works: in a thread, other
# requests on the same worker keep moving (inline, a burst of six sign-ins stalled everything for 1.5 s; Phase 13).
async def hash_password_async(raw: str) -> str:
    return await asyncio.to_thread(hash_password, raw)


async def verify_password_async(raw: str, hashed: str | None) -> tuple[bool, str | None]:
    return await asyncio.to_thread(verify_password, raw, hashed)


def is_strong_password(raw: str) -> bool:
    return bool(_PASSWORD_RULE.match(raw))


def temporary_password() -> str:
    alphabet = "abcdefghjkmnpqrstuvwxyzABCDEFGHJKLMNPQRSTUVWXYZ"
    return "".join(secrets.choice(alphabet) for _ in range(7)) + "".join(secrets.choice("23456789") for _ in range(4))


def sha256_hex(value: str | bytes) -> str:
    return hashlib.sha256(value.encode() if isinstance(value, str) else value).hexdigest()


def new_opaque_token() -> tuple[str, str]:
    raw = secrets.token_urlsafe(48)
    return raw, sha256_hex(raw)


def new_otp_code() -> str:
    return f"{secrets.randbelow(1_000_000):06d}"


def otp_hash(code: str, user_id: uuid.UUID) -> str:
    """Keyed, so a leaked otp_codes table cannot be brute-forced offline (only 10^6 codes)."""
    return hmac.new(get_settings().jwt_secret.encode(), f"otp:{code}:{user_id}".encode(), hashlib.sha256).hexdigest()


def _encode(claims: dict, minutes: int, audience: str) -> str:
    now = datetime.now(UTC)
    payload = {**claims, "aud": audience, "iat": now, "exp": now + timedelta(minutes=minutes), "jti": uuid.uuid4().hex}
    return jwt.encode(payload, get_settings().jwt_secret, algorithm="HS256")


def create_access_token(user_id: uuid.UUID, school_id: uuid.UUID, roles: list[str]) -> str:
    return _encode(
        {"sub": str(user_id), "sch": str(school_id), "roles": roles, "typ": "access"},
        get_settings().access_token_minutes,
        APP_AUDIENCE,
    )


def create_selection_token(choices: list[tuple[uuid.UUID, uuid.UUID]]) -> str:
    """Short-lived token listing (school_id, user_id) pairs a verified parent may choose from."""
    return _encode(
        {"typ": "select", "choices": [[str(s), str(u)] for s, u in choices]},
        get_settings().selection_token_minutes,
        APP_AUDIENCE,
    )


def create_platform_token(admin_id: uuid.UUID) -> str:
    return _encode({"sub": str(admin_id), "typ": "platform"}, get_settings().access_token_minutes, PLATFORM_AUDIENCE)


def decode_token(token: str, expected_type: str, audience: str = APP_AUDIENCE) -> dict:
    payload = jwt.decode(
        token,
        get_settings().jwt_secret,
        algorithms=["HS256"],
        audience=audience,
        options={"require": ["exp", "typ", "aud"]},
    )
    if payload.get("typ") != expected_type:
        raise jwt.InvalidTokenError("wrong token type")
    return payload
