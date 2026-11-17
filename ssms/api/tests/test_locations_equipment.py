"""Regions and districts as reference data; searching rooms by equipment."""

import psycopg
import pytest

from tests.conftest import TESTER_URL
from tests.helpers import SCHOOL_A, bearer, login, u
from tests.test_platform import NEW_SCHOOL, platform_login

API = "/api/v1"
F2A, F2B, LAB = u(18, 1), u(18, 2), u(18, 4)


async def test_every_region_has_its_districts(client):
    headers = bearer(await platform_login(client))
    regions = (await client.get(f"{API}/platform/regions", headers=headers)).json()
    assert len(regions) == 31
    assert all(r["districts"] for r in regions)
    names = {r["name"]: {d["name"] for d in r["districts"]} for r in regions}
    assert "Dodoma City" in names["Dodoma"] and "Dodoma City" not in names["Arusha"]


async def test_school_needs_a_real_district(client):
    headers = bearer(await platform_login(client))
    response = await client.post(
        f"{API}/platform/schools", headers=headers, json={**NEW_SCHOOL, "district_id": str(u(1, 12345))}
    )
    assert response.status_code == 422 and response.json()["details"][0]["field"] == "district_id"


async def test_school_profile_shows_region_and_district(client):
    admin = bearer(await login(client))
    school = (await client.get(f"{API}/school", headers=admin)).json()
    assert school["region"] == "Dodoma" and school["district"] == "Dodoma City"


async def test_search_rooms_by_equipment(client):
    admin = bearer(await login(client))
    items = {i["name"]: i for i in (await client.get(f"{API}/equipment-items", headers=admin)).json()}
    assert items["Desks"]["rooms"] == 2
    found = await client.get(f"{API}/rooms?equipment_id={items['Desks']['id']}", headers=admin)
    assert {r["id"] for r in found.json()} == {str(F2A), str(F2B)}
    both = f"{API}/rooms?equipment_id={items['Desks']['id']}&equipment_id={items['Power points']['id']}"
    assert (await client.get(both, headers=admin)).json() == []
    lab = next(r for r in (await client.get(f"{API}/rooms", headers=admin)).json() if r["id"] == str(LAB))
    assert {e["name"]: e["quantity"] for e in lab["equipment"]} == {"Benches": 1, "Gas taps": 1, "Power points": 10}


async def test_equipment_names_are_shared_and_lists_replace(client):
    admin = bearer(await login(client))
    saved = await client.patch(
        f"{API}/rooms/{F2A}",
        headers=admin,
        json={"equipment": [{"name": "  DESKS ", "quantity": 40}, {"name": "projector"}]},
    )
    assert saved.status_code == 200, saved.text
    assert {e["name"]: e["quantity"] for e in saved.json()["equipment"]} == {"Desks": 40, "Projector": 1}
    items = {i["name"]: i for i in (await client.get(f"{API}/equipment-items", headers=admin)).json()}
    assert items["Desks"]["rooms"] == 2 and items["Whiteboard"]["rooms"] == 1 and items["Projector"]["rooms"] == 1

    untouched = await client.patch(f"{API}/rooms/{F2A}", headers=admin, json={"capacity": 44})
    assert len(untouched.json()["equipment"]) == 2


async def test_create_room_with_equipment_and_delete_rules(client):
    admin = bearer(await login(client))
    created = await client.post(
        f"{API}/rooms",
        headers=admin,
        json={
            "code": "ICT1",
            "name": "Computer room",
            "capacity": 30,
            "equipment": [{"name": "Computers", "quantity": 30}],
        },
    )
    assert created.status_code == 201, created.text
    item_id = created.json()["equipment"][0]["equipment_id"]
    remove = f"{API}/equipment-items/{item_id}?reason=No%20longer%20used"
    assert (await client.delete(remove, headers=admin)).status_code == 409
    await client.patch(f"{API}/rooms/{created.json()['id']}", headers=admin, json={"equipment": []})
    assert (await client.delete(remove, headers=admin)).status_code == 204
    renamed = await client.patch(f"{API}/equipment-items/{item_id}", headers=admin, json={"name": "Gone"})
    assert renamed.status_code == 404


async def test_other_school_sees_no_equipment(client):
    other = bearer(await login(client, school="upendo-pri"))
    assert (await client.get(f"{API}/equipment-items", headers=other)).json() == []


def test_equipment_rls_as_ssms_app(database):
    url = TESTER_URL.replace("postgresql+psycopg://", "postgresql://")
    with psycopg.connect(url) as conn:
        conn.execute("SET ROLE ssms_app")
        assert conn.execute("SELECT count(*) FROM room_equipment").fetchone()[0] == 0  # no context: fail closed
        conn.execute(f"SET LOCAL app.school_id = '{u(1, 2)}'")
        assert conn.execute(f"SELECT count(*) FROM equipment_items WHERE school_id = '{SCHOOL_A}'").fetchone()[0] == 0
        with pytest.raises(psycopg.errors.InsufficientPrivilege):
            conn.execute("INSERT INTO equipment_items (school_id, name) VALUES (%s, 'Other')", (SCHOOL_A,))
        conn.rollback()
