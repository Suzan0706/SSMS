"""UC-06 Enrol Student and UC-07 Validate Requirements."""
import hashlib
import uuid
from dataclasses import dataclass
from datetime import date

from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.errors import AppError, not_found, rule_violation
from app.models import (CourseOffering, Enrolment, EnrolmentDocument, EnrolmentRequirement, EnrolmentSchedule,
                        Invoice, Schedule, Student, Term, User)
from app.models.enums import DocumentStatus, EnrolmentStatus, StudentStatus
from app.schemas.students import StatusChangeIn
from app.services import payments, students
from app.services.common import next_number, now_eat
from app.services.storage import Storage

E = EnrolmentStatus

# File type is decided by the first bytes, never by the extension or the browser's claim.
MAGIC = {
    b"%PDF-": ("application/pdf", "pdf"),
    b"\x89PNG\r\n\x1a\n": ("image/png", "png"),
    b"\xff\xd8\xff": ("image/jpeg", "jpg"),
}


def confirmed_count(db: Session, offering_id: int) -> int:
    return db.scalar(select(func.count()).select_from(Enrolment).where(
        Enrolment.offering_id == offering_id, Enrolment.status == E.CONFIRMED)) or 0


def get_enrolment(db: Session, enrolment_id: int) -> Enrolment:
    enrolment = db.get(Enrolment, enrolment_id)
    if enrolment is None:
        raise not_found("Enrolment")
    return enrolment


def requirements_for(db: Session, enrolment: Enrolment) -> list[EnrolmentRequirement]:
    level = enrolment.offering.course.education_level
    return list(db.scalars(select(EnrolmentRequirement).where(
        EnrolmentRequirement.is_active,
        or_(EnrolmentRequirement.education_level.is_(None), EnrolmentRequirement.education_level == level),
    ).order_by(EnrolmentRequirement.requirement_id)).all())


def apply(db: Session, student: Student, offering_id: int) -> Enrolment:
    offering = db.get(CourseOffering, offering_id)
    if offering is None or not offering.is_open:
        raise AppError(404, "NOT_FOUND", "Course offering not open", "Kozi hii haipo wazi kwa usajili")
    if student.current_status not in (StudentStatus.APPLICANT, StudentStatus.ACTIVE):
        raise rule_violation("Only applicants and active students can enrol",
                             "Ni waombaji na wanafunzi hai pekee wanaoweza kujisajili")
    if confirmed_count(db, offering_id) >= offering.capacity:
        raise AppError(409, "OFFERING_FULL", "No places left", "Nafasi zimejaa")
    enrolment = Enrolment(enrolment_no=next_number(db, "enrolment"), student_id=student.student_id,
                          offering_id=offering_id)
    db.add(enrolment)
    db.flush()                         # trigger: one active enrolment per student per year
    db.refresh(enrolment)
    return enrolment


def upload_document(db: Session, storage: Storage, enrolment: Enrolment, requirement_id: int,
                    file_name: str, content: bytes) -> EnrolmentDocument:
    if enrolment.status not in (E.PENDING, E.INVALID):
        raise rule_violation("Documents can only be changed before submission or after rejection",
                             "Nyaraka zinaweza kubadilishwa kabla ya kuwasilisha au baada ya kukataliwa",
                             status_code=409)
    requirement = db.get(EnrolmentRequirement, requirement_id)
    if requirement is None or requirement not in requirements_for(db, enrolment):
        raise rule_violation("This requirement does not apply to this enrolment",
                             "Hitaji hili halihusiani na usajili huu")
    if not 0 < len(content) <= get_settings().max_upload_bytes:
        raise rule_violation("File must be between 1 byte and 5 MB", "Faili liwe kati ya baiti 1 na MB 5")
    kind = next((v for magic, v in MAGIC.items() if content.startswith(magic)), None)
    if kind is None:
        raise rule_violation("Only PDF, JPG or PNG files are accepted", "Ni faili za PDF, JPG au PNG pekee")
    mime, ext = kind

    doc = db.scalar(select(EnrolmentDocument).where(EnrolmentDocument.enrolment_id == enrolment.enrolment_id,
                                                    EnrolmentDocument.requirement_id == requirement_id))
    if doc is not None and doc.status == DocumentStatus.VALID:
        raise rule_violation("This document is already valid", "Nyaraka hii tayari imethibitishwa",
                             status_code=409)
    key = f"enrolments/{enrolment.enrolment_id}/{requirement.code}/{uuid.uuid4().hex}.{ext}"
    storage.put(key, content, mime)
    values = dict(file_name=file_name[:255], storage_key=key, mime_type=mime, file_size_bytes=len(content),
                  sha256=hashlib.sha256(content).hexdigest(), status=DocumentStatus.PENDING, remarks=None,
                  validated_by=None, validated_at=None, uploaded_at=now_eat())
    if doc is None:
        doc = EnrolmentDocument(enrolment_id=enrolment.enrolment_id, requirement_id=requirement_id, **values)
        db.add(doc)
    else:
        for k, v in values.items():
            setattr(doc, k, v)
    db.flush()
    return doc


def submit(db: Session, enrolment: Enrolment) -> Enrolment:
    if enrolment.status not in (E.PENDING, E.INVALID):
        raise rule_violation("Only a pending or rejected application can be submitted",
                             "Maombi yanayosubiri au yaliyokataliwa pekee ndiyo yanaweza kuwasilishwa",
                             status_code=409)
    docs = {d.requirement_id: d for d in enrolment.documents}
    missing = [r.code for r in requirements_for(db, enrolment)
               if r.is_mandatory and (r.requirement_id not in docs
                                      or docs[r.requirement_id].status == DocumentStatus.INVALID)]
    if missing:
        raise rule_violation("Some mandatory documents are missing or still invalid",
                             "Baadhi ya nyaraka za lazima hazipo au bado si sahihi", missing=missing)
    enrolment.status = E.SUBMITTED
    enrolment.submitted_at = now_eat()
    db.flush()
    return enrolment


def refresh_status(db: Session, enrolment: Enrolment) -> Enrolment:
    """After validation: VALIDATED when every mandatory document is VALID, INVALID when any is INVALID."""
    docs = {d.requirement_id: d for d in enrolment.documents}
    if any(d.status == DocumentStatus.PENDING for d in docs.values()):
        return enrolment
    mandatory = [r for r in requirements_for(db, enrolment) if r.is_mandatory]
    if all(r.requirement_id in docs and docs[r.requirement_id].status == DocumentStatus.VALID for r in mandatory):
        enrolment.status = E.VALIDATED
    elif any(d.status == DocumentStatus.INVALID for d in docs.values()):
        enrolment.status = E.INVALID
    db.flush()
    return enrolment


def validate_document(db: Session, document_id: int, status: str, remarks: str | None,
                      validator: User) -> Enrolment:
    doc = db.get(EnrolmentDocument, document_id)
    if doc is None:
        raise not_found("Document")
    enrolment = doc.enrolment
    if enrolment.status != E.SUBMITTED:
        raise rule_violation("Only submitted applications can be validated",
                             "Maombi yaliyowasilishwa pekee ndiyo yanaweza kuhakikiwa", status_code=409)
    doc.status = DocumentStatus(status)
    doc.remarks = remarks
    doc.validated_by = validator.user_id
    doc.validated_at = now_eat()
    db.flush()
    return refresh_status(db, enrolment)


def term_to_bill(db: Session, offering: CourseOffering) -> Term | None:
    """The current or next term of the offering's year (the last term if the year is over)."""
    terms = db.scalars(select(Term).where(Term.academic_year_id == offering.academic_year_id)
                       .order_by(Term.term_no)).all()
    today = date.today()
    return next((t for t in terms if t.end_date >= today), terms[-1] if terms else None)


@dataclass
class Confirmation:
    enrolment: Enrolment
    schedules_linked: int
    invoice: Invoice | None


def confirm(db: Session, enrolment: Enrolment, stream: str, actor: User) -> Confirmation:
    if enrolment.status != E.VALIDATED:
        raise rule_violation("Only validated applications can be confirmed",
                             "Maombi yaliyohakikiwa pekee ndiyo yanaweza kuthibitishwa", status_code=409)
    offering = db.scalar(select(CourseOffering).where(CourseOffering.offering_id == enrolment.offering_id)
                         .with_for_update(of=CourseOffering))  # serialise the capacity check
    if confirmed_count(db, offering.offering_id) >= offering.capacity:
        raise AppError(409, "OFFERING_FULL", "No places left", "Nafasi zimejaa")

    enrolment.status = E.CONFIRMED
    enrolment.stream = stream
    enrolment.confirmed_at = now_eat()
    enrolment.confirmed_by = actor.user_id
    db.flush()

    sessions = db.scalars(select(Schedule.schedule_id).join(Term, Term.term_id == Schedule.term_id).where(
        Schedule.offering_id == offering.offering_id, Schedule.stream == stream,
        Term.academic_year_id == offering.academic_year_id)).all()
    for sid in sessions:
        db.add(EnrolmentSchedule(enrolment_id=enrolment.enrolment_id, schedule_id=sid))
    db.flush()                         # trigger: no student clash

    student = enrolment.student
    if student.current_status == StudentStatus.APPLICANT:
        students.change_status(db, student, StatusChangeIn(
            new_status=StudentStatus.ACTIVE,
            reason=f"Enrolment {enrolment.enrolment_no} confirmed"), actor, via_enrolment=True)

    term = term_to_bill(db, offering)
    invoice = payments.raise_invoice(db, student, offering, term, actor) if term else None
    return Confirmation(enrolment, len(sessions), invoice)


def cancel(db: Session, enrolment: Enrolment, reason: str) -> Enrolment:
    if enrolment.status in (E.CONFIRMED, E.CANCELLED):
        raise rule_violation("Confirmed or cancelled enrolments cannot be cancelled here",
                             "Usajili uliothibitishwa au kusitishwa hauwezi kusitishwa hapa", status_code=409)
    enrolment.status = E.CANCELLED
    enrolment.cancelled_at = now_eat()
    enrolment.cancel_reason = reason
    db.flush()
    return enrolment
