"""Academic progress across terms for the student, their guardians and staff (brief §4 Q and R)."""

from tests.helpers import GUARDIAN_A, SCHOOL_A, SHARED_PHONE, bearer, login, parent_login, u

API = "/api/v1"
AMANI = u(6, 11)  # Form II, results published for Term One in the seed


async def test_the_student_their_parent_and_staff_see_progress_by_term(client, db, dispatcher):
    amani = bearer(await login(client, username="mf-2025-0014"))
    rows = (await client.get(f"{API}/students/{AMANI}/progress", headers=amani)).json()
    assert rows and rows[0]["term"].startswith("Muhula wa Kwanza")
    first = rows[0]
    assert first["average"] is not None and 1 <= first["position"] <= first["out_of"]

    parent = await parent_login(client, db, dispatcher, SCHOOL_A, GUARDIAN_A, SHARED_PHONE)
    assert (await client.get(f"{API}/students/{AMANI}/progress", headers=parent)).json() == rows
    teacher = bearer(await login(client, username="tch.mwita"))
    assert (await client.get(f"{API}/students/{AMANI}/progress", headers=teacher)).status_code == 200


async def test_other_students_and_other_schools_cannot_see_it(client):
    emmanuel = bearer(await login(client, username="mf-2026-0003"))
    assert (await client.get(f"{API}/students/{AMANI}/progress", headers=emmanuel)).status_code == 404
    other_school = bearer(await login(client, school="upendo-pri"))
    assert (await client.get(f"{API}/students/{AMANI}/progress", headers=other_school)).status_code == 404
