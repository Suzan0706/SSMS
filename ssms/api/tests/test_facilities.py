"""Hostel, transport and venues through the API, as ssms_app; facility fees keep the books balanced."""

from decimal import Decimal

import pytest

from app.models import FeeStructureLine
from tests.finance_helpers import assert_books_balance
from tests.helpers import SCHOOL_A, TERM1, as_school, bearer, login, parent_login, u

API = "/api/v1"
KILIMANJARO, K1 = u(41, 1), u(42, 1)  # girls' hostel, room for 4 (Zawadi already there in Term One)
AMANI, BARAKA, REHEMA, JUMA, EMMANUEL = (u(6, n) for n in (11, 13, 14, 15, 17))
SWAI, SWAI_PHONE = u(2, 24), "255786000024"  # Rehema's father
MAIN_HALL = u(47, 1)


@pytest.fixture
async def admin(client) -> dict:
    return bearer(await login(client))


async def invoice_of(client, headers, student) -> dict:
    page = (await client.get(f"{API}/invoices?term_id={TERM1}", headers=headers)).json()["items"]
    return next(i for i in page if i["student_id"] == str(student))


async def test_hostel_requests_decisions_and_boarding_fee(client, db, admin, dispatcher):
    # The Form II structure gets an optional boarding line: charged only to students given a room.
    await as_school(db, SCHOOL_A)
    db.add(
        FeeStructureLine(
            school_id=SCHOOL_A,
            fee_structure_id=u(35, 1),
            fee_item_id=u(34, 6),
            term_id=TERM1,
            amount_tzs=Decimal("200000"),
            is_optional=True,
        )
    )
    await db.commit()
    boys = await client.post(f"{API}/hostels", headers=admin, json={"name": "Bweni la Serengeti", "gender": "M"})
    assert boys.status_code == 201
    room = await client.post(
        f"{API}/hostel-rooms", headers=admin, json={"hostel_id": boys.json()["id"], "name": "S1", "capacity": 1}
    )
    assert room.status_code == 201
    duplicate_room = await client.post(
        f"{API}/hostel-rooms", headers=admin, json={"hostel_id": boys.json()["id"], "name": "S1", "capacity": 2}
    )
    assert duplicate_room.status_code == 409

    parent = await parent_login(client, db, dispatcher, SCHOOL_A, SWAI, SWAI_PHONE)
    body = {"term_id": str(TERM1), "student_id": str(REHEMA), "preferred_hostel_id": str(KILIMANJARO)}
    asked = await client.post(f"{API}/accommodation-requests", headers=parent, json=body)
    assert asked.status_code == 201 and asked.json()["status"] == "PENDING"
    assert (await client.post(f"{API}/accommodation-requests", headers=parent, json=body)).status_code == 409
    not_mine = await client.post(
        f"{API}/accommodation-requests", headers=parent, json={**body, "student_id": str(AMANI)}
    )
    assert not_mine.status_code == 403 and not_mine.json()["details"][0]["code"] == "not_own_child"
    assert [r["student_id"] for r in (await client.get(f"{API}/accommodation-requests", headers=parent)).json()] == [
        str(REHEMA)
    ]

    emmanuel = bearer(await login(client, username="mf-2026-0003"))
    wrong = await client.post(
        f"{API}/accommodation-requests",
        headers=emmanuel,
        json={"term_id": str(TERM1), "preferred_hostel_id": str(KILIMANJARO)},
    )
    assert wrong.status_code == 422 and wrong.json()["details"][0]["code"] == "wrong_gender"
    own = await client.post(f"{API}/accommodation-requests", headers=emmanuel, json={"term_id": str(TERM1)})
    assert own.status_code == 201 and own.json()["student_id"] == str(EMMANUEL)
    assert (
        await client.post(
            f"{API}/accommodation-requests/{own.json()['id']}/decide", headers=emmanuel, json={"approve": False}
        )
    ).status_code == 403

    before = Decimal((await invoice_of(client, admin, REHEMA))["total_tzs"])
    approved = await client.post(
        f"{API}/accommodation-requests/{asked.json()['id']}/decide",
        headers=admin,
        json={"approve": True, "room_id": str(K1)},
    )
    assert approved.status_code == 200, approved.text
    out = approved.json()
    assert out["status"] == "APPROVED" and out["room"] == "Bweni la Kilimanjaro / K1" and out["invoice_no"]
    assert Decimal((await invoice_of(client, admin, REHEMA))["total_tzs"]) == before + 200000
    await assert_books_balance(db)
    girls_room = await client.post(
        f"{API}/accommodation-requests/{own.json()['id']}/decide",
        headers=admin,
        json={"approve": True, "room_id": str(K1)},
    )
    assert girls_room.json()["details"][0]["code"] == "wrong_gender"
    assert (
        await client.post(
            f"{API}/accommodation-requests/{own.json()['id']}/decide",
            headers=admin,
            json={"approve": True, "room_id": room.json()["id"]},
        )
    ).json()["invoice_no"] is None  # Emmanuel (Form V) has no Term One invoice: generation will add boarding

    juma = await client.post(
        f"{API}/accommodation-requests", headers=admin, json={"term_id": str(TERM1), "student_id": str(JUMA)}
    )
    full = await client.post(
        f"{API}/accommodation-requests/{juma.json()['id']}/decide",
        headers=admin,
        json={"approve": True, "room_id": room.json()["id"]},
    )
    assert (
        full.status_code == 422
        and full.json()["error_code"] == "FULL"
        and full.json()["details"][0]["code"] == "room_full"
    )
    rejected = await client.post(
        f"{API}/accommodation-requests/{juma.json()['id']}/decide",
        headers=admin,
        json={"approve": False, "note": "Hakuna nafasi"},
    )
    assert rejected.json()["status"] == "REJECTED"

    occupancy = (await client.get(f"{API}/hostels/{KILIMANJARO}/occupancy?term_id={TERM1}", headers=admin)).json()
    assert (occupancy["beds"], occupancy["used"]) == (4, 2)
    allocation = next(o for r in occupancy["rooms"] for o in r["occupants"] if o["student_id"] == str(REHEMA))
    assert (
        await client.post(f"{API}/hostel-allocations/{allocation['allocation_id']}/vacate", headers=admin)
    ).status_code == 204
    assert (await client.get(f"{API}/hostels/{KILIMANJARO}/occupancy?term_id={TERM1}", headers=admin)).json()[
        "used"
    ] == 1
    hostels = {h["name"]: h for h in (await client.get(f"{API}/hostels", headers=admin)).json()}
    assert (hostels["Bweni la Serengeti"]["rooms"], hostels["Bweni la Serengeti"]["beds"]) == (1, 1)


async def test_cancel_pending_request(client, db, dispatcher):
    parent = await parent_login(client, db, dispatcher, SCHOOL_A, SWAI, SWAI_PHONE)
    asked = await client.post(
        f"{API}/accommodation-requests", headers=parent, json={"term_id": str(TERM1), "student_id": str(REHEMA)}
    )
    cancelled = await client.post(f"{API}/accommodation-requests/{asked.json()['id']}/cancel", headers=parent)
    assert cancelled.json()["status"] == "CANCELLED"
    assert (
        await client.post(f"{API}/accommodation-requests/{asked.json()['id']}/cancel", headers=parent)
    ).status_code == 409
    again = await client.post(
        f"{API}/accommodation-requests", headers=parent, json={"term_id": str(TERM1), "student_id": str(REHEMA)}
    )
    assert again.status_code == 201  # a cancelled request does not block a new one


async def test_transport_assignment_adds_route_fee(client, db, admin):
    bad = await client.post(f"{API}/buses", headers=admin, json={"bus_no": "ABC 123", "capacity": 30})
    assert bad.status_code == 422
    bus = (await client.post(f"{API}/buses", headers=admin, json={"bus_no": "T 456 GHJ", "capacity": 1})).json()
    assert (
        await client.post(f"{API}/buses", headers=admin, json={"bus_no": "T 456 GHJ", "capacity": 5})
    ).status_code == 409
    route = await client.post(
        f"{API}/routes",
        headers=admin,
        json={
            "name": "Makole - Shuleni",
            "term_fee_tzs": "90000",
            "stops": [
                {"seq": 2, "name": "Makole", "pickup_time": "06:50"},
                {"seq": 1, "name": "Chamwino", "pickup_time": "06:30"},
            ],
        },
    )
    assert route.status_code == 201 and [s["name"] for s in route.json()["stops"]] == ["Chamwino", "Makole"]
    stop = route.json()["stops"][0]["id"]
    before = Decimal((await invoice_of(client, admin, BARAKA))["total_tzs"])
    body = {
        "student_id": str(BARAKA),
        "bus_id": bus["id"],
        "stop_id": stop,
        "term_id": str(TERM1),
    }
    assigned = await client.post(f"{API}/transport-assignments", headers=admin, json=body)
    assert assigned.status_code == 201, assigned.text
    out = assigned.json()
    assert out["invoice_no"] and out["bus_no"] == "T 456 GHJ" and out["stop_name"] == "Chamwino"
    assert Decimal((await invoice_of(client, admin, BARAKA))["total_tzs"]) == before + 90000
    await assert_books_balance(db)

    full = await client.post(f"{API}/transport-assignments", headers=admin, json={**body, "student_id": str(JUMA)})
    assert full.status_code == 422 and full.json()["details"][0]["code"] == "bus_full"
    twice = await client.post(
        f"{API}/transport-assignments", headers=admin, json={**body, "bus_id": str(u(44, 1)), "stop_id": stop}
    )
    assert twice.status_code == 409
    seats = {
        b["bus_no"]: (b["used"], b["free"])
        for b in (await client.get(f"{API}/buses?term_id={TERM1}", headers=admin)).json()
    }
    assert seats == {"T 123 DEF": (1, 29), "T 456 GHJ": (1, 0)}
    in_use = await client.patch(f"{API}/routes/{route.json()['id']}", headers=admin, json={"stops": []})
    assert in_use.status_code == 409
    ended = await client.post(f"{API}/transport-assignments/{out['id']}/end", headers=admin)
    assert ended.json()["ended_at"]
    manifest = (await client.get(f"{API}/transport-assignments?term_id={TERM1}", headers=admin)).json()
    assert [m["student_id"] for m in manifest] == [str(AMANI)]
    teacher = bearer(await login(client, username="tch.salma"))
    assert (await client.post(f"{API}/transport-assignments", headers=teacher, json=body)).status_code == 403


async def test_venue_bookings(client, admin):
    base = {"venue_id": str(MAIN_HALL), "name": "Mkutano wa wazazi", "event_date": "2026-10-30"}
    clash = await client.post(
        f"{API}/venue-events", headers=admin, json={**base, "time_start": "10:00", "time_end": "11:00"}
    )
    assert clash.status_code == 409 and clash.json()["error_code"] == "VENUE_CLASH"  # graduation 09:00-13:00
    crowded = await client.post(
        f"{API}/venue-events",
        headers=admin,
        json={**base, "time_start": "14:00", "time_end": "15:00", "seats_occupied": 500},
    )
    assert crowded.status_code == 422 and crowded.json()["details"][0]["code"] == "too_many_seats"
    booked = await client.post(
        f"{API}/venue-events",
        headers=admin,
        json={**base, "time_start": "13:00", "time_end": "15:00", "seats_occupied": 120},
    )
    assert booked.status_code == 201  # starts when the graduation ends: no overlap
    moved = await client.patch(f"{API}/venue-events/{booked.json()['id']}", headers=admin, json={"time_start": "12:00"})
    assert moved.status_code == 409
    events = (await client.get(f"{API}/venue-events?from=2026-10-30&to=2026-10-30", headers=admin)).json()
    assert [e["time_start"] for e in events] == ["09:00:00", "13:00:00"]
    assert (await client.delete(f"{API}/venue-events/{booked.json()['id']}", headers=admin)).status_code == 204
    bursar = bearer(await login(client, username="bursar"))
    assert (
        await client.post(
            f"{API}/venue-events", headers=bursar, json={**base, "time_start": "16:00", "time_end": "17:00"}
        )
    ).status_code == 403
