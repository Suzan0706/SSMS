"""CSV exports of lists, with the filters of the screen (FR-79).

Encrypted fields (birth certificate, NIDA, phone numbers) and health data are never exported. Every export is audited.
Cells that a spreadsheet would run as a formula are prefixed with an apostrophe (CSV injection).
"""

import csv
import io
import uuid
from datetime import date
from typing import Annotated

from fastapi import APIRouter, Depends, Query, Response
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import Principal, require_permission
from app.core.sheets import csv_cell
from app.db.session import get_session
from app.models import Department, Designation, Invoice, Staff, Student, User
from app.models.enums import StudentStatus
from app.services import attendance, audit, students

router = APIRouter(prefix="/exports", tags=["exports"])
Session = Annotated[AsyncSession, Depends(get_session)]
CSV = "text/csv; charset=utf-8"
BOM = chr(0xFEFF)  # byte-order mark, so spreadsheet programs read Kiswahili names correctly


def _csv(name: str, header: list[str], rows) -> Response:
    out = io.StringIO()
    writer = csv.writer(out)
    writer.writerow(header)
    for row in rows:
        writer.writerow([csv_cell(v) for v in row])
    return Response(
        BOM + out.getvalue(), media_type=CSV, headers={"Content-Disposition": f'attachment; filename="{name}"'}
    )


@router.get("/students.csv", response_class=Response, responses={200: {"content": {CSV: {}}}})
async def students_csv(
    session: Session,
    principal: Annotated[Principal, require_permission("students.export")],
    q: Annotated[str | None, Query(max_length=60)] = None,
    status: StudentStatus | None = None,
):
    rows, cursor = [], None
    while True:  # the student list, with the year on screen, every page
        page, cursor = await students.list_page(
            session, q=q, class_id=None, stream_id=None, status=status, limit=50, cursor=cursor
        )
        rows += [(s.admission_no, s.full_name, s.gender, s.class_code, s.stream_name, s.status) for s in page]
        if not cursor:
            break
    await audit.record(session, "EXPORT", "students", None, {"rows": len(rows), "q": q, "status": status})
    await session.commit()
    return _csv("students.csv", ["admission_no", "name", "gender", "class", "stream", "status"], rows)


@router.get("/staff.csv", response_class=Response, responses={200: {"content": {CSV: {}}}})
async def staff_csv(
    session: Session, principal: Annotated[Principal, require_permission("staff.read", "staff.manage")]
):
    rows = (
        await session.execute(
            select(
                Staff.staff_no,
                User.first_name,
                User.last_name,
                Department.name_en,
                Designation.name_en,
                Staff.employment_type,
                Staff.status,
            )
            .join(User, User.id == Staff.user_id)
            .outerjoin(Department, Department.id == Staff.department_id)
            .outerjoin(Designation, Designation.id == Staff.designation_id)
            .where(Staff.deleted_at.is_(None))
            .order_by(User.last_name, User.first_name)
        )
    ).all()
    await audit.record(session, "EXPORT", "staff", None, {"rows": len(rows)})
    await session.commit()
    return _csv(
        "staff.csv",
        ["staff_no", "first_name", "last_name", "department", "designation", "employment_type", "status"],
        rows,
    )


@router.get("/invoices.csv", response_class=Response, responses={200: {"content": {CSV: {}}}})
async def invoices_csv(
    term_id: uuid.UUID, session: Session, principal: Annotated[Principal, require_permission("finance.read")]
):
    rows = (
        await session.execute(
            select(
                Invoice.invoice_no,
                Student.admission_no,
                User.first_name,
                User.last_name,
                Invoice.issued_at,
                Invoice.due_date,
                Invoice.total_tzs,
                Invoice.paid_tzs,
                Invoice.balance_tzs,
                Invoice.status,
            )
            .join(Student, Student.id == Invoice.student_id)
            .join(User, User.id == Student.user_id)
            .where(Invoice.term_id == term_id)
            .order_by(Invoice.invoice_no)
        )
    ).all()
    await audit.record(session, "EXPORT", "invoices", None, {"rows": len(rows), "term_id": str(term_id)})
    await session.commit()
    return _csv(
        "invoices.csv",
        [
            "invoice_no",
            "admission_no",
            "first_name",
            "last_name",
            "issued_at",
            "due_date",
            "total_tzs",
            "paid_tzs",
            "balance_tzs",
            "status",
        ],
        [(*r[:4], r[4].date().isoformat(), *r[5:]) for r in rows],
    )


@router.get("/attendance.csv", response_class=Response, responses={200: {"content": {CSV: {}}}})
async def attendance_csv(
    stream_id: uuid.UUID,
    start: Annotated[date, Query(alias="from")],
    end: Annotated[date, Query(alias="to")],
    session: Session,
    principal: Annotated[Principal, require_permission("attendance.read")],
):
    report = await attendance.stream_report(session, stream_id, start, end)
    await audit.record(session, "EXPORT", "attendance", stream_id, {"from": str(start), "to": str(end)})
    await session.commit()
    return _csv(
        f"attendance-{start}-{end}.csv",
        ["admission_no", "name", "present", "late", "absent", "excused", "rate_pct"],
        [(r.admission_no, r.full_name, r.present, r.late, r.absent, r.excused, r.rate_pct) for r in report.rows],
    )
