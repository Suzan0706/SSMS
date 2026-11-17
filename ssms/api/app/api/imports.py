"""/imports (templates, uploads) and /jobs (status and result files of background work)."""

import hashlib
import uuid
from datetime import datetime
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, File, Header, Response, UploadFile, status
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import Principal, active_principal
from app.core.errors import AppError, forbidden, not_found
from app.core.pagination import Cursor, Limit, Page, paginate
from app.core.storage import get_storage
from app.db.session import get_session
from app.models import BackgroundJob
from app.models.enums import JobStatus
from app.services import idempotency, imports
from app.tasks.dispatch import get_dispatcher

router = APIRouter(tags=["imports"])
Kind = Literal["students", "guardians", "staff"]
XLSX = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
FILE_TYPES = {"xlsx": XLSX, "csv": "text/csv; charset=utf-8", "pdf": "application/pdf", "json": "application/json"}


class JobOut(BaseModel):
    id: uuid.UUID
    kind: str
    status: str
    progress_pct: int
    total_items: int | None
    processed_items: int
    error_count: int
    created_at: datetime
    started_at: datetime | None
    finished_at: datetime | None
    error_report_url: str | None
    result_url: str | None


def job_out(job) -> JobOut:
    base = f"/api/v1/jobs/{job.id}/files"
    return JobOut(
        id=job.id,
        kind=job.kind,
        status=job.status,
        progress_pct=job.progress_pct,
        total_items=job.total_items,
        processed_items=job.processed_items,
        error_count=job.error_count,
        created_at=job.created_at,
        started_at=job.started_at,
        finished_at=job.finished_at,
        error_report_url=f"{base}/errors" if job.error_report_file_key else None,
        result_url=f"{base}/result" if job.result_file_key else None,
    )


def _allowed(principal: Principal, kind: str) -> None:
    if not principal.has(imports.PERMISSION[kind]):
        raise forbidden()


@router.get(
    "/imports/templates/{kind}",
    response_class=Response,
    summary="XLSX template with a help sheet",
    responses={200: {"content": {XLSX: {}}}},
)
async def template(kind: Kind, principal: Principal = Depends(active_principal)):
    _allowed(principal, kind)
    return Response(
        imports.template(kind),
        media_type=XLSX,
        headers={"Content-Disposition": f'attachment; filename="ssms-{kind}-template.xlsx"'},
    )


@router.post(
    "/imports/{kind}",
    response_model=JobOut,
    status_code=status.HTTP_202_ACCEPTED,
    responses={
        413: {"description": "FILE_TOO_LARGE"},
        422: {"description": "FILE_TYPE / IMPORT_HEADERS / IDEMPOTENCY_KEY_REQUIRED / MISMATCH"},
    },
    summary="Upload XLSX or CSV; validated and imported all-or-nothing by a background job",
)
async def upload(
    kind: Kind,
    file: Annotated[UploadFile, File()],
    idempotency_key: Annotated[str | None, Header(alias="Idempotency-Key")] = None,
    principal: Principal = Depends(active_principal),
    session: AsyncSession = Depends(get_session),
):
    _allowed(principal, kind)
    key = idempotency.require_key(idempotency_key)
    limit = imports.max_bytes()
    data = await file.read(limit + 1)
    if len(data) > limit:
        raise AppError(413, "FILE_TOO_LARGE", mb=limit // (1024 * 1024))
    try:
        headers, rows = imports.read_rows(data)
        imports.check_headers(kind, headers)
    except imports.ImportFileError as exc:
        raise AppError(422, exc.code, [{"field": "file", "code": exc.code, **exc.params}]) from None
    if len(rows) > imports.MAX_ROWS:
        raise AppError(422, "VALIDATION_ERROR", [{"field": "file", "code": "too_many_rows", "limit": imports.MAX_ROWS}])

    scope = f"POST /imports/{kind}"
    digest = hashlib.sha256(data).hexdigest()
    previous = await idempotency.replay(session, scope, key, digest)
    if previous:
        job = (await session.execute(select(BackgroundJob).where(BackgroundJob.id == previous["job_id"]))).scalar_one()
        return job_out(job)
    job = BackgroundJob(
        school_id=principal.school_id,
        kind=imports.KINDS[kind],
        status=JobStatus.QUEUED,
        idempotency_key=key,
        requested_by=principal.user_id,
        created_by=principal.user_id,
        total_items=len(rows),
    )
    job.input_file_key = get_storage().put(f"{principal.school_id}/imports/{job.id}/input.{imports.sniff(data)}", data)
    session.add(job)
    idempotency.remember(session, principal, scope, key, digest, 202, {"job_id": str(job.id)})
    await session.commit()
    get_dispatcher().send("imports.run", job_id=str(job.id), school_id=str(principal.school_id))
    return job_out(job)


async def _job(session: AsyncSession, principal: Principal, job_id: uuid.UUID) -> BackgroundJob:
    job = (await session.execute(select(BackgroundJob).where(BackgroundJob.id == job_id))).scalar_one_or_none()
    if job is None or (job.requested_by != principal.user_id and not principal.has("users.manage")):
        raise not_found()
    return job


@router.get("/jobs", response_model=Page[JobOut], tags=["jobs"], summary="My background jobs, newest first")
async def my_jobs(
    limit: Limit = 20,
    cursor: Cursor = None,
    principal: Principal = Depends(active_principal),
    session: AsyncSession = Depends(get_session),
):
    stmt = select(BackgroundJob.id, BackgroundJob.created_at).where(BackgroundJob.requested_by == principal.user_id)
    rows, next_cursor = await paginate(
        session, stmt, [BackgroundJob.created_at, BackgroundJob.id], limit, cursor, descending=True
    )
    jobs = {
        j.id: j
        for j in (
            await session.execute(select(BackgroundJob).where(BackgroundJob.id.in_([r.id for r in rows])))
        ).scalars()
    }
    return Page[JobOut](items=[job_out(jobs[r.id]) for r in rows], next_cursor=next_cursor)


@router.get("/jobs/{job_id}", response_model=JobOut, tags=["jobs"], summary="Status of one job (owner or admin)")
async def get_job(
    job_id: uuid.UUID, principal: Principal = Depends(active_principal), session: AsyncSession = Depends(get_session)
):
    return job_out(await _job(session, principal, job_id))


@router.get(
    "/jobs/{job_id}/files/{which}", response_class=Response, tags=["jobs"], responses={200: {"content": {XLSX: {}}}}
)
async def job_file(
    job_id: uuid.UUID,
    which: Literal["errors", "result"],
    principal: Principal = Depends(active_principal),
    session: AsyncSession = Depends(get_session),
):
    job = await _job(session, principal, job_id)
    key = job.error_report_file_key if which == "errors" else job.result_file_key
    if not key:
        raise not_found()
    ext = key.rsplit(".", 1)[-1] if "." in key.rsplit("/", 1)[-1] else "xlsx"
    return Response(
        get_storage().get(key),
        media_type=FILE_TYPES.get(ext, XLSX),
        headers={"Content-Disposition": f'attachment; filename="job-{job.id}-{which}.{ext}"'},
    )
