"""End-of-year compliance exports (FR-68): counts in the shape education officers ask for, one sheet per template.

Templates (column layouts VERIFY with the ministry / regional education office before relying on them):
  ENROLMENT   class x age (<=12 .. >=19, age on 1 January of the year) x sex, active enrolments of the year
  ATTENDANCE  class x sex: register days, attendance rate
  RESULTS     class x division (I-IV, 0, incomplete) x sex, latest publication of the year per class
  STAFF       designation x sex x employment type, plus highest qualification
The job is COMPLIANCE_EXPORT; the file is Excel (one sheet per template), CSV or PDF (one template); audited EXPORT.
"""

import io
import json
import uuid
from datetime import UTC, date, datetime

from openpyxl import Workbook
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import Principal
from app.core.errors import AppError
from app.core.sheets import append as safe_append
from app.core.storage import get_storage
from app.db.session import DbContext, school_session, set_context
from app.models import AcademicYear, BackgroundJob, School
from app.models.enums import JobKind, JobStatus
from app.services import audit, imports, reports

TEMPLATES = ("ENROLMENT", "ATTENDANCE", "RESULTS", "STAFF")
AGES = list(range(12, 20))  # 12 means "12 or younger", 19 means "19 or older"


async def _enrolment(session: AsyncSession, year: AcademicYear) -> tuple[list[str], list[list]]:
    rows = (
        await session.execute(
            text(
                "SELECT c.code, u.gender, greatest(least(date_part('year', age(CAST(:jan AS date), "
                "u.date_of_birth))::int, 19), 12), "
                "count(*) FROM enrolments e JOIN streams s ON s.id = e.stream_id JOIN classes c ON c.id = s.class_id "
                "JOIN students st ON st.id = e.student_id JOIN users u ON u.id = st.user_id "
                "WHERE e.academic_year_id = :year AND e.status = 'ACTIVE' AND u.date_of_birth IS NOT NULL "
                "GROUP BY c.code, c.sort_order, u.gender, 3 ORDER BY c.sort_order"
            ),
            {"jan": date(year.start_date.year, 1, 1), "year": year.id},
        )
    ).all()
    columns = (
        ["class"]
        + [f"{'<=' if a == 12 else '>=' if a == 19 else ''}{a} {g}" for a in AGES for g in ("M", "F")]
        + [
            "total M",
            "total F",
        ]
    )
    table: dict[str, dict] = {}
    for code, gender, age, n in rows:
        line = table.setdefault(code, {})
        line[(age, gender)] = line.get((age, gender), 0) + n
    out = []
    for code, line in table.items():
        cells = [line.get((a, g), 0) for a in AGES for g in ("M", "F")]
        out.append([code, *cells, sum(cells[0::2]), sum(cells[1::2])])
    return columns, out


async def _attendance(session: AsyncSession, year: AcademicYear) -> tuple[list[str], list[list]]:
    rows = (
        await session.execute(
            text(
                "SELECT c.code, u.gender, count(DISTINCT a.session_date), count(r.id), "
                "count(r.id) FILTER (WHERE r.status IN ('PRESENT','LATE')) "
                "FROM attendance_sessions a JOIN attendance_records r ON r.session_id = a.id "
                "JOIN streams s ON s.id = a.stream_id JOIN classes c ON c.id = s.class_id "
                "JOIN students st ON st.id = r.student_id JOIN users u ON u.id = st.user_id "
                "WHERE a.kind = 'REGISTER' AND a.session_date BETWEEN :start AND :end "
                "GROUP BY c.code, c.sort_order, u.gender ORDER BY c.sort_order"
            ),
            {"start": year.start_date, "end": year.end_date},
        )
    ).all()
    table: dict[str, dict] = {}
    for code, gender, days, marked, attended in rows:
        line = table.setdefault(code, {"days": 0})
        line["days"] = max(line["days"], days)
        line[gender] = round(attended * 100 / marked, 1) if marked else None
    return ["class", "register days", "attendance % M", "attendance % F"], [
        [code, v["days"], v.get("M"), v.get("F")] for code, v in table.items()
    ]


async def _results(session: AsyncSession, year: AcademicYear) -> tuple[list[str], list[list]]:
    divisions = ["I", "II", "III", "IV", "0", "incomplete"]
    rows = (
        await session.execute(
            text(
                "WITH latest AS (SELECT DISTINCT ON (p.class_id) p.id, p.class_id FROM result_publications p "
                "JOIN terms t ON t.id = p.term_id WHERE t.academic_year_id = :year ORDER BY p.class_id, t.term_no "
                "DESC) "
                "SELECT c.code, u.gender, coalesce(ts.division, 'incomplete'), count(*) FROM latest l "
                "JOIN student_term_summaries ts ON ts.publication_id = l.id "
                "JOIN enrolments e ON e.id = ts.enrolment_id JOIN students st ON st.id = e.student_id "
                "JOIN users u ON u.id = st.user_id JOIN classes c ON c.id = l.class_id "
                "WHERE NOT EXISTS (SELECT 1 FROM student_term_summaries x WHERE x.supersedes_id = ts.id) "
                "GROUP BY c.code, c.sort_order, u.gender, 3 ORDER BY c.sort_order"
            ),
            {"year": year.id},
        )
    ).all()
    table: dict[str, dict] = {}
    for code, gender, division, n in rows:
        table.setdefault(code, {})[(division, gender)] = n
    return ["class"] + [f"Div {d} {g}" for d in divisions for g in ("M", "F")], [
        [code, *[line.get((d, g), 0) for d in divisions for g in ("M", "F")]] for code, line in table.items()
    ]


async def _staff(session: AsyncSession, year: AcademicYear) -> tuple[list[str], list[list]]:
    rows = (
        await session.execute(
            text(
                "SELECT coalesce(g.name_en, '-'), sf.employment_type, u.gender, "
                "coalesce((SELECT q.level FROM staff_qualifications q WHERE q.staff_id = sf.id AND q.deleted_at IS "
                "NULL "
                "ORDER BY array_position(ARRAY['CERTIFICATE','DIPLOMA','DEGREE','POSTGRAD_DIP','MASTERS','PHD'], "
                "CAST(q.level AS text)) DESC LIMIT 1), '-'), count(*) "
                "FROM staff sf JOIN users u ON u.id = sf.user_id LEFT JOIN designations g ON g.id = sf.designation_id "
                "WHERE sf.deleted_at IS NULL AND sf.status = 'ACTIVE' GROUP BY 1, 2, 3, 4 ORDER BY 1, 2, 4"
            )
        )
    ).all()
    return ["designation", "employment type", "sex", "highest qualification", "count"], [list(r) for r in rows]


BUILDERS = {"ENROLMENT": _enrolment, "ATTENDANCE": _attendance, "RESULTS": _results, "STAFF": _staff}


async def build(session: AsyncSession, template: str, year_id: uuid.UUID) -> tuple[list[str], list[list]]:
    year = (await session.execute(select(AcademicYear).where(AcademicYear.id == year_id))).scalar_one_or_none()
    if year is None:
        raise AppError(422, "VALIDATION_ERROR", [{"field": "academic_year_id", "code": "invalid_value"}])
    return await BUILDERS[template](session, year)


def queue(session: AsyncSession, principal: Principal, templates: list[str], year_id: uuid.UUID, fmt: str, key: str):
    if fmt != "xlsx" and len(templates) != 1:
        raise AppError(422, "VALIDATION_ERROR", [{"field": "templates", "code": "invalid_value"}])
    job = BackgroundJob(
        school_id=principal.school_id,
        kind=JobKind.COMPLIANCE_EXPORT,
        status=JobStatus.QUEUED,
        idempotency_key=key,
        requested_by=principal.user_id,
        created_by=principal.user_id,
    )
    params = {"templates": templates, "academic_year_id": str(year_id), "format": fmt}
    job.input_file_key = get_storage().put(
        f"{principal.school_id}/compliance/{job.id}/params.json", json.dumps(params).encode()
    )
    session.add(job)
    return job


async def run(job_id: str, school_id: str) -> str:
    async with school_session(uuid.UUID(school_id)) as session:
        job = (
            await session.execute(
                select(BackgroundJob)
                .where(BackgroundJob.id == uuid.UUID(job_id), BackgroundJob.kind == JobKind.COMPLIANCE_EXPORT)
                .with_for_update()
            )
        ).scalar_one_or_none()
        if job is None or job.status != JobStatus.QUEUED:
            return "skipped"
        job.status, job.started_at = JobStatus.RUNNING, datetime.now(UTC)
        await session.commit()
        await set_context(session, DbContext(school_id=job.school_id, user_id=job.requested_by))
        params = json.loads(get_storage().get(job.input_file_key))
        year_id, fmt = uuid.UUID(params["academic_year_id"]), params["format"]
        school = (await session.execute(select(School.name))).scalar_one()
        sheets = [(t, *await build(session, t, year_id)) for t in params["templates"]]
        if fmt == "xlsx":
            wb = Workbook()
            wb.remove(wb.active)
            for name, columns, data in sheets:
                ws = wb.create_sheet(name)
                safe_append(ws, [f"{school} - {name}"])
                safe_append(ws, columns)
                for r in data:
                    safe_append(ws, r)
            buffer = io.BytesIO()
            wb.save(buffer)
            content = buffer.getvalue()
        else:
            name, columns, data = sheets[0]
            content = reports.render(columns, data, fmt, f"{school} - {name}")
        key = f"{job.school_id}/compliance/{job.id}/compliance.{fmt}"
        get_storage().put(key, content)
        rows = sum(len(d) for _, _, d in sheets)
        job.result_file_key, job.total_items, job.processed_items = key, rows, rows
        await audit.record(session, "EXPORT", "compliance", job.id, {"templates": params["templates"], "format": fmt})
        imports.finish_job(job, JobStatus.SUCCEEDED)
        await session.commit()
    return "succeeded"
