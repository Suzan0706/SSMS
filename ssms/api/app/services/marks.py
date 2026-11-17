"""Draft marks: who may enter them, the sheet, offline batch sync with optimistic versions, Excel upload.

Marks stay drafts until the class is published; publication locks them (fn_mark_entries_guard refuses changes).
A device sends the version its edit was based on; a different server version means somebody else changed the mark
meanwhile, so the item is returned as a conflict with the server value instead of overwriting it.
"""

import hashlib
import io
import json
import uuid
from datetime import UTC, datetime
from decimal import Decimal, InvalidOperation

from openpyxl import Workbook
from sqlalchemy import or_, select
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import Principal, load_access
from app.core.errors import AppError, forbidden
from app.core.i18n import message
from app.core.storage import get_storage
from app.db.session import DbContext, school_session, set_context
from app.models import (
    AssessmentComponent,
    BackgroundJob,
    ClassSubject,
    CombinationSubject,
    Enrolment,
    MarkEntry,
    SchoolClass,
    Staff,
    Stream,
    Student,
    TeachingAssignment,
    Term,
    User,
)
from app.models.enums import EnrolmentStatus, JobStatus
from app.schemas.marks import (
    BatchOut,
    ItemResult,
    MarkItem,
    ServerMark,
    SheetComponent,
    SheetMark,
    SheetOut,
    SheetStudent,
)
from app.services import crud, imports

ABSENT = {"ABS", "AB", "X", "HAKUFIKA"}


async def may_enter(
    session: AsyncSession, principal: Principal, term: Term, stream_id: uuid.UUID, subject_id: uuid.UUID
) -> bool:
    """Head teacher / academic office (results.publish) for every class; otherwise the assigned teacher only."""
    if principal.has("results.publish"):
        return True
    if not principal.has("marks.enter"):
        return False
    return bool(
        (
            await session.execute(
                select(TeachingAssignment.id)
                .join(Staff, Staff.id == TeachingAssignment.staff_id)
                .where(
                    TeachingAssignment.academic_year_id == term.academic_year_id,
                    TeachingAssignment.stream_id == stream_id,
                    TeachingAssignment.subject_id == subject_id,
                    TeachingAssignment.deleted_at.is_(None),
                    Staff.user_id == principal.user_id,
                )
            )
        ).first()
    )


async def components_for(
    session: AsyncSession, term_id: uuid.UUID, level_id: uuid.UUID, subject_id: uuid.UUID
) -> list[AssessmentComponent]:
    """Subject-specific components replace the level-wide set (same rule as results_scope)."""
    rows = list(
        (
            await session.execute(
                select(AssessmentComponent)
                .where(
                    AssessmentComponent.term_id == term_id,
                    AssessmentComponent.education_level_id == level_id,
                    AssessmentComponent.deleted_at.is_(None),
                    or_(AssessmentComponent.subject_id == subject_id, AssessmentComponent.subject_id.is_(None)),
                )
                .order_by(AssessmentComponent.code)
            )
        ).scalars()
    )
    specific = [c for c in rows if c.subject_id == subject_id]
    return specific or [c for c in rows if c.subject_id is None]


async def _students(session: AsyncSession, term: Term, stream: Stream, subject_id: uuid.UUID) -> list:
    """Active enrolments of the stream that take the subject (class curriculum, or their combination)."""
    in_class = (
        await session.execute(
            select(ClassSubject.id).where(
                ClassSubject.class_id == stream.class_id,
                ClassSubject.subject_id == subject_id,
                ClassSubject.deleted_at.is_(None),
            )
        )
    ).first()
    stmt = (
        select(Enrolment.id, Student.admission_no, User.first_name, User.middle_name, User.last_name)
        .join(Student, Student.id == Enrolment.student_id)
        .join(User, User.id == Student.user_id)
        .where(
            Enrolment.stream_id == stream.id,
            Enrolment.academic_year_id == term.academic_year_id,
            Enrolment.status == EnrolmentStatus.ACTIVE,
        )
    )
    if not in_class:
        stmt = stmt.join(
            CombinationSubject,
            (CombinationSubject.combination_id == Enrolment.combination_id)
            & (CombinationSubject.subject_id == subject_id)
            & CombinationSubject.deleted_at.is_(None),
        )
    return (await session.execute(stmt.order_by(User.last_name, User.first_name))).all()


async def sheet(
    session: AsyncSession, principal: Principal, term_id: uuid.UUID, stream_id: uuid.UUID, subject_id: uuid.UUID
) -> SheetOut:
    term = await crud.get_live(session, Term, term_id)
    stream = await crud.get_live(session, Stream, stream_id)
    if not await may_enter(session, principal, term, stream_id, subject_id):
        raise forbidden()
    level_id = (
        await session.execute(select(SchoolClass.education_level_id).where(SchoolClass.id == stream.class_id))
    ).scalar()
    components = await components_for(session, term.id, level_id, subject_id)
    students = await _students(session, term, stream, subject_id)
    marks = (
        (
            await session.execute(
                select(MarkEntry).where(
                    MarkEntry.enrolment_id.in_([s.id for s in students]),
                    MarkEntry.subject_id == subject_id,
                    MarkEntry.component_id.in_([c.id for c in components]),
                    MarkEntry.deleted_at.is_(None),
                )
            )
        )
        .scalars()
        .all()
    )
    by_key = {(m.enrolment_id, m.component_id): m for m in marks}
    out_students = []
    for s in students:
        entries = {}
        for c in components:
            m = by_key.get((s.id, c.id))
            if m:
                entries[str(c.id)] = SheetMark(
                    score=m.score, is_absent=m.is_absent, version=m.version, locked=m.locked_at is not None
                )
        out_students.append(
            SheetStudent(
                enrolment_id=s.id,
                admission_no=s.admission_no,
                marks=entries,
                full_name=" ".join(p for p in (s.first_name, s.middle_name, s.last_name) if p),
            )
        )
    return SheetOut(
        term_id=term.id,
        stream_id=stream.id,
        subject_id=subject_id,
        locked=any(m.locked_at is not None for m in marks),
        components=[SheetComponent.model_validate(c, from_attributes=True) for c in components],
        students=out_students,
    )


def sheet_etag(out: SheetOut) -> str:
    return 'W/"' + hashlib.sha256(out.model_dump_json().encode()).hexdigest()[:32] + '"'


class _Scope:
    """Caches what one batch needs to know about enrolments, components and permissions."""

    def __init__(self, session: AsyncSession, principal: Principal):
        self.session, self.principal = session, principal
        self.enrolments: dict[uuid.UUID, tuple | None] = {}
        self.components: dict[uuid.UUID, AssessmentComponent | None] = {}
        self.allowed: dict[tuple, bool] = {}
        self.applicable: dict[tuple, set] = {}

    async def enrolment(self, enrolment_id: uuid.UUID):
        if enrolment_id not in self.enrolments:
            self.enrolments[enrolment_id] = (
                await self.session.execute(
                    select(Enrolment.stream_id, Enrolment.academic_year_id, SchoolClass.education_level_id)
                    .join(Stream, Stream.id == Enrolment.stream_id)
                    .join(SchoolClass, SchoolClass.id == Stream.class_id)
                    .where(Enrolment.id == enrolment_id, Enrolment.status == EnrolmentStatus.ACTIVE)
                )
            ).first()
        return self.enrolments[enrolment_id]

    async def component(self, component_id: uuid.UUID):
        if component_id not in self.components:
            self.components[component_id] = (
                await self.session.execute(
                    select(AssessmentComponent).where(
                        AssessmentComponent.id == component_id, AssessmentComponent.deleted_at.is_(None)
                    )
                )
            ).scalar_one_or_none()
        return self.components[component_id]

    async def check(self, item: MarkItem) -> str | None:
        """None when the caller may write this mark, else an error code."""
        enrolment = await self.enrolment(item.enrolment_id)
        component = await self.component(item.component_id)
        if enrolment is None or component is None:
            return "invalid_reference"
        stream_id, year_id, level_id = enrolment
        term = await crud.get_live(self.session, Term, component.term_id)
        if term.academic_year_id != year_id:
            return "invalid_reference"
        key = (stream_id, item.subject_id, term.id)
        if key not in self.allowed:
            self.allowed[key] = await may_enter(self.session, self.principal, term, stream_id, item.subject_id)
        if not self.allowed[key]:
            return "forbidden"
        applicable_key = (term.id, level_id, item.subject_id)
        if applicable_key not in self.applicable:
            self.applicable[applicable_key] = {
                c.id for c in await components_for(self.session, term.id, level_id, item.subject_id)
            }
        if component.id not in self.applicable[applicable_key]:
            return "not_applicable"
        if item.score is not None and item.score > component.max_score:
            return "out_of_range"
        return None


async def save_batch(
    session: AsyncSession, principal: Principal, items: list[MarkItem], all_or_nothing: bool = False
) -> BatchOut:
    """Per-item results for device sync; all_or_nothing=True (Excel upload) keeps nothing when one item fails."""
    scope, results = _Scope(session, principal), []
    for index, item in enumerate(items):
        problem = await scope.check(item)
        if problem:
            results.append(ItemResult(index=index, status="error", error_code=problem))
            continue
        current = (
            await session.execute(
                select(MarkEntry)
                .where(
                    MarkEntry.enrolment_id == item.enrolment_id,
                    MarkEntry.subject_id == item.subject_id,
                    MarkEntry.component_id == item.component_id,
                    MarkEntry.deleted_at.is_(None),
                )
                .with_for_update()
            )
        ).scalar_one_or_none()
        server = (
            ServerMark(score=current.score, is_absent=current.is_absent, version=current.version) if current else None
        )
        if current is not None and current.locked_at is not None:
            results.append(ItemResult(index=index, status="error", error_code="locked", server=server))
            continue
        if current is not None and item.version != current.version:
            if (current.score, current.is_absent) == (item.score, item.is_absent):
                results.append(ItemResult(index=index, status="ok", version=current.version))  # same value: no-op
            else:
                results.append(ItemResult(index=index, status="conflict", server=server))
            continue
        try:
            async with session.begin_nested():
                if current is None:
                    current = MarkEntry(
                        school_id=principal.school_id,
                        enrolment_id=item.enrolment_id,
                        subject_id=item.subject_id,
                        component_id=item.component_id,
                        score=item.score,
                        is_absent=item.is_absent,
                        entered_by=principal.user_id,
                        client_updated_at=item.client_updated_at,
                        created_by=principal.user_id,
                    )
                    session.add(current)
                else:
                    current.score, current.is_absent = item.score, item.is_absent
                    current.entered_by, current.client_updated_at = principal.user_id, item.client_updated_at
                await session.flush()
            await session.refresh(current, ["version"])  # the trigger increments it
            results.append(ItemResult(index=index, status="ok", version=current.version))
        except DBAPIError as exc:
            code = {"23514": "out_of_range", "P0001": "locked", "23505": "conflict"}.get(
                getattr(exc.orig, "sqlstate", None), "invalid_value"
            )
            results.append(ItemResult(index=index, status="error", error_code=code))
    if all_or_nothing and any(r.status != "ok" for r in results):
        await session.rollback()
    else:
        await session.commit()
    return BatchOut(
        saved=sum(r.status == "ok" for r in results),
        conflicts=sum(r.status == "conflict" for r in results),
        errors=sum(r.status == "error" for r in results),
        results=results,
    )


# ---------------------------------------------------------------- Excel template and upload


async def template(
    session: AsyncSession, principal: Principal, term_id: uuid.UUID, stream_id: uuid.UUID, subject_id: uuid.UUID
) -> bytes:
    current = await sheet(session, principal, term_id, stream_id, subject_id)
    wb = Workbook()
    ws = wb.active
    ws.title = "marks"
    ws.append(["admission_no", "full_name"] + [c.code for c in current.components])
    for s in current.students:
        row = [s.admission_no, s.full_name]
        for c in current.components:
            mark = s.marks.get(str(c.id))
            row.append(
                "ABS" if mark and mark.is_absent else (float(mark.score) if mark and mark.score is not None else None)
            )
        ws.append(row)
    info = wb.create_sheet("help")
    info.append(["component", "max_score", "weight"])
    for c in current.components:
        info.append([c.code, float(c.max_score), float(c.weight)])
    info.append([])
    info.append(["Empty cell = unchanged. ABS = absent. Scores may have 2 decimals."])
    out = io.BytesIO()
    wb.save(out)
    return out.getvalue()


def params_key(school_id: uuid.UUID, job_id: uuid.UUID) -> str:
    return f"{school_id}/marks/{job_id}/params.json"


async def run_upload(job_id: str, school_id: str) -> str:
    """IMPORT_MARKS job: every cell is validated first; any error -> nothing saved and an error report."""
    job_uuid, school_uuid = uuid.UUID(job_id), uuid.UUID(school_id)
    async with school_session(school_uuid) as session:
        job = (
            await session.execute(select(BackgroundJob).where(BackgroundJob.id == job_uuid).with_for_update())
        ).scalar_one_or_none()
        if job is None or job.status != JobStatus.QUEUED:
            return "skipped"
        job.status, job.started_at = JobStatus.RUNNING, datetime.now(UTC)
        await session.commit()
        await set_context(session, DbContext(school_id=school_uuid, user_id=job.requested_by))
        lang = (await session.execute(select(User.preferred_language).where(User.id == job.requested_by))).scalar()
        roles, permissions = await load_access(session, job.requested_by)
        principal = Principal(
            user_id=job.requested_by,
            school_id=school_uuid,
            language=lang,
            must_change_password=False,
            roles=roles,
            permissions=permissions,
        )
        params = json.loads(get_storage().get(params_key(school_uuid, job.id)))
        try:
            current = await sheet(
                session,
                principal,
                uuid.UUID(params["term_id"]),
                uuid.UUID(params["stream_id"]),
                uuid.UUID(params["subject_id"]),
            )
        except AppError as exc:
            return await imports.fail_job(
                session,
                job,
                [{"row": 1, "column": "", "code": exc.error_code, "message": message(exc.error_code, lang)}],
            )
        headers, rows = imports.read_rows(get_storage().get(job.input_file_key))
        components = {c.code: c for c in current.components}
        students = {s.admission_no.upper(): s for s in current.students}
        errors, items = [], []
        missing = [c for c in ("admission_no", *components) if c.lower() not in headers]
        if missing:
            return await imports.fail_job(
                session,
                job,
                [
                    {
                        "row": 1,
                        "column": ", ".join(missing),
                        "code": "IMPORT_HEADERS",
                        "message": message("IMPORT_HEADERS", lang),
                    }
                ],
            )
        for n, row in rows:
            student = students.get(row.get("admission_no", "").upper())
            if student is None:
                errors.append(
                    {
                        "row": n,
                        "column": "admission_no",
                        "code": "unknown_student",
                        "message": message("unknown_student", lang),
                    }
                )
                continue
            for code, component in components.items():
                raw = row.get(code.lower(), "").strip()
                if not raw:
                    continue
                existing = student.marks.get(str(component.id))
                if existing and existing.locked:
                    errors.append(
                        {
                            "row": n,
                            "column": code,
                            "code": "results_published",
                            "message": message("results_published", lang),
                        }
                    )
                    continue
                if raw.upper() in ABSENT:
                    score, absent = None, True
                else:
                    try:
                        score, absent = Decimal(raw.replace(",", ".")).quantize(Decimal("0.01")), False
                    except InvalidOperation:
                        errors.append(
                            {
                                "row": n,
                                "column": code,
                                "code": "invalid_value",
                                "message": message("invalid_value", lang),
                            }
                        )
                        continue
                    if not 0 <= score <= component.max_score:
                        errors.append(
                            {
                                "row": n,
                                "column": code,
                                "code": "out_of_range",
                                "message": message("out_of_range", lang, max=component.max_score),
                            }
                        )
                        continue
                items.append(
                    MarkItem(
                        enrolment_id=student.enrolment_id,
                        subject_id=current.subject_id,
                        component_id=component.id,
                        score=score,
                        is_absent=absent,
                        version=existing.version if existing else 0,
                    )
                )
        job.total_items = len(items)
        if errors:
            return await imports.fail_job(session, job, errors)
        outcome = await save_batch(session, principal, items, all_or_nothing=True)
        job = (await session.execute(select(BackgroundJob).where(BackgroundJob.id == job_uuid))).scalar_one()
        if outcome.errors or outcome.conflicts:  # somebody changed marks meanwhile: report them
            bad = [
                {"row": 1, "column": "", "code": r.error_code or "conflict", "message": r.error_code or "conflict"}
                for r in outcome.results
                if r.status != "ok"
            ]
            return await imports.fail_job(session, job, bad)
        job.processed_items = outcome.saved
        imports.finish_job(job, JobStatus.SUCCEEDED)
        await session.commit()
    return "succeeded"
