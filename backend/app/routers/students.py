from fastapi import APIRouter, Depends, Query, status

from app.core.i18n import STATUS_LABELS
from app.deps import CurrentUser, DbSession, require_roles
from app.models import User
from app.models.enums import Role, StudentStatus
from app.schemas.common import Page
from app.schemas.students import (StatusChangeIn, StatusChangeOut, StudentCreate, StudentCreated, StudentOut,
                                  StudentUpdate)
from app.services import notify
from app.services import students as svc

router = APIRouter(prefix="/students", tags=["Students"])

RegistrarOrAdmin = Depends(require_roles(Role.REGISTRAR, Role.ADMIN))
StaffOrInstructor = Depends(require_roles(Role.ADMIN, Role.REGISTRAR, Role.BURSAR, Role.INSTRUCTOR))


@router.post("", response_model=StudentCreated, status_code=status.HTTP_201_CREATED)
def create_student(body: StudentCreate, db: DbSession, user: User = RegistrarOrAdmin):
    result = svc.create_student(db, body)
    db.commit()
    student = result.student
    for account in result.new_guardian_accounts:
        notify.sms_user(account.user, "account_created", name=account.user.full_name,
                        username=account.user.username, password=account.password)
    notify.sms_guardians(db, student, "account_created", primary_only=True,
                         username=student.user.username, password=result.password)
    return StudentCreated(**StudentOut.of(student).model_dump(), username=student.user.username,
                          initial_password=result.password)


@router.get("", response_model=Page[StudentOut], dependencies=[StaffOrInstructor])
def search_students(
    db: DbSession,
    q: str | None = Query(default=None, max_length=50, description="Name, admission no. or NECTA index no."),
    status_: StudentStatus | None = Query(default=None, alias="status"),
    level_id: int | None = None,
    stream: str | None = Query(default=None, pattern=r"^[A-Z]{1,5}$"),
    page: int = Query(default=1, ge=1),
    size: int = Query(default=25, ge=1, le=100),
):
    rows, total = svc.search_students(db, q, status_, level_id, stream, page, size)
    return Page[StudentOut](items=[StudentOut.of(s) for s in rows], total=total, page=page, size=size)


@router.get("/{student_id}", response_model=StudentOut)
def get_student(student_id: int, db: DbSession, user: CurrentUser):
    student = svc.get_student(db, student_id)
    svc.ensure_can_view(db, user, student)
    return StudentOut.of(student)


@router.patch("/{student_id}", response_model=StudentOut)
def update_student(student_id: int, body: StudentUpdate, db: DbSession, user: User = RegistrarOrAdmin):
    student = svc.update_student(db, svc.get_student(db, student_id), body)
    db.commit()
    return StudentOut.of(student)


@router.patch("/{student_id}/status", response_model=StatusChangeOut)
def change_status(student_id: int, body: StatusChangeIn, db: DbSession, user: User = RegistrarOrAdmin):
    student = svc.get_student(db, student_id)
    history = svc.change_status(db, student, body, user)
    db.commit()
    notify.sms_guardians(db, student, "status_changed", status=STATUS_LABELS[body.new_status.value],
                         reason=body.reason)
    return history


@router.get("/{student_id}/status-history", response_model=list[StatusChangeOut])
def status_history(student_id: int, db: DbSession, user: CurrentUser):
    svc.ensure_can_view(db, user, svc.get_student(db, student_id))
    return svc.status_history(db, student_id)
