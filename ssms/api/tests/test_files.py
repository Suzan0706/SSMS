"""Uploaded files: type from content, limits per purpose, permissions, school isolation (design/20 §20.3, NFR-16)."""

import io
import zipfile

import pytest
from sqlalchemy import select

from app.core import files as ft
from app.models import StoredFile
from app.models.enums import ScanStatus
from app.services.files import clean_name
from tests.helpers import SCHOOL_A, as_school, bearer, login

API = "/api/v1"
PNG = b"\x89PNG\r\n\x1a\n" + b"0" * 200
PDF = b"%PDF-1.4\n% test\n"


def office(part: str, macro: bool = False) -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr("[Content_Types].xml", "<Types/>")
        archive.writestr(part, "<x/>")
        if macro:
            archive.writestr("word/vbaProject.bin", b"\x00")
    return buffer.getvalue()


@pytest.fixture
async def admin(client) -> dict:
    return bearer(await login(client))


async def upload(client, headers, data, purpose="PHOTO", name="picha.png"):
    return await client.post(f"{API}/files", headers=headers, data={"purpose": purpose}, files={"file": (name, data)})


def test_types_are_read_from_the_content():
    assert ft.sniff(PDF) == (ft.PDF, "pdf")
    assert ft.sniff(office("word/document.xml")) == (ft.DOCX, "docx")
    assert ft.sniff(office("ppt/presentation.xml")) == (ft.PPTX, "pptx")
    assert ft.sniff(office("xl/workbook.xml")) == (ft.XLSX, "xlsx")
    assert ft.sniff(office("word/document.xml", macro=True)) is None  # macros never accepted
    assert ft.sniff(b"PK\x03\x04 not really a zip") is None
    assert ft.sniff(b"ID3\x03\x00" + b"0" * 20) == (ft.MP3, "mp3")
    assert ft.sniff(b"\x00\x00\x00\x18ftypmp42" + b"0" * 20) == (ft.MP4, "mp4")
    assert ft.sniff(b"<script>alert(1)</script>") is None


def test_display_names_are_cleaned():
    assert clean_name("C:\\Users\\x\\picha ya Amani.png", "png") == "picha ya Amani.png"
    assert clean_name("../../etc/passwd", "pdf") == "passwd.pdf"
    assert clean_name("ripoti.exe", "pdf") == "ripoti.pdf"  # the real extension, not the claimed one
    assert clean_name("a\x00b\nc.png", "png") == "abc.png"
    assert clean_name(None, "jpg") == "file.jpg"
    assert len(clean_name("x" * 400 + ".pdf", "pdf")) <= 200


async def test_admin_uploads_a_photo_and_staff_with_student_access_can_read_it(client, db, admin):
    response = await upload(client, admin, PNG, name="../Amani.png")
    assert response.status_code == 201, response.text
    body = response.json()
    assert (
        body["content_type"] == "image/png" and body["original_name"] == "Amani.png" and body["size_bytes"] == len(PNG)
    )
    assert "storage_key" not in body

    read = await client.get(body["url"], headers=admin)
    assert read.status_code == 200 and read.content == PNG
    assert read.headers["content-type"] == "image/png" and read.headers["cache-control"] == "private, no-store"

    teacher = bearer(await login(client, username="tch.mwita"))  # students.read: may see photographs
    assert (await client.get(body["url"], headers=teacher)).status_code == 200

    await as_school(db, SCHOOL_A)
    row = (await db.execute(select(StoredFile).where(StoredFile.id == body["id"]))).scalar_one()
    assert row.scan_status == ScanStatus.SKIPPED and len(row.sha256) == 64
    assert row.storage_key.startswith(f"{SCHOOL_A}/files/") and "Amani" not in row.storage_key


async def test_wrong_type_and_oversized_files_are_refused(client, admin):
    pdf_as_photo = await upload(client, admin, PDF, name="picha.png")
    assert pdf_as_photo.status_code == 422 and pdf_as_photo.json()["error_code"] == "FILE_TYPE"
    text_as_png = await upload(client, admin, b"hello, not an image", name="picha.png")
    assert text_as_png.status_code == 422
    big = await upload(client, admin, PNG + b"0" * (300 * 1024))
    assert big.status_code == 413 and big.json()["error_code"] == "FILE_TOO_LARGE_KB"
    empty = await upload(client, admin, b"")
    assert empty.status_code == 422


async def test_upload_needs_the_purpose_permission(client):
    teacher = bearer(await login(client, username="tch.mwita"))  # no students.update
    assert (await upload(client, teacher, PNG)).status_code == 403


async def test_other_schools_and_parents_cannot_read_a_file(client, admin):
    url = (await upload(client, admin, PNG)).json()["url"]
    other_school = bearer(await login(client, school="upendo-pri"))
    assert (await client.get(url, headers=other_school)).status_code == 404
    assert (await client.get(url)).status_code == 401


async def test_only_the_uploader_discards_a_file(client, admin):
    url = (await upload(client, admin, PNG)).json()["url"]
    teacher = bearer(await login(client, username="tch.mwita"))
    assert (await client.delete(url, headers=teacher)).status_code == 404
    assert (await client.delete(url, headers=admin)).status_code == 204
    assert (await client.get(url, headers=admin)).status_code == 404
