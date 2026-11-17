"""User accounts, roles, staff records, qualifications, departments and designations (caller's school context)."""

import uuid

from sqlalchemy import String, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import Principal
from app.core.errors import AppError, not_found
from app.core.pagination import paginate
from app.core.security import hash_password_async
from app.models import Department, Designation, Role, Staff, StaffQualification, StaffSubject, Subject, User, UserRole
from app.models.enums import UserStatus
from app.schemas.people import (
    QualificationIn,
    StaffCreateIn,
    StaffListItem,
    StaffOut,
    StaffSubjectOut,
    StaffUpdateIn,
    UserListItem,
    UserUpdateIn,
)
from app.services import audit
from app.services.people import (
    account_sms,
    decrypt_phone,
    display_phone,
    grant_role,
    new_temporary_password,
    new_user,
    now,
    revoke_sessions,
    role_ids,
    set_phone,
    unique_username,
)

ADMIN_ONLY_ROLES = {"school_admin"}


def _escape(q: str) -> str:
    return q.strip().replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


def _roles_of(user_id_column):
    return (
        select(func.coalesce(func.array_agg(Role.code), []))
        .select_from(UserRole)
        .join(Role, Role.id == UserRole.role_id)
        .where(UserRole.user_id == user_id_column, UserRole.revoked_at.is_(None))
        .correlate_except(UserRole, Role)
        .scalar_subquery()
    )


async def _user(session: AsyncSession, user_id: uuid.UUID, lock: bool = False) -> User:
    stmt = select(User).where(User.id == user_id, User.deleted_at.is_(None))
    user = (await session.execute(stmt.with_for_update() if lock else stmt)).scalar_one_or_none()
    if user is None:
        raise not_found()
    return user


# ---------------------------------------------------------------- users


async def list_users(
    session: AsyncSession,
    principal: Principal,
    *,
    q: str | None,
    role: str | None,
    status: str | None,
    limit: int,
    cursor: str | None,
) -> tuple[list[UserListItem], str | None]:
    sort_last = func.lower(User.last_name, type_=String).label("sort_last")
    sort_first = func.lower(User.first_name, type_=String).label("sort_first")
    stmt = select(
        User.id,
        User.first_name,
        User.middle_name,
        User.last_name,
        User.username,
        User.status,
        User.last_login_at,
        User.phone_enc,
        User.phone_last4,
        _roles_of(User.id).label("roles"),
        sort_last,
        sort_first,
    ).where(User.deleted_at.is_(None))
    if q:
        term = _escape(q)
        stmt = stmt.where(
            or_(User.last_name.ilike(f"{term}%"), User.first_name.ilike(f"{term}%"), User.username.ilike(f"{term}%"))
        )
    if role:
        stmt = stmt.where(
            select(UserRole.id)
            .join(Role, Role.id == UserRole.role_id)
            .where(UserRole.user_id == User.id, UserRole.revoked_at.is_(None), Role.code == role)
            .exists()
        )
    if status:
        stmt = stmt.where(User.status == status)
    rows, next_cursor = await paginate(session, stmt, [sort_last, sort_first, User.id], limit, cursor)
    reveal = principal.has("guardians.manage")
    items = [
        UserListItem(
            id=r.id,
            full_name=" ".join(p for p in (r.first_name, r.middle_name, r.last_name) if p),
            username=r.username,
            status=r.status,
            roles=sorted(r.roles or []),
            phone=display_phone(r.phone_enc, r.phone_last4, reveal),
            last_login_at=r.last_login_at,
        )
        for r in rows
    ]
    return items, next_cursor


async def update_user(session: AsyncSession, principal: Principal, user_id: uuid.UUID, body: UserUpdateIn) -> User:
    user = await _user(session, user_id, lock=True)
    if body.status:
        if user.id == principal.user_id and body.status != UserStatus.ACTIVE:
            raise AppError(409, "NOT_ALLOWED", [{"field": "status", "code": "invalid_value"}])
        if user.status == UserStatus.NO_LOGIN:
            raise AppError(409, "NOT_ALLOWED", [{"field": "status", "code": "invalid_value"}])
        user.status = body.status
        if body.status == UserStatus.DISABLED:
            await revoke_sessions(session, user.id)
        else:
            user.failed_login_count, user.locked_until = 0, None
    if body.preferred_language:
        user.preferred_language = body.preferred_language
    await session.commit()
    return user


async def reset_password(session: AsyncSession, principal: Principal, user_id: uuid.UUID) -> tuple[str, dict | None]:
    user = await _user(session, user_id, lock=True)
    if user.status == UserStatus.NO_LOGIN or user.username is None:
        raise AppError(409, "NOT_ALLOWED")
    password = new_temporary_password()
    user.password_hash, user.must_change_password = await hash_password_async(password), True
    user.failed_login_count, user.locked_until = 0, None
    await revoke_sessions(session, user.id)
    await audit.record(session, "PASSWORD_CHANGE", "users", user.id, {"by": "reset"})
    call = None
    phone = decrypt_phone(user)
    if phone:
        call = await account_sms(session, principal, user, phone, password)
    await session.commit()
    return password, call


async def add_role(session: AsyncSession, principal: Principal, user_id: uuid.UUID, role_code: str) -> list[str]:
    await _user(session, user_id)
    await grant_role(session, principal, user_id, role_code)
    await session.commit()
    return await roles_of(session, user_id)


async def remove_role(session: AsyncSession, principal: Principal, user_id: uuid.UUID, role_code: str) -> None:
    if user_id == principal.user_id and role_code in ADMIN_ONLY_ROLES:
        raise AppError(409, "NOT_ALLOWED")  # never lock the school out of administration
    role_id = (await role_ids(session, [role_code]))[role_code]
    grant = (
        await session.execute(
            select(UserRole).where(
                UserRole.user_id == user_id, UserRole.role_id == role_id, UserRole.revoked_at.is_(None)
            )
        )
    ).scalar_one_or_none()
    if grant is None:
        raise not_found()
    grant.revoked_at = now()
    await audit.record(session, "ROLE_REVOKE", "users", user_id, {"role": role_code})
    await session.commit()


async def roles_of(session: AsyncSession, user_id: uuid.UUID) -> list[str]:
    return sorted(
        (
            await session.execute(
                select(Role.code)
                .join(UserRole, UserRole.role_id == Role.id)
                .where(UserRole.user_id == user_id, UserRole.revoked_at.is_(None))
            )
        ).scalars()
    )


# ---------------------------------------------------------------- staff


async def _staff(session: AsyncSession, staff_id: uuid.UUID, lock: bool = False) -> Staff:
    stmt = select(Staff).where(Staff.id == staff_id, Staff.deleted_at.is_(None))
    staff = (await session.execute(stmt.with_for_update() if lock else stmt)).scalar_one_or_none()
    if staff is None:
        raise not_found()
    return staff


async def create_staff(
    session: AsyncSession, principal: Principal, body: StaffCreateIn, commit: bool = True
) -> tuple[uuid.UUID, str, dict]:
    """Staff record + account. Returns (staff id, temporary password, SMS task call to dispatch after commit)."""
    roles = list(dict.fromkeys(body.roles))
    if (set(roles) - {"teacher"}) and not principal.has("roles.assign"):
        raise AppError(403, "FORBIDDEN", [{"field": "roles", "code": "invalid_value"}])
    if set(roles) & {"parent", "student"}:
        raise AppError(422, "VALIDATION_ERROR", [{"field": "roles", "code": "invalid_value"}])
    p = body.person
    username = body.username or await unique_username(session, p.first_name, p.last_name)
    password = new_temporary_password()
    user = new_user(
        principal,
        first_name=p.first_name,
        middle_name=p.middle_name,
        last_name=p.last_name,
        gender=p.gender,
        date_of_birth=p.date_of_birth,
        phone=p.phone,
        email=p.email,
        username=username,
        password_hash=await hash_password_async(password),
        language=p.preferred_language,
    )
    session.add(user)
    await session.flush()
    staff = Staff(
        school_id=principal.school_id,
        user_id=user.id,
        staff_no=body.staff_no,
        check_no=body.check_no,
        department_id=body.department_id,
        designation_id=body.designation_id,
        employment_type=body.employment_type,
        employment_date=body.employment_date,
        salary_tzs=body.salary_tzs,
        max_periods_per_week=body.max_periods_per_week,
        created_by=principal.user_id,
    )
    session.add(staff)
    await session.flush()
    for code in roles:
        await grant_role(session, principal, user.id, code)
    call = await account_sms(session, principal, user, p.phone, password)
    if commit:
        await session.commit()
    return staff.id, password, call


async def get_staff(session: AsyncSession, principal: Principal, staff_id: uuid.UUID) -> StaffOut:
    staff = await _staff(session, staff_id)
    user = (await session.execute(select(User).where(User.id == staff.user_id))).scalar_one()
    qualifications = (
        (
            await session.execute(
                select(StaffQualification)
                .where(StaffQualification.staff_id == staff.id, StaffQualification.deleted_at.is_(None))
                .order_by(StaffQualification.year_awarded.desc())
            )
        )
        .scalars()
        .all()
    )
    return StaffOut(
        id=staff.id,
        user_id=user.id,
        staff_no=staff.staff_no,
        check_no=staff.check_no,
        full_name=user.full_name,
        gender=user.gender,
        phone=display_phone(user.phone_enc, user.phone_last4, principal.has("staff.manage")),
        email=user.email,
        username=user.username,
        department_id=staff.department_id,
        designation_id=staff.designation_id,
        employment_type=staff.employment_type,
        employment_date=staff.employment_date,
        salary_tzs=staff.salary_tzs if principal.has("payroll.read") else None,
        max_periods_per_week=staff.max_periods_per_week,
        status=staff.status,
        roles=await roles_of(session, user.id),
        qualifications=list(qualifications),
    )


async def list_staff(
    session: AsyncSession,
    *,
    q: str | None,
    department_id: uuid.UUID | None,
    status: str | None,
    limit: int,
    cursor: str | None,
) -> tuple[list[StaffListItem], str | None]:
    sort_last = func.lower(User.last_name, type_=String).label("sort_last")
    sort_first = func.lower(User.first_name, type_=String).label("sort_first")
    stmt = (
        select(
            Staff.id,
            Staff.staff_no,
            Staff.department_id,
            Staff.designation_id,
            Staff.employment_type,
            Staff.status,
            User.first_name,
            User.middle_name,
            User.last_name,
            sort_last,
            sort_first,
        )
        .join(User, User.id == Staff.user_id)
        .where(Staff.deleted_at.is_(None))
    )
    if q:
        term = _escape(q)
        stmt = stmt.where(
            or_(Staff.staff_no.ilike(f"{term}%"), User.last_name.ilike(f"{term}%"), User.first_name.ilike(f"{term}%"))
        )
    if department_id:
        stmt = stmt.where(Staff.department_id == department_id)
    if status:
        stmt = stmt.where(Staff.status == status)
    rows, next_cursor = await paginate(session, stmt, [sort_last, sort_first, Staff.id], limit, cursor)
    return [
        StaffListItem(
            id=r.id,
            staff_no=r.staff_no,
            department_id=r.department_id,
            designation_id=r.designation_id,
            employment_type=r.employment_type,
            status=r.status,
            full_name=" ".join(p for p in (r.first_name, r.middle_name, r.last_name) if p),
        )
        for r in rows
    ], next_cursor


async def update_staff(session: AsyncSession, principal: Principal, staff_id: uuid.UUID, body: StaffUpdateIn) -> None:
    staff = await _staff(session, staff_id, lock=True)
    user = (await session.execute(select(User).where(User.id == staff.user_id).with_for_update())).scalar_one()
    data = body.model_dump(exclude_unset=True)
    if "salary_tzs" in data and not principal.has("payroll.read"):
        raise AppError(403, "FORBIDDEN", [{"field": "salary_tzs", "code": "invalid_value"}])
    for field in ("first_name", "middle_name", "last_name", "email"):
        if field in data:
            setattr(user, field, data[field])
    if "phone" in data:
        set_phone(user, data["phone"])
    for field in (
        "check_no",
        "department_id",
        "designation_id",
        "employment_type",
        "salary_tzs",
        "max_periods_per_week",
        "status",
    ):
        if field in data:
            setattr(staff, field, data[field])
    if data.get("status") in ("TRANSFERRED", "RETIRED", "TERMINATED"):
        user.status = UserStatus.DISABLED  # leavers lose access at once
        await revoke_sessions(session, user.id)
    await session.commit()


async def delete_staff(session: AsyncSession, principal: Principal, staff_id: uuid.UUID, reason: str) -> None:
    staff = await _staff(session, staff_id, lock=True)
    if staff.user_id == principal.user_id:
        raise AppError(409, "NOT_ALLOWED")
    user = (await session.execute(select(User).where(User.id == staff.user_id).with_for_update())).scalar_one()
    staff.deleted_at = now()
    user.status = UserStatus.DISABLED
    await revoke_sessions(session, user.id)
    await audit.record(session, "DELETE", "staff", staff.id, {"reason": reason})
    await session.commit()


async def add_qualification(
    session: AsyncSession, principal: Principal, staff_id: uuid.UUID, body: QualificationIn
) -> StaffQualification:
    await _staff(session, staff_id)
    item = StaffQualification(
        school_id=principal.school_id, staff_id=staff_id, created_by=principal.user_id, **body.model_dump()
    )
    session.add(item)
    await session.commit()
    return item


async def remove_qualification(session: AsyncSession, staff_id: uuid.UUID, qualification_id: uuid.UUID) -> None:
    item = (
        await session.execute(
            select(StaffQualification).where(
                StaffQualification.id == qualification_id,
                StaffQualification.staff_id == staff_id,
                StaffQualification.deleted_at.is_(None),
            )
        )
    ).scalar_one_or_none()
    if item is None:
        raise not_found()
    item.deleted_at = now()
    await session.commit()


# ---------------------------------------------------------------- departments and designations


async def subjects_of(session: AsyncSession, staff_id: uuid.UUID) -> list[StaffSubjectOut]:
    await _staff(session, staff_id)
    rows = await session.execute(
        select(Subject.id, Subject.code, Subject.name_en, Subject.name_sw)
        .join(StaffSubject, StaffSubject.subject_id == Subject.id)
        .where(StaffSubject.staff_id == staff_id, StaffSubject.deleted_at.is_(None))
        .order_by(Subject.code)
    )
    return [StaffSubjectOut(subject_id=i, code=c, name_en=en, name_sw=sw) for i, c, en, sw in rows.all()]


async def set_subjects(
    session: AsyncSession, principal: Principal, staff_id: uuid.UUID, subject_ids: list[uuid.UUID]
) -> list[StaffSubjectOut]:
    """Replace the list. Existing lessons and assignments stay; the rule applies to new slots and generated ones."""
    await _staff(session, staff_id, lock=True)
    wanted = set(subject_ids)
    known = await session.execute(select(Subject.id).where(Subject.id.in_(wanted), Subject.deleted_at.is_(None)))
    if wanted - set(known.scalars().all()):
        raise not_found()
    current = (
        (
            await session.execute(
                select(StaffSubject).where(StaffSubject.staff_id == staff_id, StaffSubject.deleted_at.is_(None))
            )
        )
        .scalars()
        .all()
    )
    for row in current:
        if row.subject_id not in wanted:
            row.deleted_at = func.now()
    for subject_id in wanted - {row.subject_id for row in current}:
        session.add(
            StaffSubject(
                school_id=principal.school_id, staff_id=staff_id, subject_id=subject_id, created_by=principal.user_id
            )
        )
    await session.flush()
    saved = await subjects_of(session, staff_id)
    await session.commit()
    return saved


async def list_named(session: AsyncSession, model) -> list:
    return list(
        (
            await session.execute(select(model).where(model.deleted_at.is_(None)).order_by(model.code).limit(200))
        ).scalars()
    )


async def create_named(session: AsyncSession, principal: Principal, model, data: dict):
    item = model(school_id=principal.school_id, created_by=principal.user_id, **data)
    session.add(item)
    await session.commit()
    return item


async def update_named(session: AsyncSession, model, item_id: uuid.UUID, data: dict):
    item = (
        await session.execute(select(model).where(model.id == item_id, model.deleted_at.is_(None)).with_for_update())
    ).scalar_one_or_none()
    if item is None:
        raise not_found()
    for field, value in data.items():
        setattr(item, field, value)
    await session.commit()
    return item


async def delete_named(session: AsyncSession, model, item_id: uuid.UUID, reason: str) -> None:
    item = (
        await session.execute(select(model).where(model.id == item_id, model.deleted_at.is_(None)).with_for_update())
    ).scalar_one_or_none()
    if item is None:
        raise not_found()
    in_use = (
        model is Department
        and (
            await session.execute(
                select(Staff.id).where(Staff.department_id == item_id, Staff.deleted_at.is_(None)).limit(1)
            )
        ).scalar()
    )
    in_use = in_use or (
        model is Designation
        and (
            await session.execute(
                select(Staff.id).where(Staff.designation_id == item_id, Staff.deleted_at.is_(None)).limit(1)
            )
        ).scalar()
    )
    if in_use:
        raise AppError(409, "NOT_ALLOWED", [{"field": "id", "code": "in_use"}])
    item.deleted_at = now()
    await audit.record(session, "DELETE", model.__tablename__, item.id, {"reason": reason})
    await session.commit()
