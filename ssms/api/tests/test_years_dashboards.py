"""Session selector (FR-72), receptionist role (FR-76) and dashboards per role (FR-73)."""

from datetime import date

import pytest

from app.models import Enrolment
from app.models.enums import EnrolmentStatus
from app.services import dashboards
from tests.helpers import F1_A, SCHOOL_A, YEAR_2026, as_school, bearer, login, u

API = "/api/v1"
GATE_JUMA = u(2, 6)  # seeded gatekeeper: only attendance.device, so a role added here is easy to see
YEAR_UPENDO = u(12, 101)
AMANI = u(6, 11)  # seeded in F2 A for 2026


@pytest.fixture(autouse=True)
def _fresh_dashboards():
    dashboards.clear_cache()


@pytest.fixture
async def admin(client) -> dict:
    return bearer(await login(client))


async def past_year(client, admin) -> str:
    response = await client.post(
        f"{API}/academic-years",
        headers=admin,
        json={"name": "2025", "start_date": "2025-01-01", "end_date": "2025-12-31"},
    )
    assert response.status_code == 201, response.text
    return response.json()["id"]


async def as_role(client, admin, role: str) -> dict:
    added = await client.post(f"{API}/users/{GATE_JUMA}/roles", headers=admin, json={"role_code": role})
    assert added.status_code == 201, added.text
    return bearer(await login(client, username="gate.juma"))


async def test_the_year_header_must_be_a_year_of_this_school(client, admin):
    bad = await client.get(f"{API}/students", headers=admin | {"X-Academic-Year": "2025"})
    assert bad.status_code == 422 and bad.json()["details"][0]["field"] == "X-Academic-Year"
    other_school = await client.get(f"{API}/students", headers=admin | {"X-Academic-Year": str(YEAR_UPENDO)})
    assert other_school.status_code == 422
    assert (await client.get(f"{API}/students", headers=admin | {"X-Academic-Year": str(YEAR_2026)})).status_code == 200


async def test_the_student_list_shows_classes_of_the_chosen_year(client, db, admin):
    year_2025 = await past_year(client, admin)
    await as_school(db, SCHOOL_A)
    db.add(
        Enrolment(
            school_id=SCHOOL_A,
            student_id=AMANI,
            stream_id=F1_A,
            academic_year_id=year_2025,
            status=EnrolmentStatus.PROMOTED,
            started_on=date(2025, 1, 13),
            ended_on=date(2025, 12, 5),
        )
    )
    await db.commit()

    def amani(body):
        return next(s for s in body["items"] if s["id"] == str(AMANI))

    now = (await client.get(f"{API}/students?limit=50", headers=admin)).json()
    assert (amani(now)["class_code"], amani(now)["stream_name"]) == ("F2", "A")
    then = (await client.get(f"{API}/students?limit=50", headers=admin | {"X-Academic-Year": year_2025})).json()
    assert (amani(then)["class_code"], amani(then)["stream_name"]) == ("F1", "A")
    others = [s for s in then["items"] if s["id"] != str(AMANI)]
    assert others and all(s["class_code"] is None for s in others)  # nobody else was enrolled in 2025


async def test_nothing_changes_while_another_year_is_shown(client, admin):
    year_2025 = await past_year(client, admin)
    viewing_2025 = admin | {"X-Academic-Year": year_2025}
    department = {"code": "LIB", "name_en": "Library", "name_sw": "Maktaba"}
    refused = await client.post(f"{API}/departments", headers=viewing_2025, json=department)
    assert refused.status_code == 409 and refused.json()["error_code"] == "YEAR_READ_ONLY"
    assert (await client.post(f"{API}/notifications/read-all", headers=viewing_2025)).status_code in (200, 204)
    assert (await client.get(f"{API}/departments", headers=viewing_2025)).status_code == 200
    current = admin | {"X-Academic-Year": str(YEAR_2026)}
    assert (await client.post(f"{API}/departments", headers=current, json=department)).status_code == 201


async def test_the_office_dashboard_counts_the_chosen_year(client, admin):
    year_2025 = await past_year(client, admin)
    now = (await client.get(f"{API}/dashboards/admin", headers=admin)).json()
    then = (await client.get(f"{API}/dashboards/admin", headers=admin | {"X-Academic-Year": year_2025})).json()
    assert now["series"]["enrolment_by_class"] and then["series"]["enrolment_by_class"] == []


async def test_receptionist_works_the_front_desk_but_not_marks_money_or_health(client, admin):
    desk = await as_role(client, admin, "receptionist")
    board = await client.get(f"{API}/dashboards/receptionist", headers=desk)
    assert board.status_code == 200, board.text
    body = board.json()
    assert set(body["tiles"]) == {"waiting", "under_review", "approved", "admitted_this_month"}
    assert all("application_no" in a for a in body["series"]["latest_applications"])
    assert (await client.get(f"{API}/students", headers=desk)).status_code == 200
    assert (await client.get(f"{API}/enrolment-applications", headers=desk)).status_code == 200
    for path in ("/invoices", "/fee-structures", "/reconciliation-runs", "/dashboards/bursar", "/dashboards/admin"):
        assert (await client.get(f"{API}{path}", headers=desk)).status_code == 403, path


async def test_librarian_dashboard_lists_overdue_loans(client, admin):
    librarian = await as_role(client, admin, "librarian")
    body = (await client.get(f"{API}/dashboards/librarian", headers=librarian)).json()
    assert body["tiles"]["titles"] >= 1 and body["tiles"]["on_loan"] >= 1
    late = body["series"]["overdue_loans"]
    assert body["tiles"]["overdue"] == len(late) and late[0]["days_late"] > 0
    assert "Basic Mathematics" in late[0]["title"]
    teacher = bearer(await login(client, username="tch.mwita"))
    assert (await client.get(f"{API}/dashboards/librarian", headers=teacher)).status_code == 403
