"""Phase 12 security review (design/21): the checks that were missing when the review started.

Every route asks for a sign-in unless it is on the short public list; no response schema can carry a secret; CORS
answers only the configured origin; search inputs cannot change a query; spreadsheets never run what people typed;
a file in use cannot be discarded; another school's certificates and cards cannot be reached.
"""

import io
import re
import uuid

from openpyxl import Workbook, load_workbook

from app.core import sheets
from app.services import imports, reports
from tests.helpers import bearer, login, u

API = "/api/v1"
STAFF_MWITA = u(8, 3)
AMANI = u(6, 11)
PNG = b"\x89PNG\r\n\x1a\n" + b"0" * 200

# Routes anyone may call, each with its reason. Anything else must answer 401 without a token.
PUBLIC = {
    "/health/live": "liveness probe",
    "/health/ready": "readiness probe",
    "/metrics": "Prometheus scrape, closed at the web server (nginx.conf)",
    f"{API}/auth/login": "sign-in",
    f"{API}/auth/refresh": "uses the httpOnly refresh cookie instead of a token",
    f"{API}/auth/logout": "revokes the refresh cookie's session",
    f"{API}/auth/otp/request": "parent sign-in by phone",
    f"{API}/auth/otp/verify": "parent sign-in by phone",
    f"{API}/auth/select-school": "uses the short-lived selection token from otp/verify",
    f"{API}/platform/auth/login": "console sign-in",
    f"{API}/enrolment/offerings": "applicants see classes and places left; rate-limited, no personal data",
}
# Called by payment networks, SMS gateways and gate devices: no user token; each checks its own signature or key.
MACHINE = {
    f"{API}/devices/taps": "device API key (stored as a hash)",
    f"{API}/webhooks/gepg/bill": "GePG signature",
    f"{API}/webhooks/gepg/payment": "GePG signature",
    f"{API}/webhooks/sms/{{provider}}": "provider signature",
    f"{API}/webhooks/{{provider}}": "mobile money provider signature",
}
SECRET_FIELD = re.compile(r"(password|_hash$|_enc$|secret|totp|refresh_token|api_key|private)", re.I)
# Shown exactly once, to the person who created them; only a hash is stored and a password must be changed at first use.
SHOWN_ONCE = {
    ("POST /api/v1/platform/schools", "temporary_password"),
    ("POST /api/v1/staff", "temporary_password"),
    ("POST /api/v1/users/{user_id}/reset-password", "temporary_password"),
    ("POST /api/v1/devices", "api_key"),
    ("POST /api/v1/devices/{device_id}/rotate-key", "api_key"),
}


def _concrete(path: str) -> str:
    return re.sub(r"\{[^}]+\}", str(uuid.uuid4()), path)


async def test_every_route_needs_a_sign_in_except_the_public_list(client):
    # The route list comes from the OpenAPI document (only /metrics is hidden from it, and it is public).
    paths = (await client.get("/openapi.json")).json()["paths"]
    checked, open_routes = 0, []
    for path, methods in paths.items():
        if path in PUBLIC or path in MACHINE:
            continue
        for method in methods:
            checked += 1
            response = await client.request(method.upper(), _concrete(path), json={})
            if response.status_code not in (401, 403):
                open_routes.append(f"{method.upper()} {path} -> {response.status_code}")
    assert checked > 300, checked  # the sweep really ran over the whole API
    assert open_routes == [], "\n".join(open_routes)


async def test_no_response_can_carry_a_secret(client):
    schema = (await client.get("/openapi.json")).json()
    leaks = []
    for path, methods in schema["paths"].items():
        for method, op in methods.items():
            for code, resp in op.get("responses", {}).items():
                ref = resp.get("content", {}).get("application/json", {}).get("schema", {})
                for name in _fields(schema, ref, set()):
                    if (f"{method.upper()} {path}", name) in SHOWN_ONCE or name in (
                        "must_change_password",
                        "totp_enabled",
                    ):
                        continue
                    if SECRET_FIELD.search(name):
                        leaks.append(f"{method.upper()} {path} {code}: {name}")
    assert leaks == [], "\n".join(leaks)


def _fields(schema: dict, node: dict, seen: set) -> set[str]:
    if "$ref" in node:
        name = node["$ref"].rsplit("/", 1)[-1]
        if name in seen:
            return set()
        seen.add(name)
        return _fields(schema, schema["components"]["schemas"][name], seen)
    found = set(node.get("properties", {}))
    for child in [
        *node.get("properties", {}).values(),
        node.get("items", {}),
        *node.get("anyOf", []),
        *node.get("allOf", []),
    ]:
        if isinstance(child, dict) and child:
            found |= _fields(schema, child, seen)
    return found


async def test_cors_answers_only_the_configured_origin(client):
    asked = {"Access-Control-Request-Method": "POST", "Access-Control-Request-Headers": "authorization"}
    good = await client.options(f"{API}/auth/login", headers={"Origin": "http://localhost:5173", **asked})
    assert good.headers.get("access-control-allow-origin") == "http://localhost:5173"
    evil = await client.options(f"{API}/auth/login", headers={"Origin": "https://evil.example", **asked})
    assert "access-control-allow-origin" not in evil.headers


async def test_search_inputs_cannot_change_a_query(client):
    admin = bearer(await login(client))
    everyone = (await client.get(f"{API}/students?limit=50", headers=admin)).json()["items"]
    for attack in ("' OR '1'='1", "%' OR 1=1 --", "x'); DROP TABLE students; --", "\\'; SELECT pg_sleep(5); --"):
        response = await client.get(f"{API}/students", params={"q": attack}, headers=admin)
        assert response.status_code in (200, 422), attack
        if response.status_code == 200:
            assert response.json()["items"] == [], attack
    assert len((await client.get(f"{API}/students?limit=50", headers=admin)).json()["items"]) == len(everyone)


def test_spreadsheets_store_typed_formulas_as_text():
    attack = '=HYPERLINK("http://evil.example","Bonyeza")'
    assert sheets.csv_cell(attack).startswith("'=")
    assert sheets.csv_cell("Amani Juma") == "Amani Juma"

    csv_text = reports.render(["name", "amount"], [[attack, None], ["+255754000021", None]], "csv", "t").decode()
    assert "'=HYPERLINK" in csv_text and "'+255754000021" in csv_text

    for content in (
        reports.render(["name"], [[attack]], "xlsx", "t"),
        imports.report([{"row": 2, "column": "name", "code": "x", "message": attack}]),
    ):
        cells = [c for row in load_workbook(io.BytesIO(content)).active.iter_rows() for c in row]
        typed = next(c for c in cells if c.value == attack)
        assert typed.data_type == "s"  # text, not a formula

    ws = Workbook().active
    sheets.append(ws, [attack, 5, -3])
    assert [c.data_type for c in ws[1]] == ["s", "n", "n"]  # numbers stay numbers


async def test_a_file_in_use_cannot_be_discarded(client):
    admin = bearer(await login(client))
    photo = (
        await client.post(f"{API}/files", headers=admin, data={"purpose": "PHOTO"}, files={"file": ("m.png", PNG)})
    ).json()
    assert (
        await client.put(f"{API}/staff/{STAFF_MWITA}/photo", headers=admin, json={"file_id": photo["id"]})
    ).status_code == 204

    refused = await client.delete(f"{API}/files/{photo['id']}", headers=admin)
    assert refused.status_code == 409 and refused.json()["error_code"] == "FILE_IN_USE"
    assert (await client.get(f"{API}/staff/{STAFF_MWITA}/photo", headers=admin)).status_code == 200

    spare = (
        await client.post(f"{API}/files", headers=admin, data={"purpose": "PHOTO"}, files={"file": ("s.png", PNG)})
    ).json()
    assert (await client.delete(f"{API}/files/{spare['id']}", headers=admin)).status_code == 204


async def test_another_schools_certificates_and_cards_are_out_of_reach(client):
    admin = bearer(await login(client))
    template = (
        await client.post(
            f"{API}/certificate-templates",
            headers=admin,
            json={"kind": "CHARACTER", "name": "Tabia njema", "body": "{{name}} ana tabia njema shuleni {{school}}."},
        )
    ).json()
    issued = (
        await client.post(
            f"{API}/certificates",
            headers=admin,
            json={"template_id": template["id"], "student_ids": [str(AMANI)], "issued_on": "2026-11-02"},
        )
    ).json()["issued"][0]

    other = bearer(await login(client, school="upendo-pri"))
    assert (await client.get(f"{API}/certificates/{issued['id']}.pdf", headers=other)).status_code == 404
    assert (
        await client.post(
            f"{API}/certificates/{issued['id']}/revoke", headers=other, json={"reason": "Jaribio la shule nyingine"}
        )
    ).status_code == 404
    assert all(c["id"] != issued["id"] for c in (await client.get(f"{API}/certificates", headers=other)).json())
    assert (
        await client.put(
            f"{API}/certificate-templates/{template['id']}",
            headers=other,
            json={"kind": "CHARACTER", "name": "Imeibiwa", "body": "Maandishi ya shule nyingine {{name}}"},
        )
    ).status_code == 404
    assert (await client.get(f"{API}/staff/{STAFF_MWITA}/photo", headers=other)).status_code == 404


def test_study_material_links_cannot_carry_script():
    """Links are shown to students as <a href>, so only https is accepted (no javascript:, data: or http:)."""
    import pytest
    from pydantic import ValidationError

    from app.schemas.teaching import MaterialIn

    base = {"subject_id": str(uuid.uuid4()), "stream_ids": [str(uuid.uuid4())], "title": "Kiungo"}
    for bad in ("javascript:alert(document.cookie)", "data:text/html,<script>alert(1)</script>", "http://example.org"):
        with pytest.raises(ValidationError):
            MaterialIn(**base, link_url=bad)
    assert MaterialIn(**base, link_url="https://example.org/somo").link_url.scheme == "https"


def test_production_refuses_to_start_with_development_settings(monkeypatch):
    import pytest

    from app.core import config

    monkeypatch.setenv("SSMS_ENVIRONMENT", "production")
    monkeypatch.setenv("SSMS_EMAIL_PROVIDER", "smtp")
    for name in ("SSMS_SMTP_HOST", "SSMS_JWT_SECRET", "SSMS_BLIND_INDEX_KEY"):
        monkeypatch.delenv(name, raising=False)
    config.get_settings.cache_clear()
    try:
        with pytest.raises(RuntimeError) as refused:
            config.get_settings()
        for setting in ("SSMS_JWT_SECRET", "SSMS_BLIND_INDEX_KEY", "SSMS_SMS_PROVIDER", "SSMS_SMTP_HOST"):
            assert setting in str(refused.value)
        assert "dev-only" not in str(refused.value)  # names the settings, never prints a value
    finally:
        config.get_settings.cache_clear()


async def test_console_email_in_production_is_off_not_falsely_sent(client, monkeypatch):
    from app.api import documents as documents_api
    from app.core.config import Settings
    from app.services import email

    production = Settings(environment="production", email_provider="console")
    assert not production.email_enabled and Settings(environment="production", email_provider="smtp").email_enabled
    monkeypatch.setattr(email, "get_settings", lambda: production)
    monkeypatch.setattr(documents_api, "get_settings", lambda: production)

    admin = bearer(await login(client))
    off = await client.post(f"{API}/email-messages/test", headers=admin)
    assert off.status_code == 422 and off.json()["details"][0]["code"] == "email_off"
    assert (await client.get(f"{API}/email-messages", headers=admin)).json() == []
