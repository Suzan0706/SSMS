"""UC-06 Enrol Student and UC-07 Validate Requirements."""
from fastapi import APIRouter, Depends, File, Form, Query, UploadFile, status
from sqlalchemy import select

from app.core.config import get_settings
from app.core.errors import AppError, forbidden
from app.core.i18n import tzs
from app.deps import CurrentUser, DbSession, get_storage, require_roles
from app.models import Enrolment, EnrolmentDocument, Student, User
from app.models.enums import DocumentStatus, EnrolmentStatus, Role
from app.schemas.courses import RequirementOut
from app.schemas.enrolments import (CancelIn, ConfirmIn, ConfirmOut, DocumentOut, DocumentValidateIn,
                                    EnrolmentCreate, EnrolmentOut)
from app.services import enrolments as svc
from app.services import notify
from app.services.payments import invoice_balance
from app.services.storage import Storage
from app.tasks.payments import request_control_number

router = APIRouter(tags=["Enrolment"])
Registrar = Depends(require_roles(Role.REGISTRAR, Role.ADMIN))


def _out(db, e: Enrolment, with_details: bool = True) -> EnrolmentOut:
    o = e.offering
    return EnrolmentOut(
        enrolment_id=e.enrolment_id, enrolment_no=e.enrolment_no, student_id=e.student_id,
        offering_id=e.offering_id, course_code=o.course.course_code, level_code=o.level.code,
        academic_year=o.academic_year.name, stream=e.stream, status=e.status, applied_at=e.applied_at,
        submitted_at=e.submitted_at, confirmed_at=e.confirmed_at, cancelled_at=e.cancelled_at,
        cancel_reason=e.cancel_reason,
        requirements=[RequirementOut.model_validate(r) for r in svc.requirements_for(db, e)] if with_details else [],
        documents=[DocumentOut.model_validate(d) for d in e.documents] if with_details else [],
    )


def _load_for(db, enrolment_id: int, user: User) -> Enrolment:
    """Students act only on their own enrolment; staff and instructors on any."""
    enrolment = svc.get_enrolment(db, enrolment_id)
    if user.role == Role.STUDENT and enrolment.student.user_id != user.user_id:
        raise AppError(404, "NOT_FOUND", "Enrolment not found", "Usajili haukupatikana")
    if user.role == Role.PARENT:
        raise forbidden()
    return enrolment


@router.post("/enrolments", response_model=EnrolmentOut, status_code=status.HTTP_201_CREATED)
def apply(body: EnrolmentCreate, db: DbSession, user: CurrentUser):
    """Student applies for themselves; Registrar/Admin may apply on behalf of a student."""
    if user.role == Role.STUDENT:
        student = db.scalar(select(Student).where(Student.user_id == user.user_id))
    elif user.role in (Role.REGISTRAR, Role.ADMIN) and body.student_id:
        student = db.get(Student, body.student_id)
    else:
        raise forbidden()
    if student is None:
        raise AppError(404, "NOT_FOUND", "Student not found", "Mwanafunzi hakupatikana")
    enrolment = svc.apply(db, student, body.offering_id)
    db.commit()
    return _out(db, enrolment)


@router.get("/enrolments", response_model=list[EnrolmentOut], dependencies=[Registrar])
def list_enrolments(db: DbSession, status_: EnrolmentStatus | None = Query(default=None, alias="status"),
                    offering_id: int | None = None):
    stmt = select(Enrolment).order_by(Enrolment.enrolment_id.desc())
    if status_:
        stmt = stmt.where(Enrolment.status == status_)
    if offering_id:
        stmt = stmt.where(Enrolment.offering_id == offering_id)
    return [_out(db, e, with_details=False) for e in db.scalars(stmt.limit(500)).all()]


@router.get("/enrolments/{enrolment_id}", response_model=EnrolmentOut)
def get_enrolment(enrolment_id: int, db: DbSession, user: CurrentUser):
    return _out(db, _load_for(db, enrolment_id, user))


@router.get("/enrolments/{enrolment_id}/requirements", response_model=list[RequirementOut])
def requirements(enrolment_id: int, db: DbSession, user: CurrentUser):
    return svc.requirements_for(db, _load_for(db, enrolment_id, user))


@router.post("/enrolments/{enrolment_id}/documents", response_model=DocumentOut,
             status_code=status.HTTP_201_CREATED)
async def upload_document(enrolment_id: int, db: DbSession, user: CurrentUser,
                          requirement_id: int = Form(...), file: UploadFile = File(...),
                          storage: Storage = Depends(get_storage)):
    """PDF, JPG or PNG up to 5 MB. Type is checked from the file content, not the name."""
    enrolment = _load_for(db, enrolment_id, user)
    content = await file.read(get_settings().max_upload_bytes + 1)
    doc = svc.upload_document(db, storage, enrolment, requirement_id, file.filename or "upload", content)
    db.commit()
    return doc


@router.post("/enrolments/{enrolment_id}/submit", response_model=EnrolmentOut)
def submit(enrolment_id: int, db: DbSession, user: CurrentUser):
    enrolment = svc.submit(db, _load_for(db, enrolment_id, user))
    db.commit()
    return _out(db, enrolment)


@router.get("/enrolment-documents", response_model=list[DocumentOut],
            dependencies=[Depends(require_roles(Role.INSTRUCTOR, Role.REGISTRAR, Role.ADMIN))])
def validation_queue(db: DbSession, status_: DocumentStatus = Query(default=DocumentStatus.PENDING, alias="status")):
    """Documents of SUBMITTED enrolments waiting for faculty validation."""
    return db.scalars(select(EnrolmentDocument).join(Enrolment).where(
        EnrolmentDocument.status == status_, Enrolment.status == EnrolmentStatus.SUBMITTED)
        .order_by(EnrolmentDocument.uploaded_at)).all()


@router.patch("/enrolment-documents/{document_id}", response_model=EnrolmentOut)
def validate_document(document_id: int, body: DocumentValidateIn, db: DbSession,
                      user: User = Depends(require_roles(Role.INSTRUCTOR, Role.ADMIN))):
    """Faculty marks one document VALID or INVALID (remarks required). Enrolment status follows."""
    enrolment = svc.validate_document(db, document_id, body.status, body.remarks, user)
    db.commit()
    if enrolment.status == EnrolmentStatus.VALIDATED:
        notify.sms_user(enrolment.student.user, "requirements_completed", enrolment_no=enrolment.enrolment_no)
    elif enrolment.status == EnrolmentStatus.INVALID:
        notify.sms_user(enrolment.student.user, "requirements_invalid")
    return _out(db, enrolment)


@router.post("/enrolments/{enrolment_id}/confirm", response_model=ConfirmOut)
def confirm(enrolment_id: int, body: ConfirmIn, db: DbSession, user: User = Registrar):
    """Confirm: stream, class sessions, student ACTIVE and term invoice in one transaction."""
    result = svc.confirm(db, svc.get_enrolment(db, enrolment_id), body.stream, user)
    db.commit()
    e = result.enrolment
    notify.sms_user(e.student.user, "enrolment_confirmed", name=e.student.user.full_name,
                    level={"sw": e.offering.level.name_sw, "en": e.offering.level.name_en}, stream=e.stream)
    if result.invoice:
        balance = invoice_balance(db, result.invoice.invoice_id)
        notify.sms_guardians(db, e.student, "invoice_issued", primary_only=True,
                             invoice_no=result.invoice.invoice_no, amount=tzs(balance["total_tzs"]),
                             control_no=result.invoice.gepg_control_no or "-")
        try:
            request_control_number.delay(result.invoice.invoice_id)
        except Exception:              # retried by the nightly reconciliation job
            pass
    return ConfirmOut(enrolment=_out(db, e), schedules_linked=result.schedules_linked,
                      invoice_no=result.invoice.invoice_no if result.invoice else None)


@router.post("/enrolments/{enrolment_id}/cancel", response_model=EnrolmentOut)
def cancel(enrolment_id: int, body: CancelIn, db: DbSession, user: CurrentUser):
    if user.role not in (Role.STUDENT, Role.REGISTRAR, Role.ADMIN):
        raise forbidden()
    enrolment = svc.cancel(db, _load_for(db, enrolment_id, user), body.reason)
    db.commit()
    notify.sms_user(enrolment.student.user, "enrolment_cancelled", enrolment_no=enrolment.enrolment_no,
                    reason=body.reason)
    return _out(db, enrolment)
