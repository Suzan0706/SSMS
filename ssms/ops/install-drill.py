"""Install drill (design/18.2): from an empty production stack to a school whose administrator has uploaded a file.

Run inside the stack, after deploy-check:
    docker compose ... run --rm -T api python - < ssms/ops/install-drill.py

It creates a console administrator, signs in to the console with the authenticator code, registers a school, signs in
as its administrator (changing the temporary password), uploads a clean photo and the EICAR test file, and reads the
console dashboard, all through the web container (nginx), as a browser would. Passwords and the authenticator secret
stay in memory: only status codes and counts are printed. Never run it on a live installation (it adds a school).
"""

import asyncio
import io
import secrets
import sys
import zipfile

import httpx
import pyotp

from app.db.session import provider
from app.services import platform

WEB = "http://web:8080/api/v1"
PNG = b"\x89PNG\r\n\x1a\n" + b"0" * 200
EICAR = rb"X5O!P%@AP[4\PZX54(P^)7CC)7}$EICAR-STANDARD-ANTIVIRUS-TEST-FILE!$H+H*"
results: list[tuple[str, bool]] = []


def infected_docx() -> bytes:
    """A Word document (a zip with word/document.xml) carrying the EICAR file: it passes the type check, and ClamAV
    finds the test signature inside the archive. EICAR is only recognised at the start of a file, so a photo with the
    string appended would rightly pass as clean."""
    out = io.BytesIO()
    with zipfile.ZipFile(out, "w", zipfile.ZIP_STORED) as archive:
        archive.writestr("[Content_Types].xml", "<Types/>")
        archive.writestr("word/document.xml", "<document/>")
        archive.writestr("eicar.com", EICAR)
    return out.getvalue()


def check(step: str, ok: bool, detail: str = "") -> None:
    results.append((step, ok))
    print(f"{'ok  ' if ok else 'FAIL'} {step}{(': ' + detail) if detail else ''}")


def password() -> str:
    return "Drill-" + secrets.token_urlsafe(12) + "7a"


async def main() -> None:
    run = secrets.token_hex(3)  # each run uses its own operator and school, so the drill can be repeated
    ops_email, code = f"drill-ops-{run}@ssms.co.tz", f"drill-{run}"
    ops_password = password()
    async with provider.platform() as session:
        _, uri = await platform.create_admin(session, "Drill Operator", ops_email, ops_password)
    totp = pyotp.parse_uri(uri)
    check("console administrator created", True)

    async with httpx.AsyncClient(timeout=60) as web:
        no_code = await web.post(f"{WEB}/platform/auth/login", json={"email": ops_email, "password": ops_password})
        check(
            "console refuses a sign-in without the authenticator code",
            no_code.status_code == 401,
            str(no_code.status_code),
        )
        console = await web.post(
            f"{WEB}/platform/auth/login",
            json={"email": ops_email, "password": ops_password, "totp": totp.now()},
        )
        check("console sign-in with the authenticator code", console.status_code == 200, str(console.status_code))
        ops = {"Authorization": f"Bearer {console.json()['access_token']}"}

        regions = (await web.get(f"{WEB}/platform/regions", headers=ops)).json()
        district = regions[0]["districts"][0]["id"]
        school = {
            "code": code,
            "name": "Shule ya Sekondari ya Majaribio",
            "ownership": "PRIVATE",
            "levels": ["O_LEVEL"],
            "district_id": district,
            "admin": {"first_name": "Neema", "last_name": "Majaribio", "gender": "F", "phone": "0713000111"},
        }
        made = await web.post(f"{WEB}/platform/schools", json=school, headers=ops)
        check("school registered from the console", made.status_code == 201, str(made.status_code))
        temporary = made.json()["temporary_password"]

        first = await web.post(
            f"{WEB}/auth/login", json={"school_code": code, "username": "admin", "password": temporary}
        )
        check("school administrator signs in", first.status_code == 200, str(first.status_code))
        token = first.json()["access_token"]
        check("a temporary password must be changed", first.json()["user"]["must_change_password"] is True)
        new_password = password()
        changed = await web.post(
            f"{WEB}/auth/change-password",
            json={"current_password": temporary, "new_password": new_password},
            headers={"Authorization": f"Bearer {token}"},
        )
        check("password changed", changed.status_code == 204, str(changed.status_code))
        again = await web.post(
            f"{WEB}/auth/login", json={"school_code": code, "username": "admin", "password": new_password}
        )
        admin = {"Authorization": f"Bearer {again.json()['access_token']}"}

        clean = await web.post(f"{WEB}/files", headers=admin, data={"purpose": "PHOTO"}, files={"file": ("p.png", PNG)})
        check("a clean photo is scanned and stored", clean.status_code == 201, str(clean.status_code))
        back = await web.get(f"{WEB}/files/{clean.json()['id']}", headers=admin)
        check("the photo reads back from the object store", back.status_code == 200 and back.content == PNG)
        # A head teacher who also teaches publishes study materials: give the administrator the teacher role.
        me = (await web.get(f"{WEB}/auth/me", headers=admin)).json()
        role = await web.post(f"{WEB}/users/{me['user']['id']}/roles", headers=admin, json={"role_code": "teacher"})
        check("teacher role added to the administrator", role.status_code == 201, str(role.status_code))
        relog = await web.post(
            f"{WEB}/auth/login", json={"school_code": code, "username": "admin", "password": new_password}
        )
        teacher = {"Authorization": f"Bearer {relog.json()['access_token']}"}
        infected = await web.post(
            f"{WEB}/files",
            headers=teacher,
            data={"purpose": "STUDY_MATERIAL"},
            files={"file": ("somo.docx", infected_docx())},
        )
        check(
            "a Word document carrying the EICAR test file is refused",
            infected.status_code == 422 and infected.json().get("error_code") == "FILE_INFECTED",
            str(infected.status_code),
        )

        board = (await web.get(f"{WEB}/platform/dashboard", headers=ops)).json()
        listed = any(s["code"] == code for s in board["per_school"])
        check("console dashboard lists the new school", listed, f"{board['schools']} school(s) in total")

    failed = [step for step, ok in results if not ok]
    print(f"install drill: {len(results) - len(failed)}/{len(results)} checks passed")
    sys.exit(1 if failed else 0)


asyncio.run(main())
