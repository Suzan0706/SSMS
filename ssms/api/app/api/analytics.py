"""/reports/{type} (preview + export job), /dashboards/{role}, /compliance-exports, /data-subject-requests."""

import hashlib
import uuid
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, Header, Response
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import Principal, active_principal, require_permission
from app.api.imports import JobOut, job_out
from app.core.errors import forbidden, not_found
from app.core.storage import get_storage
from app.db.session import get_session
from app.models import BackgroundJob, DataSubjectRequest, User
from app.models.enums import DsrStatus
from app.schemas.analytics import ComplianceIn, DsrIn, DsrOut, DsrUpdate, ExportIn, ReportFilters, ReportPreview
from app.services import compliance, crud, dashboards, idempotency, privacy, reports
from app.tasks.dispatch import get_dispatcher

router = APIRouter(tags=["reports"])
Session = Annotated[AsyncSession, Depends(get_session)]
Signed = Annotated[Principal, Depends(active_principal)]
Exporter = Annotated[Principal, require_permission("reports.export")]
Privacy = Annotated[Principal, require_permission("privacy.manage")]
ReportType = Literal["enrolment", "attendance", "results", "fees", "staff", "student-status", "transactions"]
# reports.read opens the school reports; money and staff reports also need finance or staff access.
REPORT_PERMISSIONS = {
    "fees": ("finance.read",),
    "transactions": ("finance.read",),
    "staff": ("staff.read", "staff.manage"),
}


def _may_read(principal: Principal, report: str) -> bool:
    if not principal.has("reports.read"):
        return False
    needed = REPORT_PERMISSIONS.get(report)
    return needed is None or any(principal.has(p) for p in needed)


@router.get("/reports/{report}", response_model=ReportPreview, summary="First 50 rows and the total, with filters")
async def preview(
    report: ReportType, principal: Signed, session: Session, filters: Annotated[ReportFilters, Depends()]
):
    if not _may_read(principal, report):
        raise forbidden()
    columns, data, total = await reports.rows(session, report, filters.model_dump(), reports.PREVIEW_ROWS)
    return ReportPreview(report=report, columns=columns, rows=reports.preview_json(columns, data), total=total)


@router.post(
    "/reports/{report}/export",
    response_model=JobOut,
    status_code=202,
    summary="Every row as Excel, CSV or PDF (EXPORT job; download from /jobs/{id}/files/result; audited)",
)
async def export(
    report: ReportType,
    body: ExportIn,
    principal: Exporter,
    session: Session,
    idempotency_key: Annotated[str | None, Header(alias="Idempotency-Key")] = None,
):
    if not _may_read(principal, report):
        raise forbidden()
    key = idempotency.require_key(idempotency_key)
    digest = hashlib.sha256(f"{report}:{body.model_dump_json()}".encode()).hexdigest()
    scope = "POST /reports/export"
    previous = await idempotency.replay(session, scope, key, digest)
    if previous:
        return job_out(await crud.get_live(session, BackgroundJob, uuid.UUID(previous["job_id"])))
    job = reports.queue_export(session, principal, report, body.model_dump(exclude={"format"}), body.format, key)
    idempotency.remember(session, principal, scope, key, digest, 202, {"job_id": str(job.id)})
    await session.commit()
    get_dispatcher().send("reports.export", job_id=str(job.id), school_id=str(principal.school_id))
    return job_out(job)


@router.get(
    "/dashboards/{role}",
    summary="KPI tiles and small series for the office, bursar, teacher, librarian or front desk (cached one minute)",
)
async def dashboard(
    role: Literal["admin", "bursar", "teacher", "librarian", "receptionist"], principal: Signed, session: Session
):
    if not principal.has(dashboards.PERMISSIONS[role]):
        raise forbidden()
    return await dashboards.build(session, principal, role)


@router.post(
    "/compliance-exports",
    response_model=JobOut,
    status_code=202,
    tags=["compliance"],
    summary="End-of-year returns (enrolment by age/sex/class, attendance, results, staff); formats VERIFY",
)
async def compliance_export(
    body: ComplianceIn,
    principal: Exporter,
    session: Session,
    idempotency_key: Annotated[str | None, Header(alias="Idempotency-Key")] = None,
):
    key = idempotency.require_key(idempotency_key)
    digest = hashlib.sha256(body.model_dump_json().encode()).hexdigest()
    scope = "POST /compliance-exports"
    previous = await idempotency.replay(session, scope, key, digest)
    if previous:
        return job_out(await crud.get_live(session, BackgroundJob, uuid.UUID(previous["job_id"])))
    job = compliance.queue(
        session, principal, list(dict.fromkeys(body.templates)), body.academic_year_id, body.format, key
    )
    idempotency.remember(session, principal, scope, key, digest, 202, {"job_id": str(job.id)})
    await session.commit()
    get_dispatcher().send("compliance.export", job_id=str(job.id), school_id=str(principal.school_id))
    return job_out(job)


# ---------------------------------------------------------------- privacy


async def _dsr_out(session: AsyncSession, item: DataSubjectRequest) -> DsrOut:
    user = (await session.execute(select(User).where(User.id == item.subject_user_id))).scalar_one()
    return DsrOut(
        id=item.id,
        subject_user_id=item.subject_user_id,
        subject_name=user.full_name,
        request_type=item.request_type,
        status=item.status,
        details=item.details,
        requested_at=item.requested_at,
        due_at=item.due_at,
        completed_at=item.completed_at,
        overdue=privacy.is_overdue(item),
        has_file=item.result_file_key is not None,
    )


@router.get("/data-subject-requests", response_model=list[DsrOut], tags=["privacy"], summary="Open first, by due date")
async def list_dsr(_: Privacy, session: Session, status: DsrStatus | None = None):
    where = [DataSubjectRequest.status == status] if status else []
    items = await crud.list_live(
        session,
        DataSubjectRequest,
        DataSubjectRequest.completed_at.is_not(None),
        DataSubjectRequest.due_at,
        where=where,
    )
    return [await _dsr_out(session, i) for i in items]


@router.post("/data-subject-requests", response_model=DsrOut, status_code=201, tags=["privacy"])
async def create_dsr(body: DsrIn, principal: Privacy, session: Session):
    item = await privacy.create(session, principal, body.subject_user_id, body.request_type, body.details)
    await session.refresh(item)
    return await _dsr_out(session, item)


@router.patch("/data-subject-requests/{request_id}", response_model=DsrOut, tags=["privacy"])
async def update_dsr(request_id: uuid.UUID, body: DsrUpdate, principal: Privacy, session: Session):
    return await _dsr_out(session, await privacy.set_status(session, principal, request_id, body.status, body.note))


@router.post(
    "/data-subject-requests/{request_id}/export",
    response_model=DsrOut,
    tags=["privacy"],
    summary="Collect everything held about the person into one JSON file and complete the request",
)
async def run_dsr_export(request_id: uuid.UUID, principal: Privacy, session: Session):
    return await _dsr_out(session, await privacy.export(session, principal, request_id))


@router.post(
    "/data-subject-requests/{request_id}/anonymise",
    response_model=DsrOut,
    tags=["privacy"],
    summary="Remove names, contacts, identifiers and login; ledgers and results stay (legal duty)",
)
async def run_dsr_anonymise(request_id: uuid.UUID, principal: Privacy, session: Session):
    return await _dsr_out(session, await privacy.anonymise(session, principal, request_id))


@router.get("/data-subject-requests/{request_id}/file", response_class=Response, tags=["privacy"])
async def dsr_file(request_id: uuid.UUID, _: Privacy, session: Session):
    item = await crud.get_live(session, DataSubjectRequest, request_id)
    if not item.result_file_key:
        raise not_found()
    return Response(
        get_storage().get(item.result_file_key),
        media_type="application/json",
        headers={"Content-Disposition": f'attachment; filename="data-{item.subject_user_id}.json"'},
    )
