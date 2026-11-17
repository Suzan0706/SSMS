"""/staff, /departments, /designations."""

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, Query, Response, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import Principal, require_permission
from app.core.pagination import Cursor, Limit, Page
from app.db.session import get_session
from app.models import Department, Designation
from app.models.enums import StaffStatus
from app.schemas.people import (
    CodeNameOut,
    DepartmentIn,
    DepartmentOut,
    DepartmentUpdateIn,
    DesignationIn,
    QualificationIn,
    QualificationOut,
    StaffCreatedOut,
    StaffCreateIn,
    StaffListItem,
    StaffOut,
    StaffSubjectOut,
    StaffSubjectsIn,
    StaffUpdateIn,
)
from app.services import staff as service
from app.tasks.dispatch import get_dispatcher

router = APIRouter(tags=["staff"])
Reason = Annotated[str, Query(min_length=3, max_length=300, description="Why the record is removed (audited)")]


@router.get("/staff", response_model=Page[StaffListItem])
async def list_staff(
    q: Annotated[str | None, Query(max_length=50)] = None,
    department_id: uuid.UUID | None = None,
    status_filter: Annotated[StaffStatus | None, Query(alias="status")] = None,
    limit: Limit = 50,
    cursor: Cursor = None,
    _: Principal = require_permission("staff.read", "staff.manage"),
    session: AsyncSession = Depends(get_session),
):
    items, next_cursor = await service.list_staff(
        session, q=q, department_id=department_id, status=status_filter, limit=limit, cursor=cursor
    )
    return Page[StaffListItem](items=items, next_cursor=next_cursor)


@router.post(
    "/staff",
    response_model=StaffCreatedOut,
    status_code=status.HTTP_201_CREATED,
    responses={409: {"description": "DUPLICATE staff number, username or phone"}},
    summary="Staff record + login account (temporary password shown once and sent by SMS)",
)
async def create_staff(
    body: StaffCreateIn,
    principal: Principal = require_permission("staff.manage"),
    session: AsyncSession = Depends(get_session),
):
    staff_id, password, call = await service.create_staff(session, principal, body)
    get_dispatcher().send("sms.send", **call)
    out = await service.get_staff(session, principal, staff_id)
    return StaffCreatedOut(**out.model_dump(), temporary_password=password)


@router.get("/staff/{staff_id}", response_model=StaffOut, summary="Salary only with payroll.read")
async def get_staff(
    staff_id: uuid.UUID,
    principal: Principal = require_permission("staff.read", "staff.manage"),
    session: AsyncSession = Depends(get_session),
):
    return await service.get_staff(session, principal, staff_id)


@router.patch(
    "/staff/{staff_id}",
    response_model=StaffOut,
    summary="Partial update; leaving statuses (TRANSFERRED, RETIRED, TERMINATED) disable the account",
)
async def update_staff(
    staff_id: uuid.UUID,
    body: StaffUpdateIn,
    principal: Principal = require_permission("staff.manage"),
    session: AsyncSession = Depends(get_session),
):
    await service.update_staff(session, principal, staff_id, body)
    return await service.get_staff(session, principal, staff_id)


@router.delete("/staff/{staff_id}", status_code=status.HTTP_204_NO_CONTENT, summary="Soft delete (audited)")
async def delete_staff(
    staff_id: uuid.UUID,
    reason: Reason,
    principal: Principal = require_permission("staff.manage"),
    session: AsyncSession = Depends(get_session),
):
    await service.delete_staff(session, principal, staff_id, reason)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post("/staff/{staff_id}/qualifications", response_model=QualificationOut, status_code=status.HTTP_201_CREATED)
async def add_qualification(
    staff_id: uuid.UUID,
    body: QualificationIn,
    principal: Principal = require_permission("staff.manage"),
    session: AsyncSession = Depends(get_session),
):
    return await service.add_qualification(session, principal, staff_id, body)


@router.delete("/staff/{staff_id}/qualifications/{qualification_id}", status_code=status.HTTP_204_NO_CONTENT)
async def remove_qualification(
    staff_id: uuid.UUID,
    qualification_id: uuid.UUID,
    _: Principal = require_permission("staff.manage"),
    session: AsyncSession = Depends(get_session),
):
    await service.remove_qualification(session, staff_id, qualification_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get(
    "/staff/{staff_id}/subjects",
    response_model=list[StaffSubjectOut],
    summary="Subjects this teacher is qualified to teach",
)
async def staff_subjects(
    staff_id: uuid.UUID,
    _: Principal = require_permission("staff.read", "staff.manage", "timetable.manage"),
    session: AsyncSession = Depends(get_session),
):
    return await service.subjects_of(session, staff_id)


@router.put(
    "/staff/{staff_id}/subjects",
    response_model=list[StaffSubjectOut],
    summary="Replace the list; timetable slots and the generator only use qualified teachers",
)
async def set_staff_subjects(
    staff_id: uuid.UUID,
    body: StaffSubjectsIn,
    principal: Principal = require_permission("staff.manage", "timetable.manage"),
    session: AsyncSession = Depends(get_session),
):
    return await service.set_subjects(session, principal, staff_id, body.subject_ids)


@router.get("/departments", response_model=list[DepartmentOut], tags=["reference"])
async def list_departments(
    _: Principal = require_permission("staff.read", "staff.manage"), session: AsyncSession = Depends(get_session)
):
    return await service.list_named(session, Department)


@router.post("/departments", response_model=DepartmentOut, status_code=status.HTTP_201_CREATED)
async def create_department(
    body: DepartmentIn,
    principal: Principal = require_permission("staff.manage"),
    session: AsyncSession = Depends(get_session),
):
    return await service.create_named(session, principal, Department, body.model_dump())


@router.patch("/departments/{department_id}", response_model=DepartmentOut)
async def update_department(
    department_id: uuid.UUID,
    body: DepartmentUpdateIn,
    _: Principal = require_permission("staff.manage"),
    session: AsyncSession = Depends(get_session),
):
    return await service.update_named(session, Department, department_id, body.model_dump(exclude_unset=True))


@router.delete(
    "/departments/{department_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    responses={409: {"description": "NOT_ALLOWED: staff still belong to it"}},
)
async def delete_department(
    department_id: uuid.UUID,
    reason: Reason,
    _: Principal = require_permission("staff.manage"),
    session: AsyncSession = Depends(get_session),
):
    await service.delete_named(session, Department, department_id, reason)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get("/designations", response_model=list[CodeNameOut], tags=["reference"])
async def list_designations(
    _: Principal = require_permission("staff.read", "staff.manage"), session: AsyncSession = Depends(get_session)
):
    return await service.list_named(session, Designation)


@router.post("/designations", response_model=CodeNameOut, status_code=status.HTTP_201_CREATED)
async def create_designation(
    body: DesignationIn,
    principal: Principal = require_permission("staff.manage"),
    session: AsyncSession = Depends(get_session),
):
    return await service.create_named(session, principal, Designation, body.model_dump())


@router.delete("/designations/{designation_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_designation(
    designation_id: uuid.UUID,
    reason: Reason,
    _: Principal = require_permission("staff.manage"),
    session: AsyncSession = Depends(get_session),
):
    await service.delete_named(session, Designation, designation_id, reason)
    return Response(status_code=status.HTTP_204_NO_CONTENT)
