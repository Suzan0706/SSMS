"""End-of-year promotion as one all-or-nothing background job.

Every ACTIVE enrolment of the old year moves on: repeaters stay in their stream, others go to the stream with
the same name in the next class (or its first stream), and students of a final class graduate. Nothing is written
when any student cannot be placed; the database capacity trigger is the last check.
"""

import json
import uuid
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import Principal
from app.core.errors import AppError
from app.core.i18n import message
from app.core.storage import get_storage
from app.db.session import DbContext, school_session, set_context
from app.models import AcademicYear, BackgroundJob, Enrolment, SchoolClass, Stream, Student, StudentStatusHistory, User
from app.models.enums import EnrolmentStatus, JobKind, JobStatus, StudentStatus
from app.schemas.enrolment import PromotionIn
from app.services import imports


def params_key(school_id: uuid.UUID, job_id: uuid.UUID) -> str:
    return f"{school_id}/promotions/{job_id}/params.json"


def store_params(principal: Principal, job: BackgroundJob, body: PromotionIn) -> None:
    job.input_file_key = get_storage().put(
        params_key(principal.school_id, job.id), body.model_dump_json().encode("utf-8")
    )


async def _plan(session: AsyncSession, body: PromotionIn, lang: str):
    years = {
        y.id: y
        for y in (
            await session.execute(
                select(AcademicYear).where(AcademicYear.id.in_([body.academic_year_from, body.academic_year_to]))
            )
        ).scalars()
    }
    if len(years) != 2 or years[body.academic_year_to].start_date <= years[body.academic_year_from].start_date:
        return None, [
            {"row": 1, "column": "academic_year_to", "code": "invalid_value", "message": message("invalid_value", lang)}
        ]
    old_year, new_year = years[body.academic_year_from], years[body.academic_year_to]
    stmt = (
        select(Enrolment, Stream.name.label("stream_name"), SchoolClass, Student.admission_no)
        .join(Stream, Stream.id == Enrolment.stream_id)
        .join(SchoolClass, SchoolClass.id == Stream.class_id)
        .join(Student, Student.id == Enrolment.student_id)
        .where(Enrolment.academic_year_id == old_year.id, Enrolment.status == EnrolmentStatus.ACTIVE)
        .order_by(SchoolClass.sort_order, Student.admission_no)
    )
    if body.class_id:
        stmt = stmt.where(SchoolClass.id == body.class_id)
    rows = (await session.execute(stmt.with_for_update(of=Enrolment))).all()
    streams: dict[uuid.UUID, list[Stream]] = {}
    for s in (await session.execute(select(Stream).where(Stream.deleted_at.is_(None)).order_by(Stream.name))).scalars():
        streams.setdefault(s.class_id, []).append(s)
    already = set(
        (await session.execute(select(Enrolment.student_id).where(Enrolment.academic_year_id == new_year.id))).scalars()
    )
    repeaters, plan, errors = set(body.repeaters), [], []
    for n, (enrolment, stream_name, school_class, admission_no) in enumerate(rows, start=2):
        if enrolment.student_id in already:
            errors.append(
                {
                    "row": n,
                    "column": admission_no,
                    "code": "duplicate_in_school",
                    "message": message("duplicate_in_school", lang),
                }
            )
            continue
        if enrolment.student_id in repeaters:
            plan.append((enrolment, admission_no, "REPEATED", enrolment.stream_id))
        elif school_class.next_class_id is None:
            plan.append((enrolment, admission_no, "GRADUATED", None))
        else:
            options = streams.get(school_class.next_class_id, [])
            target = next((s for s in options if s.name == stream_name), options[0] if options else None)
            if target is None:
                errors.append(
                    {
                        "row": n,
                        "column": admission_no,
                        "code": "unknown_class",
                        "message": message("unknown_class", lang),
                    }
                )
                continue
            plan.append((enrolment, admission_no, "PROMOTED", target.id))
    return (old_year, new_year, plan), errors


async def _apply(session: AsyncSession, job: BackgroundJob, old_year, new_year, plan) -> list[list]:
    results = []
    for enrolment, admission_no, outcome, stream_id in plan:
        enrolment.status, enrolment.ended_on = EnrolmentStatus(outcome), old_year.end_date
        if outcome == "GRADUATED":
            student = (
                await session.execute(select(Student).where(Student.id == enrolment.student_id).with_for_update())
            ).scalar_one()
            session.add(
                StudentStatusHistory(
                    school_id=job.school_id,
                    student_id=student.id,
                    old_status=student.status,
                    new_status=StudentStatus.GRADUATED,
                    reason="Completed the final class",
                    effective_date=old_year.end_date,
                    created_by=job.requested_by,
                )
            )
            student.status = StudentStatus.GRADUATED
        else:
            session.add(
                Enrolment(
                    school_id=job.school_id,
                    student_id=enrolment.student_id,
                    stream_id=stream_id,
                    academic_year_id=new_year.id,
                    combination_id=enrolment.combination_id,
                    status=EnrolmentStatus.ACTIVE,
                    started_on=new_year.start_date,
                    created_by=job.requested_by,
                )
            )
        results.append([admission_no, outcome, str(stream_id) if stream_id else ""])
    await session.flush()
    return results


async def run_job(job_id: str, school_id: str) -> str:
    """Celery entry point. Idempotent: a job that is not QUEUED is left alone."""
    job_uuid, school_uuid = uuid.UUID(job_id), uuid.UUID(school_id)
    async with school_session(school_uuid) as session:
        job = (
            await session.execute(
                select(BackgroundJob)
                .where(BackgroundJob.id == job_uuid, BackgroundJob.kind == JobKind.PROMOTION)
                .with_for_update()
            )
        ).scalar_one_or_none()
        if job is None or job.status != JobStatus.QUEUED:
            return "skipped"
        job.status, job.started_at = JobStatus.RUNNING, datetime.now(UTC)
        await session.commit()
        await set_context(session, DbContext(school_id=school_uuid, user_id=job.requested_by))
        lang = (await session.execute(select(User.preferred_language).where(User.id == job.requested_by))).scalar()
        body = PromotionIn.model_validate(json.loads(get_storage().get(job.input_file_key)))
        planned, errors = await _plan(session, body, lang)
        if errors:
            return await imports.fail_job(session, job, errors)
        old_year, new_year, plan = planned
        job.total_items = len(plan)
        try:
            results = await _apply(session, job, old_year, new_year, plan)
        except (AppError, IntegrityError):
            await session.rollback()
            job = (await session.execute(select(BackgroundJob).where(BackgroundJob.id == job_uuid))).scalar_one()
            return await imports.fail_job(
                session, job, [{"row": 1, "column": "", "code": "stream_full", "message": message("stream_full", lang)}]
            )
        key = f"{job.school_id}/promotions/{job.id}/result.xlsx"
        get_storage().put(key, imports.result_file(["admission_no", "outcome", "stream_id"], results))
        job.result_file_key, job.processed_items = key, len(results)
        imports.finish_job(job, JobStatus.SUCCEEDED)
        await session.commit()
    return "succeeded"
