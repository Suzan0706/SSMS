"""Reports (FR-67): one read-only query per report type, shared by the on-screen preview and the export job.

Every query runs as ssms_app under RLS (one school), selects named columns only and takes the same optional filters
(academic year, term, class, stream, from/to dates, status). The preview returns the first 50 rows and the total;
the export (EXPORT job) writes every row as Excel, CSV or PDF and is audited.
"""

import csv
import io
import json
import uuid
from datetime import UTC, date, datetime
from decimal import Decimal

from openpyxl import Workbook
from reportlab.lib.pagesizes import A4, landscape
from reportlab.lib.units import mm
from reportlab.pdfgen import canvas
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import Principal
from app.core import sheets
from app.core.errors import AppError
from app.core.storage import get_storage
from app.db.session import DbContext, school_session, set_context
from app.models import BackgroundJob, School, Term
from app.models.enums import JobKind, JobStatus
from app.services import audit, calendar, imports, years

PREVIEW_ROWS = 50

NAME = "concat_ws(' ', u.first_name, u.middle_name, u.last_name)"
ENROLLED = """
    LEFT JOIN enrolments e ON e.student_id = st.id AND e.status = 'ACTIVE' AND e.academic_year_id = CAST(:year AS uuid)
    LEFT JOIN streams s ON s.id = e.stream_id LEFT JOIN classes c ON c.id = s.class_id"""
CLASS_FILTER = """
    AND (CAST(:class AS uuid) IS NULL OR c.id = CAST(:class AS uuid))
    AND (CAST(:stream AS uuid) IS NULL OR s.id = CAST(:stream AS uuid))"""

QUERIES: dict[str, tuple[list[str], str]] = {
    "enrolment": (
        ["admission_no", "name", "sex", "date_of_birth", "age", "class", "stream", "status", "admission_date"],
        f"""SELECT st.admission_no, {NAME}, u.gender, u.date_of_birth,
                   date_part('year', age(CAST(:on AS date), u.date_of_birth))::int, c.code, s.name, st.status,
                   st.admission_date
            FROM students st JOIN users u ON u.id = st.user_id {ENROLLED}
            WHERE st.deleted_at IS NULL AND (CAST(:status AS text) IS NULL OR st.status = :status)
              AND (e.id IS NOT NULL OR CAST(:status AS text) IS NOT NULL) {CLASS_FILTER}
            ORDER BY c.sort_order NULLS LAST, s.name, u.last_name, u.first_name""",
    ),
    "attendance": (
        ["admission_no", "name", "class", "stream", "present", "late", "absent", "excused", "rate_pct"],
        f"""SELECT st.admission_no, {NAME}, c.code, s.name,
                   count(*) FILTER (WHERE r.status = 'PRESENT'), count(*) FILTER (WHERE r.status = 'LATE'),
                   count(*) FILTER (WHERE r.status = 'ABSENT'), count(*) FILTER (WHERE r.status = 'EXCUSED'),
                   round(100.0 * count(*) FILTER (WHERE r.status IN ('PRESENT','LATE')) / nullif(count(r.id), 0), 1)
            FROM students st JOIN users u ON u.id = st.user_id {ENROLLED}
            LEFT JOIN attendance_records r ON r.student_id = st.id AND r.session_id IN (
                SELECT a.id FROM attendance_sessions a WHERE a.kind = 'REGISTER'
                  AND a.session_date BETWEEN CAST(:from AS date) AND CAST(:to AS date))
            WHERE st.deleted_at IS NULL AND e.id IS NOT NULL {CLASS_FILTER}
            GROUP BY st.id, st.admission_no, u.first_name, u.middle_name, u.last_name, c.code, c.sort_order, s.name
            ORDER BY c.sort_order, s.name, u.last_name""",
    ),
    "results": (
        ["admission_no", "name", "sex", "class", "stream", "average", "points", "division", "position"],
        f"""SELECT st.admission_no, {NAME}, u.gender, c.code, s.name, ts.average_score, ts.total_points,
                   ts.division, ts.class_position
            FROM student_term_summaries ts
            JOIN result_publications p ON p.id = ts.publication_id AND p.term_id = CAST(:term AS uuid)
            JOIN enrolments e ON e.id = ts.enrolment_id JOIN streams s ON s.id = e.stream_id
            JOIN classes c ON c.id = s.class_id JOIN students st ON st.id = e.student_id JOIN users u ON u.id =
                st.user_id
            WHERE NOT EXISTS (SELECT 1 FROM student_term_summaries x WHERE x.supersedes_id = ts.id) {CLASS_FILTER}
            ORDER BY c.sort_order, ts.class_position""",
    ),
    "fees": (
        ["admission_no", "name", "class", "stream", "invoiced_tzs", "paid_tzs", "outstanding_tzs", "credit_tzs"],
        f"""SELECT st.admission_no, {NAME}, c.code, s.name,
                   coalesce((SELECT sum(i.total_tzs) FROM invoices i WHERE i.student_id = st.id AND i.cancelled_at IS
                       NULL
                             AND (CAST(:term AS uuid) IS NULL OR i.term_id = CAST(:term AS uuid))), 0),
                   coalesce((SELECT sum(i.paid_tzs) FROM invoices i WHERE i.student_id = st.id AND i.cancelled_at IS
                       NULL
                             AND (CAST(:term AS uuid) IS NULL OR i.term_id = CAST(:term AS uuid))), 0),
                   coalesce(f.outstanding_tzs, 0), coalesce(f.credit_tzs, 0)
            FROM students st JOIN users u ON u.id = st.user_id {ENROLLED}
            LEFT JOIN v_student_fee_position f ON f.student_id = st.id
            WHERE st.deleted_at IS NULL AND e.id IS NOT NULL {CLASS_FILTER}
            ORDER BY c.sort_order, s.name, u.last_name""",
    ),
    "staff": (
        ["staff_no", "name", "sex", "department", "designation", "employment_type", "employment_date", "status"],
        f"""SELECT sf.staff_no, {NAME}, u.gender, d.name_en, g.name_en, sf.employment_type, sf.employment_date,
            sf.status
            FROM staff sf JOIN users u ON u.id = sf.user_id
            LEFT JOIN departments d ON d.id = sf.department_id LEFT JOIN designations g ON g.id = sf.designation_id
            WHERE sf.deleted_at IS NULL AND (CAST(:status AS text) IS NULL OR sf.status = :status)
            ORDER BY sf.staff_no""",
    ),
    "student-status": (
        ["effective_date", "admission_no", "name", "from_status", "to_status", "reason"],
        f"""SELECT h.effective_date, st.admission_no, {NAME}, h.old_status, h.new_status, h.reason
            FROM student_status_history h JOIN students st ON st.id = h.student_id JOIN users u ON u.id = st.user_id
            WHERE h.effective_date BETWEEN CAST(:from AS date) AND CAST(:to AS date)
              AND (CAST(:status AS text) IS NULL OR h.new_status = :status)
            ORDER BY h.effective_date, st.admission_no""",
    ),
    "transactions": (
        ["received_at", "receipt_no", "admission_no", "name", "channel", "reference", "amount_tzs", "status"],
        f"""SELECT p.received_at, r.receipt_no, st.admission_no, {NAME}, p.channel, p.external_ref, p.amount_tzs,
            p.status
            FROM payments p JOIN students st ON st.id = p.student_id JOIN users u ON u.id = st.user_id
            LEFT JOIN receipts r ON r.payment_id = p.id
            WHERE p.received_at >= CAST(:from AS date) AND p.received_at < CAST(:to AS date) + 1
              AND (CAST(:status AS text) IS NULL OR p.status = :status)
            ORDER BY p.received_at""",
    ),
}
TYPES = tuple(QUERIES)


async def _params(session: AsyncSession, filters: dict) -> dict:
    today = calendar.today()
    year = filters.get("academic_year_id")
    if year is None:
        year = await years.viewing_year(session)
    term = filters.get("term_id")
    start, end = filters.get("date_from"), filters.get("date_to")
    if term and (start is None or end is None):
        t = (await session.execute(select(Term).where(Term.id == term))).scalar_one_or_none()
        start, end = start or (t.start_date if t else None), end or (t.end_date if t else None)
    start, end = start or today.replace(month=1, day=1), end or today
    if end < start or (end - start).days > 400:
        raise AppError(422, "VALIDATION_ERROR", [{"field": "date_to", "code": "invalid_range"}])
    return {
        "year": year,
        "term": term,
        "class": filters.get("class_id"),
        "stream": filters.get("stream_id"),
        "status": filters.get("status"),
        "from": start,
        "to": end,
        "on": today,
    }


async def rows(
    session: AsyncSession, report: str, filters: dict, limit: int | None
) -> tuple[list[str], list[list], int]:
    """(columns, rows, total). `limit` None = every row (export)."""
    if report not in QUERIES:
        raise AppError(404, "NOT_FOUND")
    if report == "results" and not filters.get("term_id"):
        raise AppError(422, "VALIDATION_ERROR", [{"field": "term_id", "code": "required"}])
    columns, sql = QUERIES[report]
    params = await _params(session, filters)
    total = (await session.execute(text(f"SELECT count(*) FROM ({sql}) q"), params)).scalar_one()
    query = text(sql + (f" LIMIT {int(limit)}" if limit else ""))
    data = [list(r) for r in (await session.execute(query, params)).all()]
    return columns, data, total


def _cell(value):
    if isinstance(value, Decimal):
        return f"{value:.2f}"
    if isinstance(value, datetime):
        return value.astimezone(calendar.EAT).strftime("%Y-%m-%d %H:%M")
    if isinstance(value, date):
        return value.isoformat()
    return "" if value is None else str(value)


def preview_json(columns: list[str], data: list[list]) -> list[dict]:
    return [{c: _cell(v) for c, v in zip(columns, r, strict=True)} for r in data]


def render(columns: list[str], data: list[list], fmt: str, title: str) -> bytes:
    if fmt == "csv":
        out = io.StringIO()
        writer = csv.writer(out)
        writer.writerow(columns)
        writer.writerows([[sheets.csv_cell(v) if isinstance(v, str) else _cell(v) for v in r] for r in data])
        return ("﻿" + out.getvalue()).encode()  # BOM: Excel opens Kiswahili names correctly
    if fmt == "pdf":
        return _pdf(columns, data, title)
    wb = Workbook()
    ws = wb.active
    ws.title = title[:31]
    sheets.append(ws, columns)
    for r in data:
        sheets.append(
            ws,
            [
                float(v) if isinstance(v, Decimal) else (_cell(v) if isinstance(v, datetime | uuid.UUID) else v)
                for v in r
            ],
        )
    out = io.BytesIO()
    wb.save(out)
    return out.getvalue()


def _pdf(columns: list[str], data: list[list], title: str) -> bytes:
    out = io.BytesIO()
    page = canvas.Canvas(out, pagesize=landscape(A4))
    width, height = landscape(A4)
    col = (width - 20 * mm) / max(len(columns), 1)

    def header(y: float) -> float:
        page.setFont("Helvetica-Bold", 11)
        page.drawString(10 * mm, height - 12 * mm, title)
        page.setFont("Helvetica-Bold", 7)
        for i, c in enumerate(columns):
            page.drawString(10 * mm + i * col, y, c[:24])
        return y - 5 * mm

    y = header(height - 20 * mm)
    page.setFont("Helvetica", 7)
    for r in data:
        if y < 12 * mm:
            page.showPage()
            y = header(height - 20 * mm)
            page.setFont("Helvetica", 7)
        for i, v in enumerate(r):
            page.drawString(10 * mm + i * col, y, _cell(v)[: int(col / 3.6)])
        y -= 4.2 * mm
    page.save()
    return out.getvalue()


EXTENSIONS = {"xlsx": "xlsx", "csv": "csv", "pdf": "pdf"}


def queue_export(
    session: AsyncSession, principal: Principal, report: str, filters: dict, fmt: str, key: str
) -> BackgroundJob:
    job = BackgroundJob(
        school_id=principal.school_id,
        kind=JobKind.EXPORT,
        status=JobStatus.QUEUED,
        idempotency_key=key,
        requested_by=principal.user_id,
        created_by=principal.user_id,
    )
    params = {"report": report, "format": fmt, "filters": {k: str(v) for k, v in filters.items() if v is not None}}
    job.input_file_key = get_storage().put(
        f"{principal.school_id}/exports/{job.id}/params.json", json.dumps(params).encode()
    )
    session.add(job)
    return job


FILTER_TYPES = {"date_from": date.fromisoformat, "date_to": date.fromisoformat}


async def run_export(job_id: str, school_id: str) -> str:
    """EXPORT job: every row of a report into one file; audited."""
    async with school_session(uuid.UUID(school_id)) as session:
        job = (
            await session.execute(
                select(BackgroundJob)
                .where(BackgroundJob.id == uuid.UUID(job_id), BackgroundJob.kind == JobKind.EXPORT)
                .with_for_update()
            )
        ).scalar_one_or_none()
        if job is None or job.status != JobStatus.QUEUED:
            return "skipped"
        job.status, job.started_at = JobStatus.RUNNING, datetime.now(UTC)
        await session.commit()
        await set_context(session, DbContext(school_id=job.school_id, user_id=job.requested_by))
        params = json.loads(get_storage().get(job.input_file_key))
        filters = {k: FILTER_TYPES.get(k, str)(v) for k, v in params["filters"].items()}
        school = (await session.execute(select(School.name))).scalar_one()
        columns, data, total = await rows(session, params["report"], filters, None)
        fmt = params["format"]
        key = f"{job.school_id}/exports/{job.id}/{params['report']}.{EXTENSIONS[fmt]}"
        get_storage().put(key, render(columns, data, fmt, f"{school} - {params['report']}"))
        job.result_file_key, job.total_items, job.processed_items = key, total, total
        await audit.record(
            session, "EXPORT", "reports", job.id, {"report": params["report"], "rows": total, "format": fmt}
        )
        imports.finish_job(job, JobStatus.SUCCEEDED)
        await session.commit()
    return "succeeded"
