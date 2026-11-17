"""Library copies stay connected to books and loans (migration 0020)."""

import uuid

import pytest
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError

from tests.helpers import SCHOOL_A, as_school, bearer, login, u

API = "/api/v1"
GATE_JUMA = u(2, 6)
AMANI_USER = u(2, 11)
SEED_LOAN_BOOK = u(52, 1)


@pytest.fixture
async def librarian(client) -> dict:
    admin = bearer(await login(client))
    added = await client.post(f"{API}/users/{GATE_JUMA}/roles", headers=admin, json={"role_code": "librarian"})
    assert added.status_code == 201, added.text
    return bearer(await login(client, username="gate.juma"))


async def _copies(db, book_id) -> list[tuple[str, str]]:
    await as_school(db, SCHOOL_A)
    rows = await db.execute(
        text("SELECT accession_no, status FROM library_copies WHERE book_id = :b ORDER BY accession_no"),
        {"b": book_id},
    )
    return [tuple(r) for r in rows]


async def test_seeded_books_and_loans_have_copies(db):
    copies = await _copies(db, SEED_LOAN_BOOK)
    assert len(copies) == 3 and all(s == "AVAILABLE" for _, s in copies)
    unlinked = await db.execute(text("SELECT count(*) FROM library_loans WHERE copy_id IS NULL"))
    assert unlinked.scalar() == 0


async def test_copies_follow_the_book_and_loans_take_a_free_copy(client, librarian, db):
    book = (
        await client.post(f"{API}/library/books", headers=librarian, json={"title": "Kusadikika", "copies": 2})
    ).json()
    assert [s for _, s in await _copies(db, book["id"])] == ["AVAILABLE", "AVAILABLE"]

    lent = await client.post(
        f"{API}/library/loans", headers=librarian, json={"book_id": book["id"], "borrower_user_id": str(AMANI_USER)}
    )
    assert lent.status_code == 201, lent.text
    copy = await db.execute(text("SELECT copy_id FROM library_loans WHERE id = :l"), {"l": lent.json()["id"]})
    first = copy.scalar()
    assert first is not None

    second = await client.post(
        f"{API}/library/loans", headers=librarian, json={"book_id": book["id"], "borrower_user_id": str(GATE_JUMA)}
    )
    assert second.status_code == 201, second.text
    other = await db.execute(text("SELECT copy_id FROM library_loans WHERE id = :l"), {"l": second.json()["id"]})
    assert other.scalar() not in (None, first)  # a copy is lent to one person at a time

    more = await client.patch(f"{API}/library/books/{book['id']}", headers=librarian, json={"copies": 3})
    assert more.status_code == 200, more.text
    assert len(await _copies(db, book["id"])) == 3

    returned = await client.post(f"{API}/library/loans/{lent.json()['id']}/return", headers=librarian)
    assert returned.status_code == 200, returned.text
    fewer = await client.patch(f"{API}/library/books/{book['id']}", headers=librarian, json={"copies": 1})
    assert fewer.status_code == 200, fewer.text
    statuses = [s for _, s in await _copies(db, book["id"])]
    assert len(statuses) == 3 and statuses.count("WITHDRAWN") == 2  # kept for history, never deleted


async def test_a_loan_cannot_name_a_copy_of_another_book(db):
    await as_school(db, SCHOOL_A)
    other_copy = (
        await db.execute(text("SELECT id FROM library_copies WHERE book_id <> :b LIMIT 1"), {"b": SEED_LOAN_BOOK})
    ).scalar()
    if other_copy is None:
        book = uuid.uuid4()
        await db.execute(
            text("INSERT INTO library_books (id, school_id, title, copies) VALUES (:id, :s, 'Other', 1)"),
            {"id": book, "s": SCHOOL_A},
        )
        other_copy = (await db.execute(text("SELECT id FROM library_copies WHERE book_id = :b"), {"b": book})).scalar()
    with pytest.raises(IntegrityError):
        await db.execute(
            text(
                "INSERT INTO library_loans (school_id, book_id, copy_id, borrower_user_id, due_date, issued_by) "
                "VALUES (:s, :b, :c, :u, DATE '2026-12-01', :u)"
            ),
            {"s": SCHOOL_A, "b": SEED_LOAN_BOOK, "c": other_copy, "u": AMANI_USER},
        )
