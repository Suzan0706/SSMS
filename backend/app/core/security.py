"""Password hashing (Argon2id), JWT access tokens and opaque refresh tokens."""
import hashlib
import re
import secrets
import uuid
from datetime import UTC, datetime, timedelta

import jwt
from pwdlib import PasswordHash

from app.core.config import get_settings

# Argon2id with pwdlib's recommended parameters (m=64 MiB, t=3, p=4).
_hasher = PasswordHash.recommended()

# Used when the username does not exist, so a failed login takes the same time
# whether or not the account exists (no user enumeration by timing).
DUMMY_HASH = _hasher.hash("timing-equaliser-not-a-real-password")

PASSWORD_RULE = re.compile(r"^(?=.*[A-Za-z])(?=.*\d).{10,128}$")


def hash_password(raw: str) -> str:
    return _hasher.hash(raw)


def verify_password(raw: str, hashed: str) -> tuple[bool, str | None]:
    """Return (valid, new_hash). new_hash is set when the stored hash uses old parameters."""
    return _hasher.verify_and_update(raw, hashed)


def is_strong_password(raw: str) -> bool:
    return bool(PASSWORD_RULE.match(raw))


def generate_temporary_password() -> str:
    # 12 characters, always contains a letter and a digit
    return secrets.token_urlsafe(9)[:10] + str(secrets.randbelow(10)) + "a"


def create_access_token(user_id: int, role: str) -> str:
    settings = get_settings()
    now = datetime.now(UTC)
    payload = {
        "sub": str(user_id),
        "role": role,
        "typ": "access",
        "iat": now,
        "exp": now + timedelta(minutes=settings.access_token_minutes),
        "jti": uuid.uuid4().hex,
    }
    return jwt.encode(payload, settings.jwt_secret, algorithm=settings.jwt_algorithm)


def decode_access_token(token: str) -> dict:
    settings = get_settings()
    payload = jwt.decode(
        token,
        settings.jwt_secret,
        algorithms=[settings.jwt_algorithm],
        options={"require": ["exp", "sub", "typ"]},
    )
    if payload.get("typ") != "access":
        raise jwt.InvalidTokenError("not an access token")
    return payload


def sha256_hex(value: str | bytes) -> str:
    data = value.encode() if isinstance(value, str) else value
    return hashlib.sha256(data).hexdigest()


def new_refresh_token() -> tuple[str, str]:
    """Return (token for the client, SHA-256 hash for the database)."""
    raw = secrets.token_urlsafe(48)
    return raw, sha256_hex(raw)
