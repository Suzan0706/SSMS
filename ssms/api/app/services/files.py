"""Uploaded files (design/20 §20.3, NFR-16).

Every purpose has its own allowed types, size limit and upload permission. The bytes are stored under a random key,
the type comes from the content, and the stored_files row is the only way back to the bytes. Later phases add who may
read a file through the record that uses it (homework, materials, ...); until then only the uploader, and staff who may
see people for photographs, can open a file.
"""

import hashlib
import logging
import re
import secrets
import unicodedata
from dataclasses import dataclass

from sqlalchemy import exists, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import Principal
from app.core import files as ft
from app.core import scanner
from app.core.errors import AppError, forbidden, not_found
from app.core.storage import get_storage
from app.models import (
    CashEntry,
    CertificateTemplate,
    Homework,
    HomeworkSubmission,
    Staff,
    StoredFile,
    Student,
    StudyMaterial,
)
from app.models.enums import FilePurpose, ScanStatus

log = logging.getLogger(__name__)
KB = 1024
MB = 1024 * KB


@dataclass(frozen=True)
class Rule:
    types: frozenset[str]
    max_bytes: int
    upload: tuple[str, ...]  # any one of these permissions may upload
    read: tuple[str, ...] = ()  # besides the uploader, any one of these may read


DOCUMENTS = frozenset({ft.PDF, ft.DOCX, ft.PPTX, ft.XLSX, ft.JPEG, ft.PNG})
RULES: dict[FilePurpose, Rule] = {
    FilePurpose.PHOTO: Rule(
        frozenset({ft.JPEG, ft.PNG}), 300 * KB, ("students.update", "staff.manage"), ("students.read", "staff.read")
    ),
    FilePurpose.STUDY_MATERIAL: Rule(DOCUMENTS | {ft.MP3, ft.MP4}, 20 * MB, ("materials.publish",)),
    FilePurpose.HOMEWORK: Rule(DOCUMENTS, 20 * MB, ("homework.manage",)),
    FilePurpose.SUBMISSION: Rule(frozenset({ft.PDF, ft.DOCX, ft.JPEG, ft.PNG}), 10 * MB, ("homework.submit",)),
    FilePurpose.RECEIPT: Rule(frozenset({ft.PDF, ft.JPEG, ft.PNG}), 5 * MB, ("accounts.record",)),
    FilePurpose.CERT_TEMPLATE: Rule(frozenset({ft.JPEG, ft.PNG}), 2 * MB, ("certificates.issue",)),
}


def rule(purpose: FilePurpose, principal: Principal) -> Rule:
    """The purpose's rule, or 403 when this person may not upload for it."""
    r = RULES[purpose]
    if not any(principal.has(p) for p in r.upload):
        raise forbidden()
    return r


def clean_name(name: str | None, ext: str) -> str:
    """A safe display name: no path, no control characters, at most 200 characters, the real extension."""
    base = (name or "").replace("\\", "/").rsplit("/", 1)[-1]
    base = "".join(ch for ch in unicodedata.normalize("NFC", base) if unicodedata.category(ch)[0] != "C")
    stem = re.sub(r"\.[A-Za-z0-9]{1,5}$", "", base).strip(" .") or "file"
    return f"{stem[:190]}.{ext}"


async def save(
    session: AsyncSession, principal: Principal, purpose: FilePurpose, name: str | None, data: bytes
) -> StoredFile:
    r = RULES[purpose]
    mime, ext = ft.detect(data, set(r.types))
    status = await _scan(principal, purpose, data)
    key = f"{principal.school_id}/files/{secrets.token_hex(16)}.{ext}"
    get_storage().put(key, data)
    row = StoredFile(
        school_id=principal.school_id,
        storage_key=key,
        purpose=purpose,
        original_name=clean_name(name, ext),
        content_type=mime,
        size_bytes=len(data),
        sha256=hashlib.sha256(data).hexdigest(),
        scan_status=status,
        created_by=principal.user_id,
    )
    session.add(row)
    return row


async def _scan(principal: Principal, purpose: FilePurpose, data: bytes) -> ScanStatus:
    """Scan before anything is stored: an infected file is refused, and so is any file while the scanner is down."""
    if not scanner.configured():
        return ScanStatus.SKIPPED  # development, or SSMS_ALLOW_UNSCANNED_UPLOADS in production
    try:
        verdict, signature = await scanner.scan(data)
    except scanner.ScannerUnavailable as exc:
        log.error("virus scanner unavailable: %s", exc)
        raise AppError(503, "SCANNER_UNAVAILABLE") from exc
    if verdict == "INFECTED":
        log.warning(
            "infected upload refused: %s (school %s, user %s, %s)",
            signature,
            principal.school_id,
            principal.user_id,
            purpose,
        )
        raise AppError(422, "FILE_INFECTED")
    return ScanStatus.CLEAN


async def get(session: AsyncSession, file_id) -> StoredFile:
    row = (
        await session.execute(select(StoredFile).where(StoredFile.id == file_id, StoredFile.deleted_at.is_(None)))
    ).scalar_one_or_none()
    if row is None:
        raise not_found()
    return row


def may_read(row: StoredFile, principal: Principal) -> bool:
    if row.created_by == principal.user_id:
        return True
    return row.scan_status in (ScanStatus.CLEAN, ScanStatus.SKIPPED) and any(
        principal.has(p) for p in RULES[row.purpose].read
    )


async def open_for(session: AsyncSession, principal: Principal, file_id) -> tuple[StoredFile, bytes]:
    row = await get(session, file_id)
    if not may_read(row, principal):
        raise not_found()  # never reveal that someone else's file exists
    if row.scan_status == ScanStatus.INFECTED:
        raise not_found()
    return row, get_storage().get(row.storage_key)


async def in_use(session: AsyncSession, row: StoredFile) -> bool:
    """Whether any record still points at the file (by id, or by storage key for photographs)."""
    uses = [
        exists().where(StudyMaterial.file_id == row.id),
        exists().where(Homework.file_id == row.id),
        exists().where(HomeworkSubmission.file_id == row.id),
        exists().where(CashEntry.attachment_file_id == row.id),
        exists().where(CertificateTemplate.background_file_id == row.id),
        exists().where(Student.photo_file_key == row.storage_key),
        exists().where(Staff.photo_file_key == row.storage_key),
    ]
    return bool((await session.execute(select(or_(*uses)))).scalar())


async def discard(session: AsyncSession, principal: Principal, file_id) -> None:
    """The uploader removes a file nothing uses: the bytes are deleted, so a file in use is refused."""
    row = await get(session, file_id)
    if row.created_by != principal.user_id:
        raise not_found()
    if await in_use(session, row):
        raise AppError(409, "FILE_IN_USE")
    row.deleted_at = func.now()
    get_storage().delete(row.storage_key)
