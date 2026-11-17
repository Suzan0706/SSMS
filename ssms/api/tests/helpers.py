"""Fixed ids from design/sql/seed.sql and small helpers shared by the tests."""

import uuid

from sqlalchemy import update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.crypto import get_cipher
from app.db.session import DbContext, set_context
from app.models import User
from app.services.sms import PHONE_FIELD

PASSWORD = "Mfano@2026"  # demo password of every seeded account


def u(table: int, n: int) -> uuid.UUID:
    """Same formula as pg_temp.u() in seed.sql."""
    return uuid.UUID(f"{table:08x}-0000-4000-8000-{n:012x}")


SCHOOL_A, SCHOOL_B = u(1, 1), u(1, 2)
ADMIN_A, BURSAR_A, TEACHER_A, ADMIN_B = u(2, 1), u(2, 2), u(2, 3), u(2, 101)
GUARDIAN_A, GUARDIAN_B = u(2, 21), u(2, 121)  # same phone 255754000021 in both schools
SHARED_PHONE = "255754000021"


async def login(
    client, school: str = "mfano-sec", username: str = "admin", password: str = PASSWORD, **headers
) -> dict:
    response = await client.post(
        "/api/v1/auth/login", json={"school_code": school, "username": username, "password": password}, headers=headers
    )
    assert response.status_code == 200, response.text
    return response.json()


def bearer(token_or_body) -> dict:
    token = token_or_body["access_token"] if isinstance(token_or_body, dict) else token_or_body
    return {"Authorization": f"Bearer {token}"}


async def as_school(db: AsyncSession, school_id: uuid.UUID, user_id: uuid.UUID | None = None) -> None:
    await set_context(db, DbContext(school_id=school_id, user_id=user_id))


async def rekey_phone(db: AsyncSession, school_id: uuid.UUID, user_id: uuid.UUID, phone: str) -> None:
    """Seed phones use an unkeyed stand-in hash; give a user the real encrypted phone and keyed blind index."""
    cipher = get_cipher()
    await as_school(db, school_id)
    await db.execute(
        update(User)
        .where(User.id == user_id)
        .values(
            phone_enc=cipher.encrypt(phone, PHONE_FIELD),
            phone_hash=cipher.blind_index(phone, PHONE_FIELD),
            phone_last4=phone[-4:],
        )
    )
    await db.commit()


# Academic seed (school A)
YEAR_2026, TERM1 = u(12, 1), u(13, 1)
O_LEVEL, A_LEVEL = u(11, 1), u(11, 2)
F1, F2, F5 = u(16, 1), u(16, 2), u(16, 5)
F1_A, F2_A, F2_B, F5_PCM = u(19, 1), u(19, 2), u(19, 3), u(19, 4)
PCM = u(17, 1)
BMATH, ENG, PHY, CHEM, BIO, GS, PHY_A, CHEM_A, AMATH = (u(15, n) for n in (9, 5, 6, 7, 8, 10, 11, 12, 13))
STAFF_MWITA, STAFF_SALMA, STAFF_KIMARO, STAFF_LAIZER = u(8, 3), u(8, 4), u(8, 5), u(8, 8)
ROOM_F2A, ROOM_LAB_PHY, ROOM_HALL, ROOM_F1A = u(18, 1), u(18, 4), u(18, 6), u(18, 7)


async def parent_login(client, db, dispatcher, school_id: uuid.UUID, user_id: uuid.UUID, phone: str) -> dict:
    """Sign a seeded guardian in through the real SMS-code flow; returns the Authorization header."""
    await rekey_phone(db, school_id, user_id, phone)
    assert (await client.post("/api/v1/auth/otp/request", json={"phone": phone})).status_code == 200
    text = dispatcher.take("sms.send")[-1]["text"]
    code = next(word.strip(".") for word in text.split() if word.strip(".").isdigit() and len(word.strip(".")) == 6)
    response = await client.post("/api/v1/auth/otp/verify", json={"phone": phone, "code": code})
    assert response.status_code == 200, response.text
    return bearer(response.json())
