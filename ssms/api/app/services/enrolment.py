"""Enrolment workflow: requirements -> application -> documents -> submit -> validate -> approve / reject / cancel.

The applicant is registered as a student with status APPLICANT (admission number reserved); approval enrols
the student into a stream (capacity enforced by the database) and makes them ACTIVE.
"""

import hashlib
import uuid
from datetime import UTC, date, datetime

from sqlalchemy import SmallInteger, and_, cast, func, literal, or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import Principal
from app.core.errors import AppError, forbidden, not_found
from app.core.files import detect
from app.core.storage import get_storage
from app.models import (
    AcademicYear,
    Combination,
    Enrolment,
    EnrolmentApplication,
    EnrolmentDocument,
    EnrolmentRequirement,
    Guardian,
    School,
    SchoolClass,
    SchoolSettings,
    Stream,
    Student,
    StudentGuardian,
    StudentStatusHistory,
    User,
)
from app.models.enums import ApplicationStatus as A
from app.models.enums import DocumentStatus, EnrolmentStatus, StudentStatus, UserStatus
from app.schemas.enrolment import (
    ApplicantOut,
    ApplicationIn,
    ApplicationOut,
    ChecklistItem,
    DocumentDecisionIn,
    DocumentOut,
    OfferingClass,
    OfferingCombination,
    OfferingsOut,
    RequirementOut,
)
from app.schemas.people import GuardianLinkIn, StudentCreateIn
from app.services import audit, sms
from app.services import students as student_service
from app.services.people import decrypt_phone, flush_or_rule

DOCUMENT_TYPES = {"application/pdf", "image/jpeg", "image/png"}
MAX_DOCUMENT_BYTES = 5 * 1024 * 1024
OPEN = (A.INQUIRED, A.REQUIREMENTS_PENDING, A.UNDER_REVIEW)
APPROVED_TEXT = {
    "sw": "{school}: {student} amekubaliwa kujiunga {class_name}. Namba ya usajili {admission_no}.",
    "en": "{school}: {student} has been admitted to {class_name}. Admission number {admission_no}.",
}


def _now() -> datetime:
    return datetime.now(UTC)


def _error(status: int, code: str, field: str, detail: str) -> AppError:
    return AppError(status, code, [{"field": field, "code": detail}])


# ---------------------------------------------------------------- requirements and offerings


def _requirements_for(level_id: uuid.UUID, class_id: uuid.UUID):
    return (
        select(EnrolmentRequirement)
        .where(
            EnrolmentRequirement.deleted_at.is_(None),
            or_(EnrolmentRequirement.education_level_id.is_(None), EnrolmentRequirement.education_level_id == level_id),
            or_(EnrolmentRequirement.class_id.is_(None), EnrolmentRequirement.class_id == class_id),
        )
        .order_by(EnrolmentRequirement.is_required.desc(), EnrolmentRequirement.name_en)
    )


async def offerings(session: AsyncSession, year_id: uuid.UUID | None) -> OfferingsOut:
    """Public, read-only view for families (no personal data)."""
    school = (await session.execute(select(School.name))).scalar_one()
    is_open = (await session.execute(select(SchoolSettings.is_open_for_enrolment))).scalar()
    year_filter = AcademicYear.id == year_id if year_id else AcademicYear.is_current.is_(True)
    year = (
        await session.execute(select(AcademicYear).where(year_filter, AcademicYear.deleted_at.is_(None)))
    ).scalar_one_or_none()
    if year is None:
        raise not_found()
    capacity = dict(
        (
            await session.execute(
                select(Stream.class_id, func.sum(Stream.capacity))
                .where(Stream.deleted_at.is_(None))
                .group_by(Stream.class_id)
            )
        ).all()
    )
    used = dict(
        (
            await session.execute(
                select(Stream.class_id, func.count())
                .select_from(Enrolment)
                .join(Stream, Stream.id == Enrolment.stream_id)
                .where(Enrolment.academic_year_id == year.id, Enrolment.status == EnrolmentStatus.ACTIVE)
                .group_by(Stream.class_id)
            )
        ).all()
    )
    classes = (
        (
            await session.execute(
                select(SchoolClass).where(SchoolClass.deleted_at.is_(None)).order_by(SchoolClass.sort_order)
            )
        )
        .scalars()
        .all()
    )
    out = []
    for c in classes:
        reqs = (await session.execute(_requirements_for(c.education_level_id, c.id))).scalars().all()
        out.append(
            OfferingClass(
                class_id=c.id,
                code=c.code,
                name_en=c.name_en,
                name_sw=c.name_sw,
                places_left=max(0, int(capacity.get(c.id, 0)) - used.get(c.id, 0)),
                requirements=[RequirementOut.model_validate(r) for r in reqs],
            )
        )
    combos = (
        (await session.execute(select(Combination).where(Combination.deleted_at.is_(None)).order_by(Combination.code)))
        .scalars()
        .all()
    )
    return OfferingsOut(
        school_name=school,
        academic_year=year.name,
        open=bool(is_open),
        classes=out,
        combinations=[
            OfferingCombination(combination_id=c.id, code=c.code, name_en=c.name_en, name_sw=c.name_sw) for c in combos
        ],
    )


# ---------------------------------------------------------------- applications


async def _guardian_of(session: AsyncSession, principal: Principal) -> Guardian:
    guardian = (
        await session.execute(
            select(Guardian).where(Guardian.user_id == principal.user_id, Guardian.deleted_at.is_(None))
        )
    ).scalar_one_or_none()
    if guardian is None:
        raise forbidden()
    return guardian


async def _is_guardian(session: AsyncSession, principal: Principal, student_id: uuid.UUID) -> bool:
    return bool(
        (
            await session.execute(
                select(StudentGuardian.id)
                .join(Guardian, Guardian.id == StudentGuardian.guardian_id)
                .where(
                    StudentGuardian.student_id == student_id,
                    StudentGuardian.deleted_at.is_(None),
                    Guardian.user_id == principal.user_id,
                )
            )
        ).first()
    )


def is_staff(principal: Principal) -> bool:
    return any(principal.has(p) for p in ("enrolment.manage", "enrolment.validate", "enrolment.decide"))


async def load(
    session: AsyncSession, principal: Principal, application_id: uuid.UUID, lock: bool = False
) -> EnrolmentApplication:
    """The application, if the caller is enrolment staff or a guardian of the applicant (else 404)."""
    stmt = select(EnrolmentApplication).where(
        EnrolmentApplication.id == application_id, EnrolmentApplication.deleted_at.is_(None)
    )
    app = (await session.execute(stmt.with_for_update() if lock else stmt)).scalar_one_or_none()
    if app is None or not (is_staff(principal) or await _is_guardian(session, principal, app.student_id)):
        raise not_found()
    return app


async def create(session: AsyncSession, principal: Principal, body: ApplicationIn) -> uuid.UUID:
    school_class = (
        await session.execute(
            select(SchoolClass).where(SchoolClass.id == body.class_id, SchoolClass.deleted_at.is_(None))
        )
    ).scalar_one_or_none()
    year = (
        await session.execute(
            select(AcademicYear).where(AcademicYear.id == body.academic_year_id, AcademicYear.deleted_at.is_(None))
        )
    ).scalar_one_or_none()
    if school_class is None or year is None:
        raise _error(
            422, "INVALID_REFERENCE", "class_id" if school_class is None else "academic_year_id", "invalid_value"
        )
    staff_path = principal.has("enrolment.manage")
    if staff_path:
        guardians = body.guardians
        if not guardians:
            raise _error(422, "VALIDATION_ERROR", "guardians", "required")
    else:
        if not principal.has("portal.parent"):
            raise forbidden()
        if not (await session.execute(select(SchoolSettings.is_open_for_enrolment))).scalar():
            raise _error(409, "NOT_ALLOWED", "school", "enrolment_closed")
        guardian = await _guardian_of(session, principal)
        guardians = [
            GuardianLinkIn(guardian_id=guardian.id, relationship=body.relationship, is_primary=True, sms_consent=True)
        ]
    a = body.applicant
    student_id = await student_service.admit(
        session,
        principal,
        StudentCreateIn(
            first_name=a.first_name,
            middle_name=a.middle_name,
            last_name=a.last_name,
            gender=a.gender,
            date_of_birth=a.date_of_birth,
            birth_cert_no=a.birth_cert_no,
            consent_data_processing=True,
            guardians=guardians,
        ),
        commit=False,
    )
    number = (
        await session.execute(
            select(
                func.next_document_no(
                    principal.school_id, literal("APPLICATION"), cast(int(year.name[:4]), SmallInteger)
                )
            )
        )
    ).scalar()
    application = EnrolmentApplication(
        school_id=principal.school_id,
        application_no=f"APP-{year.name[:4]}-{number:04d}",
        student_id=student_id,
        class_id=school_class.id,
        combination_id=body.combination_id,
        academic_year_id=year.id,
        status=A.REQUIREMENTS_PENDING,
        created_by=principal.user_id,
    )
    session.add(application)
    await session.commit()
    return application.id


async def out(session: AsyncSession, application: EnrolmentApplication) -> ApplicationOut:
    row = (
        await session.execute(
            select(
                Student.id,
                Student.admission_no,
                User.first_name,
                User.middle_name,
                User.last_name,
                User.gender,
                User.date_of_birth,
            )
            .join(User, User.id == Student.user_id)
            .where(Student.id == application.student_id)
        )
    ).one()
    level_id = (
        await session.execute(select(SchoolClass.education_level_id).where(SchoolClass.id == application.class_id))
    ).scalar()
    documents = (
        (
            await session.execute(
                select(EnrolmentDocument)
                .where(EnrolmentDocument.application_id == application.id, EnrolmentDocument.deleted_at.is_(None))
                .order_by(EnrolmentDocument.created_at)
            )
        )
        .scalars()
        .all()
    )
    by_requirement = {d.requirement_id: d for d in documents}
    requirements = (await session.execute(_requirements_for(level_id, application.class_id))).scalars().all()
    checklist = [
        ChecklistItem(
            requirement_id=r.id,
            name_en=r.name_en,
            name_sw=r.name_sw,
            is_required=r.is_required,
            document_id=by_requirement[r.id].id if r.id in by_requirement else None,
            status=by_requirement[r.id].validation_status if r.id in by_requirement else "MISSING",
        )
        for r in requirements
    ]
    return ApplicationOut(
        id=application.id,
        application_no=application.application_no,
        status=application.status,
        class_id=application.class_id,
        combination_id=application.combination_id,
        academic_year_id=application.academic_year_id,
        submitted_at=application.submitted_at,
        decided_at=application.decided_at,
        decision_reason=application.decision_reason,
        student=ApplicantOut(
            id=row.id,
            admission_no=row.admission_no,
            gender=row.gender,
            date_of_birth=row.date_of_birth,
            full_name=" ".join(p for p in (row.first_name, row.middle_name, row.last_name) if p),
        ),
        checklist=checklist,
        documents=[DocumentOut.model_validate(d) for d in documents],
    )


async def add_document(
    session: AsyncSession,
    principal: Principal,
    application_id: uuid.UUID,
    requirement_id: uuid.UUID,
    file_name: str,
    data: bytes,
) -> EnrolmentDocument:
    application = await load(session, principal, application_id, lock=True)
    if application.status not in (A.INQUIRED, A.REQUIREMENTS_PENDING):
        raise _error(409, "NOT_ALLOWED", "status", "invalid_value")
    level_id = (
        await session.execute(select(SchoolClass.education_level_id).where(SchoolClass.id == application.class_id))
    ).scalar()
    allowed = {r.id for r in (await session.execute(_requirements_for(level_id, application.class_id))).scalars()}
    if requirement_id not in allowed:
        raise _error(422, "INVALID_REFERENCE", "requirement_id", "invalid_value")
    mime, ext = detect(data, DOCUMENT_TYPES)
    await session.execute(
        update(EnrolmentDocument)
        .where(
            EnrolmentDocument.application_id == application.id,
            EnrolmentDocument.requirement_id == requirement_id,
            EnrolmentDocument.deleted_at.is_(None),
        )
        .values(deleted_at=_now())
    )  # a new upload replaces the old one
    await session.flush()
    document = EnrolmentDocument(
        school_id=principal.school_id,
        application_id=application.id,
        requirement_id=requirement_id,
        file_key="",
        file_name=(file_name or f"document.{ext}")[-255:],
        mime_type=mime,
        size_bytes=len(data),
        sha256=hashlib.sha256(data).hexdigest(),
        created_by=principal.user_id,
    )
    document.file_key = get_storage().put(f"{principal.school_id}/enrolment/{application.id}/{document.id}.{ext}", data)
    session.add(document)
    await session.commit()
    return document


async def submit(session: AsyncSession, principal: Principal, application_id: uuid.UUID) -> EnrolmentApplication:
    application = await load(session, principal, application_id, lock=True)
    if application.status not in (A.INQUIRED, A.REQUIREMENTS_PENDING):
        raise _error(409, "NOT_ALLOWED", "status", "invalid_value")
    current = await out(session, application)
    missing = [i for i in current.checklist if i.is_required and i.status in ("MISSING", "INVALID")]
    if missing:
        raise AppError(
            422,
            "VALIDATION_ERROR",
            [
                {
                    "field": "documents",
                    "code": "required",
                    "requirement_id": str(i.requirement_id),
                    "name_en": i.name_en,
                    "name_sw": i.name_sw,
                }
                for i in missing
            ],
        )
    application.status, application.submitted_at = A.UNDER_REVIEW, _now()
    await session.commit()
    return application


async def decide_document(
    session: AsyncSession, principal: Principal, document_id: uuid.UUID, body: DocumentDecisionIn
) -> EnrolmentApplication:
    document = (
        await session.execute(
            select(EnrolmentDocument)
            .where(EnrolmentDocument.id == document_id, EnrolmentDocument.deleted_at.is_(None))
            .with_for_update()
        )
    ).scalar_one_or_none()
    if document is None:
        raise not_found()
    application = await load(session, principal, document.application_id, lock=True)
    if application.status not in OPEN:
        raise _error(409, "NOT_ALLOWED", "status", "invalid_value")
    document.validation_status = body.status
    document.comment = body.comment
    document.validated_by, document.validated_at = principal.user_id, _now()
    if body.status == DocumentStatus.INVALID and application.status == A.UNDER_REVIEW:
        application.status = A.REQUIREMENTS_PENDING  # the family must upload a better copy
    await session.commit()
    return application


async def document_file(
    session: AsyncSession, principal: Principal, document_id: uuid.UUID
) -> tuple[EnrolmentDocument, bytes]:
    document = (
        await session.execute(
            select(EnrolmentDocument).where(EnrolmentDocument.id == document_id, EnrolmentDocument.deleted_at.is_(None))
        )
    ).scalar_one_or_none()
    if document is None:
        raise not_found()
    await load(session, principal, document.application_id)  # same visibility as the application
    return document, get_storage().get(document.file_key)


async def approve(
    session: AsyncSession,
    principal: Principal,
    application_id: uuid.UUID,
    stream_id: uuid.UUID,
    combination_id: uuid.UUID | None,
    note: str,
) -> tuple[EnrolmentApplication, dict | None]:
    application = await load(session, principal, application_id, lock=True)
    if application.status != A.UNDER_REVIEW:
        raise _error(409, "NOT_ALLOWED", "status", "invalid_value")
    current = await out(session, application)
    not_valid = [i for i in current.checklist if i.is_required and i.status != "VALID"]
    if not_valid:
        raise AppError(
            422,
            "VALIDATION_ERROR",
            [
                {"field": "documents", "code": "documents_not_valid", "requirement_id": str(i.requirement_id)}
                for i in not_valid
            ],
        )
    stream = (
        await session.execute(select(Stream).where(Stream.id == stream_id, Stream.deleted_at.is_(None)))
    ).scalar_one_or_none()
    if stream is None or stream.class_id != application.class_id:
        raise _error(422, "INVALID_REFERENCE", "stream_id", "invalid_value")
    student = (
        await session.execute(select(Student).where(Student.id == application.student_id).with_for_update())
    ).scalar_one()
    today = date.today()
    session.add(
        Enrolment(
            school_id=principal.school_id,
            student_id=student.id,
            stream_id=stream.id,
            academic_year_id=application.academic_year_id,
            combination_id=combination_id or application.combination_id,
            application_id=application.id,
            status=EnrolmentStatus.ACTIVE,
            started_on=today,
            created_by=principal.user_id,
        )
    )
    await flush_or_rule(session)  # capacity trigger -> 409 STREAM_FULL
    if student.status != StudentStatus.ACTIVE:
        session.add(
            StudentStatusHistory(
                school_id=principal.school_id,
                student_id=student.id,
                old_status=student.status,
                new_status=StudentStatus.ACTIVE,
                reason=f"Admitted ({application.application_no})",
                effective_date=today,
                created_by=principal.user_id,
            )
        )
        student.status, student.admission_date = StudentStatus.ACTIVE, today
    application.status, application.decided_at = A.APPROVED, _now()
    application.decided_by, application.decision_reason = principal.user_id, note
    call = await _admission_sms(session, principal, student, application)
    await session.commit()
    return application, call


async def _admission_sms(
    session: AsyncSession, principal: Principal, student: Student, application: EnrolmentApplication
) -> dict | None:
    """Tell the primary guardian (only with SMS consent)."""
    row = (
        await session.execute(
            select(User)
            .join(Guardian, Guardian.user_id == User.id)
            .join(
                StudentGuardian,
                and_(StudentGuardian.guardian_id == Guardian.id, StudentGuardian.student_id == student.id),
            )
            .where(
                StudentGuardian.is_primary.is_(True),
                StudentGuardian.receives_sms.is_(True),
                StudentGuardian.deleted_at.is_(None),
                User.status == UserStatus.ACTIVE,
            )
        )
    ).scalar_one_or_none()
    phone = decrypt_phone(row) if row else None
    if not phone:
        return None
    school = (await session.execute(select(School.name))).scalar_one()
    learner = (await session.execute(select(User.first_name, User.last_name).where(User.id == student.user_id))).one()
    class_name = (
        await session.execute(
            select(SchoolClass.name_sw if row.preferred_language == "sw" else SchoolClass.name_en).where(
                SchoolClass.id == application.class_id
            )
        )
    ).scalar()
    text = APPROVED_TEXT.get(row.preferred_language, APPROVED_TEXT["sw"]).format(
        school=school[:40],
        student=f"{learner.first_name} {learner.last_name}",
        class_name=class_name,
        admission_no=student.admission_no,
    )
    message = await sms.queue_sms(
        session,
        school_id=principal.school_id,
        phone=phone,
        body=text,
        language=row.preferred_language,
        to_user_id=row.id,
        template_key="admission_approved",
        idempotency_key=f"admission:{application.id}",
        related_entity="enrolment_applications",
        related_id=application.id,
    )
    return {"sms_id": str(message.id), "school_id": str(principal.school_id)}


async def close(
    session: AsyncSession, principal: Principal, application_id: uuid.UUID, status: A, reason: str
) -> EnrolmentApplication:
    """Reject (enrolment.decide) or cancel (staff or the applying guardian)."""
    application = await load(session, principal, application_id, lock=True)
    if application.status not in OPEN:
        raise _error(409, "NOT_ALLOWED", "status", "invalid_value")
    application.status, application.decided_at = status, _now()
    application.decided_by, application.decision_reason = principal.user_id, reason
    await audit.record(
        session, "UPDATE", "enrolment_applications", application.id, {"status": status, "reason": reason}
    )
    await session.commit()
    return application
