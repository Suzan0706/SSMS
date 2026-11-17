"""Bulk import of students (+ primary guardian), guardians and staff from XLSX or CSV.

All-or-nothing: every row is validated first (field rules, classes, duplicates in the file and in the school,
stream capacity). Any error -> nothing is written and an error report (row, column, code, message) is produced.
Otherwise all rows are written in ONE transaction; a database rule that still fails rolls everything back.
"""

import csv
import io
import uuid
from collections import Counter
from dataclasses import dataclass, field
from datetime import UTC, date, datetime

from openpyxl import Workbook, load_workbook
from pydantic import ValidationError
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import Principal, load_access
from app.core import sheets
from app.core.config import get_settings
from app.core.crypto import get_cipher
from app.core.errors import AppError, validation_details
from app.core.i18n import message
from app.core.storage import get_storage
from app.db.session import DbContext, school_session, set_context
from app.models import (
    AcademicYear,
    BackgroundJob,
    Department,
    Designation,
    Enrolment,
    Role,
    SchoolClass,
    Staff,
    Stream,
    Student,
    User,
)
from app.models.enums import EnrolmentStatus, JobKind, JobStatus
from app.schemas.people import GuardianLinkIn, StaffCreateIn, StudentCreateIn
from app.services import sms
from app.services import staff as staff_service
from app.services import students as student_service
from app.tasks.dispatch import get_dispatcher

MAX_ROWS = 2000
KINDS = {"students": JobKind.IMPORT_STUDENTS, "guardians": JobKind.IMPORT_GUARDIANS, "staff": JobKind.IMPORT_STAFF}
PERMISSION = {"students": "students.import", "guardians": "students.import", "staff": "staff.manage"}
YES, NO = {"YES", "Y", "NDIYO", "TRUE", "1"}, {"NO", "N", "HAPANA", "FALSE", "0", ""}

# column, required, example, description (en / sw)
COLUMNS = {
    "students": [
        ("first_name", True, "Juma", "First name / Jina la kwanza"),
        ("middle_name", False, "Ally", "Middle name / Jina la kati"),
        ("last_name", True, "Kombo", "Surname / Jina la ukoo"),
        ("gender", True, "M", "M or F"),
        ("date_of_birth", True, "2012-01-22", "YYYY-MM-DD"),
        ("birth_cert_no", False, "BC-1234-5678", "RITA birth certificate number"),
        ("prem_number", False, "", "PReM number"),
        ("class_code", False, "F1", "Class code (empty = applicant) / Darasa"),
        ("stream_name", False, "A", "Stream name, default A / Mkondo"),
        ("admission_date", False, "2026-01-12", "YYYY-MM-DD, default today"),
        ("guardian_first_name", True, "Ali", "Primary guardian first name"),
        ("guardian_last_name", True, "Kombo", "Primary guardian surname"),
        ("guardian_gender", True, "M", "M or F"),
        ("guardian_phone", True, "0754123456", "07XXXXXXXX or 2557XXXXXXXX"),
        ("guardian_relationship", True, "FATHER", "FATHER, MOTHER, GUARDIAN, SPONSOR, SIBLING, OTHER"),
        ("guardian_sms_consent", True, "YES", "YES / NO: guardian agrees to receive SMS"),
        ("data_processing_consent", True, "YES", "Must be YES (PDPA 2022)"),
    ],
    "guardians": [
        ("admission_no", True, "MF-2025-0040", "Student admission number"),
        ("first_name", True, "Mwanaisha", ""),
        ("middle_name", False, "", ""),
        ("last_name", True, "Hassan", ""),
        ("gender", True, "F", "M or F"),
        ("phone", True, "0715000022", "07XXXXXXXX"),
        ("email", False, "", ""),
        ("occupation", False, "Trader", ""),
        ("relationship", True, "MOTHER", "FATHER, MOTHER, GUARDIAN, SPONSOR, SIBLING, OTHER"),
        ("is_primary", True, "NO", "YES makes this the primary guardian"),
        ("sms_consent", True, "YES", "YES / NO"),
    ],
    "staff": [
        ("first_name", True, "Neema", ""),
        ("middle_name", False, "", ""),
        ("last_name", True, "Laizer", ""),
        ("gender", True, "F", "M or F"),
        ("phone", True, "0754000008", "07XXXXXXXX"),
        ("email", False, "", ""),
        ("staff_no", True, "MF-STF-020", "Unique in the school"),
        ("check_no", False, "", "Government check number"),
        ("department_code", False, "SCI", "Department code"),
        ("designation_code", False, "SUBJECT_TEACHER", ""),
        ("employment_type", False, "PERMANENT", "PERMANENT, CONTRACT, VOLUNTEER, INTERN"),
        ("employment_date", False, "2024-01-08", "YYYY-MM-DD"),
        ("roles", False, "teacher", "Comma separated role codes, default teacher"),
    ],
}


class ImportFileError(Exception):
    def __init__(self, code: str, **params):
        self.code, self.params = code, params


@dataclass
class Plan:
    rows: list[tuple[int, object]] = field(default_factory=list)  # (row number, validated payload)
    errors: list[dict] = field(default_factory=list)  # {row, column, code, message}

    def error(self, row_no: int, column: str, code: str, lang: str, **params) -> None:
        self.errors.append({"row": row_no, "column": column, "code": code, "message": message(code, lang, **params)})


# ---------------------------------------------------------------- files


def template(kind: str) -> bytes:
    wb = Workbook()
    data = wb.active
    data.title = "data"
    data.append([c[0] for c in COLUMNS[kind]])
    data.append([c[2] for c in COLUMNS[kind]])
    help_sheet = wb.create_sheet("help")
    help_sheet.append(["column", "required", "example", "notes"])
    for name, required, example, notes in COLUMNS[kind]:
        help_sheet.append([name, "YES" if required else "NO", example, notes])
    help_sheet.append([])
    help_sheet.append(["Delete the example row. One row per record. Maximum rows:", MAX_ROWS])
    out = io.BytesIO()
    wb.save(out)
    return out.getvalue()


def sniff(data: bytes) -> str:
    if data[:4] == b"PK\x03\x04":
        return "xlsx"
    try:
        data[:4096].decode("utf-8-sig")
    except UnicodeDecodeError:
        raise ImportFileError("FILE_TYPE") from None
    return "csv"


def _cell(value) -> str:
    if value is None:
        return ""
    if isinstance(value, datetime):
        return value.date().isoformat()
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, float) and value.is_integer():
        value = int(value)
    return str(value).strip()


def read_rows(data: bytes) -> tuple[list[str], list[tuple[int, dict[str, str]]]]:
    """(headers, [(row number as shown in Excel, {column: text})]); blank rows are skipped."""
    if sniff(data) == "xlsx":
        try:
            sheet = load_workbook(io.BytesIO(data), read_only=True, data_only=True).worksheets[0]
            grid = [[_cell(v) for v in row] for row in sheet.iter_rows(values_only=True)]
        except Exception:  # corrupt or not really a workbook
            raise ImportFileError("FILE_TYPE") from None
    else:
        grid = [[_cell(v) for v in row] for row in csv.reader(io.StringIO(data.decode("utf-8-sig")))]
    if not grid:
        raise ImportFileError("IMPORT_HEADERS")
    headers = [h.strip().lower() for h in grid[0]]
    rows = [
        (n, dict(zip(headers, values + [""] * (len(headers) - len(values)), strict=False)))
        for n, values in enumerate(grid[1:], start=2)
        if any(values)
    ]
    return headers, rows


def check_headers(kind: str, headers: list[str]) -> None:
    known = {c[0] for c in COLUMNS[kind]}
    required = {c[0] for c in COLUMNS[kind] if c[1]}
    present = {h for h in headers if h}
    if not required <= present or present - known:
        raise ImportFileError("IMPORT_HEADERS", missing=sorted(required - present), unknown=sorted(present - known))


def report(errors: list[dict]) -> bytes:
    wb = Workbook()
    sheet = wb.active
    sheet.title = "errors"
    sheet.append(["row", "column", "code", "message"])
    for e in sorted(errors, key=lambda e: (e["row"], e["column"])):
        sheets.append(sheet, [e["row"], e["column"], e["code"], e["message"]])
    out = io.BytesIO()
    wb.save(out)
    return out.getvalue()


def result_file(headers: list[str], rows: list[list]) -> bytes:
    wb = Workbook()
    sheet = wb.active
    sheet.title = "result"
    sheet.append(headers)
    for row in rows:
        sheets.append(sheet, row)
    out = io.BytesIO()
    wb.save(out)
    return out.getvalue()


# ---------------------------------------------------------------- validation


def _flag(value: str) -> bool | None:
    upper = value.strip().upper()
    return True if upper in YES else False if upper in NO else None


def _blank(value: str) -> str | None:
    return value or None


def _record_errors(plan: Plan, row: int, exc: ValidationError, lang: str, columns: dict[str, str]) -> None:
    for d in validation_details(exc.errors(), lang):
        column = columns.get(d["field"], d["field"])
        if d["code"] == "student_age":
            column = "date_of_birth"
        plan.error(row, column, d["code"], lang)


async def _streams(session: AsyncSession) -> dict[tuple[str, str], uuid.UUID]:
    rows = await session.execute(
        select(SchoolClass.code, Stream.name, Stream.id)
        .join(Stream, Stream.class_id == SchoolClass.id)
        .where(Stream.deleted_at.is_(None), SchoolClass.deleted_at.is_(None))
    )
    return {(c.upper(), s.upper()): sid for c, s, sid in rows}


async def _remaining_capacity(session: AsyncSession, stream_ids: set[uuid.UUID]) -> dict[uuid.UUID, int]:
    if not stream_ids:
        return {}
    used = dict(
        (
            await session.execute(
                select(Enrolment.stream_id, func.count())
                .join(AcademicYear, AcademicYear.id == Enrolment.academic_year_id)
                .where(
                    Enrolment.stream_id.in_(stream_ids),
                    Enrolment.status == EnrolmentStatus.ACTIVE,
                    AcademicYear.is_current,
                )
                .group_by(Enrolment.stream_id)
            )
        ).all()
    )
    capacity = dict((await session.execute(select(Stream.id, Stream.capacity).where(Stream.id.in_(stream_ids)))).all())
    return {sid: capacity[sid] - used.get(sid, 0) for sid in stream_ids}


async def plan_students(session: AsyncSession, rows, lang: str) -> Plan:
    plan, streams, cipher = Plan(), await _streams(session), get_cipher()
    columns = {
        "guardians.0.first_name": "guardian_first_name",
        "guardians.0.last_name": "guardian_last_name",
        "guardians.0.gender": "guardian_gender",
        "guardians.0.phone": "guardian_phone",
        "guardians.0.relationship": "guardian_relationship",
        "guardians.0": "guardian_phone",
        "consent_data_processing": "data_processing_consent",
        "body": "data_processing_consent",
    }
    first_seen: dict[str, int] = {}
    for n, r in rows:
        stream_id = None
        if r.get("class_code"):
            stream_id = streams.get((r["class_code"].upper(), (r.get("stream_name") or "A").upper()))
            if stream_id is None:
                plan.error(n, "class_code", "unknown_class", lang)
                continue
        sms_ok, consent = _flag(r.get("guardian_sms_consent", "")), _flag(r.get("data_processing_consent", ""))
        if sms_ok is None:
            plan.error(n, "guardian_sms_consent", "invalid_value", lang)
            continue
        try:
            payload = StudentCreateIn.model_validate(
                {
                    "first_name": r["first_name"],
                    "middle_name": _blank(r.get("middle_name", "")),
                    "last_name": r["last_name"],
                    "gender": r["gender"].upper(),
                    "date_of_birth": r["date_of_birth"],
                    "birth_cert_no": _blank(r.get("birth_cert_no", "")),
                    "prem_number": _blank(r.get("prem_number", "")),
                    "admission_date": _blank(r.get("admission_date", "")),
                    "stream_id": stream_id,
                    "consent_data_processing": bool(consent),
                    "guardians": [
                        {
                            "first_name": r["guardian_first_name"],
                            "last_name": r["guardian_last_name"],
                            "gender": r["guardian_gender"].upper(),
                            "phone": r["guardian_phone"],
                            "relationship": r["guardian_relationship"].upper(),
                            "is_primary": True,
                            "sms_consent": sms_ok,
                        }
                    ],
                }
            )
        except ValidationError as exc:
            _record_errors(plan, n, exc, lang, columns)
            continue
        if payload.birth_cert_no:
            if payload.birth_cert_no in first_seen:
                plan.error(n, "birth_cert_no", "duplicate_in_file", lang, row=first_seen[payload.birth_cert_no])
                continue
            first_seen[payload.birth_cert_no] = n
        plan.rows.append((n, payload))

    certificates = {
        cipher.blind_index(p.birth_cert_no, student_service.BIRTH_CERT): n for n, p in plan.rows if p.birth_cert_no
    }
    if certificates:
        taken = set(
            (
                await session.execute(
                    select(Student.birth_cert_no_hash).where(
                        Student.birth_cert_no_hash.in_(list(certificates)), Student.deleted_at.is_(None)
                    )
                )
            ).scalars()
        )
        for digest in taken:
            plan.error(certificates[digest], "birth_cert_no", "duplicate_in_school", lang)
    wanted = Counter(p.stream_id for _, p in plan.rows if p.stream_id)
    remaining = await _remaining_capacity(session, set(wanted))
    for n, p in plan.rows:
        if p.stream_id:
            remaining[p.stream_id] -= 1
            if remaining[p.stream_id] < 0:
                plan.error(n, "class_code", "stream_full", lang)
    return plan


async def plan_guardians(session: AsyncSession, rows, lang: str) -> Plan:
    plan = Plan()
    numbers = {r.get("admission_no", "").upper() for _, r in rows}
    students = dict(
        (
            await session.execute(
                select(Student.admission_no, Student.id).where(
                    Student.admission_no.in_(numbers), Student.deleted_at.is_(None)
                )
            )
        ).all()
    )
    seen: dict[tuple[str, str], int] = {}
    for n, r in rows:
        student_id = students.get(r.get("admission_no", "").upper())
        if student_id is None:
            plan.error(n, "admission_no", "unknown_student", lang)
            continue
        primary, sms_ok = _flag(r.get("is_primary", "")), _flag(r.get("sms_consent", ""))
        if primary is None or sms_ok is None:
            plan.error(n, "is_primary" if primary is None else "sms_consent", "invalid_value", lang)
            continue
        try:
            link = GuardianLinkIn.model_validate(
                {
                    "first_name": r["first_name"],
                    "middle_name": _blank(r.get("middle_name", "")),
                    "last_name": r["last_name"],
                    "gender": r["gender"].upper(),
                    "phone": r["phone"],
                    "email": _blank(r.get("email", "")),
                    "occupation": _blank(r.get("occupation", "")),
                    "relationship": r["relationship"].upper(),
                    "is_primary": primary,
                    "sms_consent": sms_ok,
                }
            )
        except ValidationError as exc:
            _record_errors(plan, n, exc, lang, {"body": "phone"})
            continue
        key = (str(student_id), link.phone)
        if key in seen:
            plan.error(n, "phone", "duplicate_in_file", lang, row=seen[key])
            continue
        seen[key] = n
        plan.rows.append((n, (student_id, link)))
    return plan


async def plan_staff(session: AsyncSession, principal: Principal, rows, lang: str) -> Plan:
    plan, cipher = Plan(), get_cipher()
    departments = dict(
        (await session.execute(select(Department.code, Department.id).where(Department.deleted_at.is_(None)))).all()
    )
    designations = dict(
        (await session.execute(select(Designation.code, Designation.id).where(Designation.deleted_at.is_(None)))).all()
    )
    known_roles = set((await session.execute(select(Role.code))).scalars())
    columns = {f"person.{f}": f for f in ("first_name", "middle_name", "last_name", "gender", "phone", "email")}
    staff_nos: dict[str, int] = {}
    phones: dict[str, int] = {}
    for n, r in rows:
        roles = [x.strip().lower() for x in (r.get("roles") or "teacher").split(",") if x.strip()]
        unknown = [x for x in roles if x not in known_roles or x in ("parent", "student")]
        dept, desig = r.get("department_code", "").upper(), r.get("designation_code", "").upper()
        if unknown:
            plan.error(n, "roles", "unknown_role", lang)
        elif set(roles) - {"teacher"} and not principal.has("roles.assign"):
            plan.error(n, "roles", "invalid_value", lang)
        elif dept and dept not in departments:
            plan.error(n, "department_code", "unknown_department", lang)
        elif desig and desig not in designations:
            plan.error(n, "designation_code", "unknown_designation", lang)
        else:
            try:
                payload = StaffCreateIn.model_validate(
                    {
                        "person": {
                            "first_name": r["first_name"],
                            "middle_name": _blank(r.get("middle_name", "")),
                            "last_name": r["last_name"],
                            "gender": r["gender"].upper(),
                            "phone": r["phone"],
                            "email": _blank(r.get("email", "")),
                        },
                        "staff_no": r["staff_no"],
                        "check_no": _blank(r.get("check_no", "")),
                        "department_id": departments.get(dept),
                        "designation_id": designations.get(desig),
                        "employment_type": (r.get("employment_type") or "PERMANENT").upper(),
                        "employment_date": _blank(r.get("employment_date", "")),
                        "roles": roles,
                    }
                )
            except ValidationError as exc:
                _record_errors(plan, n, exc, lang, columns)
                continue
            if payload.staff_no.upper() in staff_nos:
                plan.error(n, "staff_no", "duplicate_in_file", lang, row=staff_nos[payload.staff_no.upper()])
            elif payload.person.phone in phones:
                plan.error(n, "phone", "duplicate_in_file", lang, row=phones[payload.person.phone])
            else:
                staff_nos[payload.staff_no.upper()] = phones[payload.person.phone] = n
                plan.rows.append((n, payload))

    by_no = {p.staff_no.upper(): n for n, p in plan.rows}
    for existing in (
        await session.execute(
            select(func.upper(Staff.staff_no)).where(
                func.upper(Staff.staff_no).in_(list(by_no)), Staff.deleted_at.is_(None)
            )
        )
    ).scalars():
        plan.error(by_no[existing], "staff_no", "duplicate_in_school", lang)
    by_phone = {cipher.blind_index(p.person.phone, sms.PHONE_FIELD): n for n, p in plan.rows}
    for digest in (
        await session.execute(
            select(User.phone_hash).where(User.phone_hash.in_(list(by_phone)), User.deleted_at.is_(None))
        )
    ).scalars():
        plan.error(by_phone[digest], "phone", "duplicate_in_school", lang)
    return plan


# ---------------------------------------------------------------- the job


async def _principal(session: AsyncSession, job: BackgroundJob) -> Principal:
    user = (
        await session.execute(select(User.preferred_language, User.status).where(User.id == job.requested_by))
    ).one()
    roles, permissions = await load_access(session, job.requested_by)
    return Principal(
        user_id=job.requested_by,
        school_id=job.school_id,
        language=user.preferred_language,
        must_change_password=False,
        roles=roles,
        permissions=permissions,
    )


def finish_job(job: BackgroundJob, status: JobStatus, errors: int = 0) -> None:
    job.status, job.error_count, job.finished_at = status, errors, datetime.now(UTC)
    job.progress_pct = 100


async def fail_job(session: AsyncSession, job: BackgroundJob, errors: list[dict]) -> str:
    key = f"{job.school_id}/imports/{job.id}/errors.xlsx"
    get_storage().put(key, report(errors))
    job.error_report_file_key = key
    finish_job(job, JobStatus.FAILED, len({e["row"] for e in errors}))
    await session.commit()
    return "failed"


async def _load_job(session: AsyncSession, job_id: uuid.UUID) -> BackgroundJob | None:
    return (
        await session.execute(select(BackgroundJob).where(BackgroundJob.id == job_id).with_for_update())
    ).scalar_one_or_none()


async def run_job(job_id: str, school_id: str) -> str:
    """Celery entry point. Idempotent: a job that is not QUEUED is left alone."""
    job_uuid, school_uuid = uuid.UUID(job_id), uuid.UUID(school_id)
    async with school_session(school_uuid) as session:
        job = await _load_job(session, job_uuid)
        if job is None or job.status != JobStatus.QUEUED:
            return "skipped"
        job.status, job.started_at = JobStatus.RUNNING, datetime.now(UTC)
        await session.commit()
        await set_context(session, DbContext(school_id=school_uuid, user_id=job.requested_by))
        principal = await _principal(session, job)
        lang = principal.language
        kind = next(k for k, v in KINDS.items() if v == job.kind)
        if not principal.has(PERMISSION[kind]):
            return await fail_job(
                session, job, [{"row": 1, "column": "", "code": "FORBIDDEN", "message": message("FORBIDDEN", lang)}]
            )
        try:
            headers, rows = read_rows(get_storage().get(job.input_file_key))
            check_headers(kind, headers)
            if len(rows) > MAX_ROWS:
                raise ImportFileError("too_many_rows", limit=MAX_ROWS)
        except ImportFileError as exc:
            return await fail_job(
                session,
                job,
                [
                    {
                        "row": 1,
                        "column": ", ".join(exc.params.get("missing", [])),
                        "code": exc.code,
                        "message": message(exc.code, lang, **exc.params),
                    }
                ],
            )
        job.total_items = len(rows)
        if kind == "students":
            plan = await plan_students(session, rows, lang)
        elif kind == "guardians":
            plan = await plan_guardians(session, rows, lang)
        else:
            plan = await plan_staff(session, principal, rows, lang)
        if plan.errors:
            return await fail_job(session, job, plan.errors)
        if not plan.rows:
            return await fail_job(
                session, job, [{"row": 1, "column": "", "code": "required", "message": message("required", lang)}]
            )

        current_row, results, calls = 0, [], []
        try:
            for current_row, payload in plan.rows:
                if kind == "students":
                    student_id = await student_service.admit(session, principal, payload, commit=False)
                    number = (
                        await session.execute(select(Student.admission_no).where(Student.id == student_id))
                    ).scalar()
                    results.append([current_row, str(student_id), number])
                elif kind == "guardians":
                    student_id, link = payload
                    guardian = await student_service.link_guardian(session, principal, student_id, link)
                    results.append([current_row, str(student_id), str(guardian.id)])
                else:
                    staff_id, _, call = await staff_service.create_staff(session, principal, payload, commit=False)
                    calls.append(call)
                    username = (
                        await session.execute(
                            select(User.username).join(Staff, Staff.user_id == User.id).where(Staff.id == staff_id)
                        )
                    ).scalar()
                    results.append([current_row, str(staff_id), username])
            await session.flush()
        except (AppError, IntegrityError) as exc:
            await session.rollback()
            job = await _load_job(session, job_uuid)
            code = exc.error_code if isinstance(exc, AppError) else "RULE_VIOLATION"
            return await fail_job(
                session, job, [{"row": current_row, "column": "", "code": code, "message": message(code, lang)}]
            )
        key = f"{job.school_id}/imports/{job.id}/result.xlsx"
        heading = {"students": "admission_no", "guardians": "guardian_id", "staff": "username"}[kind]
        get_storage().put(key, result_file(["row", "id", heading], results))
        job.result_file_key, job.processed_items = key, len(results)
        finish_job(job, JobStatus.SUCCEEDED)
        await session.commit()
    for call in calls:  # account SMS only after the commit
        get_dispatcher().send("sms.send", **call)
    return "succeeded"


def max_bytes() -> int:
    return get_settings().max_import_bytes
