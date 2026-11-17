"""Library categories, publishers, cards and late-return fines; bus driver details (FR-96, FR-97)."""

from decimal import Decimal

import pytest
from sqlalchemy import select

from app.models import InvoiceLine
from tests.helpers import F2_A, SCHOOL_A, TERM1, as_school, bearer, login, u

API = "/api/v1"
GATE_JUMA = u(2, 6)
AMANI_USER = u(2, 11)
SEED_LOAN_BOOK = u(52, 1)  # lent to Amani, due 2026-03-16, never returned
BUS = u(44, 1)
STAFF_JUMA = u(8, 6)


@pytest.fixture
async def admin(client) -> dict:
    return bearer(await login(client))


@pytest.fixture
async def librarian(client, admin) -> dict:
    added = await client.post(f"{API}/users/{GATE_JUMA}/roles", headers=admin, json={"role_code": "librarian"})
    assert added.status_code == 201, added.text
    return bearer(await login(client, username="gate.juma"))


async def test_books_take_a_category_and_a_publisher(client, librarian):
    category = await client.post(f"{API}/library/categories", headers=librarian, json={"name": "Hadithi"})
    publisher = await client.post(f"{API}/library/publishers", headers=librarian, json={"name": "Mkuki na Nyota"})
    assert category.status_code == publisher.status_code == 201
    assert (
        await client.post(f"{API}/library/categories", headers=librarian, json={"name": "hadithi"})
    ).status_code == 409
    book = await client.post(
        f"{API}/library/books",
        headers=librarian,
        json={
            "title": "Kinjeketile",
            "author": "E. Hussein",
            "copies": 2,
            "category_id": category.json()["id"],
            "publisher_id": publisher.json()["id"],
        },
    )
    assert book.status_code == 201, book.text
    assert book.json()["category_id"] == category.json()["id"] and book.json()["publisher_id"] == publisher.json()["id"]
    teacher = bearer(await login(client, username="tch.mwita"))
    assert (await client.get(f"{API}/library/categories", headers=teacher)).status_code == 403


async def test_cards_are_issued_once_printed_revoked_and_used_to_lend(client, librarian):
    first = await client.post(f"{API}/library/cards", headers=librarian, json={"stream_id": str(F2_A)})
    assert first.status_code == 200 and first.json()["issued"] >= 4
    assert (await client.post(f"{API}/library/cards", headers=librarian, json={"stream_id": str(F2_A)})).json()[
        "issued"
    ] == 0
    cards = (await client.get(f"{API}/library/cards?stream_id={F2_A}", headers=librarian)).json()
    assert all(c["card_no"].startswith("LC-") and c["class_stream"] == "F2 A" for c in cards)
    pdf = await client.get(f"{API}/library/cards.pdf?stream_id={F2_A}", headers=librarian)
    assert pdf.status_code == 200 and pdf.content.startswith(b"%PDF")

    amani = next(c for c in cards if c["user_id"] == str(AMANI_USER))
    book = (
        await client.post(f"{API}/library/books", headers=librarian, json={"title": "Shamba la Wanyama", "copies": 1})
    ).json()
    lent = await client.post(
        f"{API}/library/loans", headers=librarian, json={"book_id": book["id"], "card_no": amani["card_no"].lower()}
    )
    assert lent.status_code == 201 and lent.json()["borrower_user_id"] == str(AMANI_USER)

    assert (await client.post(f"{API}/library/cards/{amani['id']}/revoke", headers=librarian)).status_code == 204
    old = await client.post(
        f"{API}/library/loans", headers=librarian, json={"book_id": book["id"], "card_no": amani["card_no"]}
    )
    assert old.status_code == 422  # a revoked card no longer lends
    again = await client.post(f"{API}/library/cards", headers=librarian, json={"user_ids": [str(AMANI_USER)]})
    assert again.json()["issued"] == 1


async def test_a_late_student_return_is_fined_per_day_on_the_invoice(client, db, admin, librarian):
    rule = await client.put(f"{API}/fine-rules/library-day", headers=admin, json={"amount_tzs": "200", "grace_days": 2})
    assert rule.status_code == 200
    late = next(
        loan
        for loan in (await client.get(f"{API}/library/loans?overdue=true", headers=librarian)).json()
        if loan["book_id"] == str(SEED_LOAN_BOOK)
    )
    returned = await client.post(f"{API}/library/loans/{late['id']}/return", headers=librarian)
    assert returned.status_code == 200 and returned.json()["returned_at"]
    fine = Decimal(returned.json()["fine_tzs"])
    assert fine > 0 and fine % 200 == 0
    await as_school(db, SCHOOL_A)
    lines = (
        (await db.execute(select(InvoiceLine.amount_tzs).where(InvoiceLine.description.like("Library fine%"))))
        .scalars()
        .all()
    )
    assert lines == [fine]
    again = await client.post(f"{API}/library/loans/{late['id']}/return", headers=librarian)
    assert again.json()["fine_tzs"] is None  # returning twice does not fine twice


async def test_returns_are_not_fined_without_a_rule(client, librarian):
    late = next(
        loan
        for loan in (await client.get(f"{API}/library/loans?overdue=true", headers=librarian)).json()
        if loan["book_id"] == str(SEED_LOAN_BOOK)
    )
    assert (await client.post(f"{API}/library/loans/{late['id']}/return", headers=librarian)).json()["fine_tzs"] is None


async def test_the_bus_list_shows_the_driver(client, admin):
    assert (
        await client.patch(f"{API}/buses/{BUS}", headers=admin, json={"driver_staff_id": str(STAFF_JUMA)})
    ).status_code == 200
    buses = (await client.get(f"{API}/buses?term_id={TERM1}", headers=admin)).json()
    bus = next(b for b in buses if b["id"] == str(BUS))
    assert bus["driver_name"] == "Juma Omari"
