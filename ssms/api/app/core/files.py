"""Uploaded files are recognised by their content (magic bytes), never by the name or the browser's type."""

import io
import zipfile

from fastapi import UploadFile

from app.core.errors import AppError

PDF = "application/pdf"
JPEG = "image/jpeg"
PNG = "image/png"
DOCX = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
PPTX = "application/vnd.openxmlformats-officedocument.presentationml.presentation"
XLSX = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
MP3 = "audio/mpeg"
MP4 = "video/mp4"

SIGNATURES = (
    (b"%PDF-", PDF, "pdf"),
    (b"\xff\xd8\xff", JPEG, "jpg"),
    (b"\x89PNG\r\n\x1a\n", PNG, "png"),
)

# Office Open XML files are zip archives; the part that identifies each kind.
_OOXML = (
    ("word/document.xml", DOCX, "docx"),
    ("ppt/presentation.xml", PPTX, "pptx"),
    ("xl/workbook.xml", XLSX, "xlsx"),
)


def _ooxml(data: bytes) -> tuple[str, str] | None:
    """Kind of an Office file, or None. Files with macros (vbaProject.bin) are never accepted."""
    try:
        with zipfile.ZipFile(io.BytesIO(data)) as archive:
            names = set(archive.namelist())
    except (zipfile.BadZipFile, ValueError):
        return None
    if any(n.lower().endswith("vbaproject.bin") for n in names):
        return None
    for part, mime, ext in _OOXML:
        if part in names:
            return mime, ext
    return None


def sniff(data: bytes) -> tuple[str, str] | None:
    """(mime type, extension) recognised from the bytes, or None."""
    for magic, mime, ext in SIGNATURES:
        if data.startswith(magic):
            return mime, ext
    if data.startswith(b"PK\x03\x04"):
        return _ooxml(data)
    if data.startswith(b"ID3") or (len(data) > 1 and data[0] == 0xFF and data[1] & 0xE0 == 0xE0):
        return MP3, "mp3"
    if data[4:8] == b"ftyp":
        return MP4, "mp4"
    return None


def detect(data: bytes, allowed: set[str]) -> tuple[str, str]:
    """(mime type, extension) or 422 FILE_TYPE."""
    found = sniff(data)
    if found is None or found[0] not in allowed:
        raise AppError(422, "FILE_TYPE", [{"field": "file", "code": "invalid_value"}])
    return found


async def read_limited(file: UploadFile, limit: int) -> bytes:
    """Read at most `limit` bytes; larger files are refused with 413 FILE_TOO_LARGE."""
    data = await file.read(limit + 1)
    if len(data) > limit:
        if limit < 1024 * 1024:
            raise AppError(413, "FILE_TOO_LARGE_KB", kb=limit // 1024)
        raise AppError(413, "FILE_TOO_LARGE", mb=limit // (1024 * 1024))
    if not data:
        raise AppError(422, "VALIDATION_ERROR", [{"field": "file", "code": "required"}])
    return data
