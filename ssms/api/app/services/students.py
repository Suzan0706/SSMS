"""Students, their guardians and consents. Everything runs in the caller's school context (RLS)."""

import uuid
from datetime import date

from sqlalchemy import SmallInteger, String, cast, func, literal, or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import Principal
from app.core.crypto import get_cipher
from app.core.errors import AppError, not_found
from app.core.pagination import paginate
from app.models import (
    AcademicYear,
    ConsentRecord,
    Enrolment,
    Guardian,
    SchoolClass,
    SchoolSettings,
    Stream,
    Student,
    StudentGuardian,
    StudentStatusHistory,
    User,
)
from app.models.enums import ConsentChannel, ConsentPurpose, EnrolmentStatus, UserStatus
from app.models.enums import StudentStatus as S
from app.schemas.people import (
    ConsentIn,
    EnrolmentOut,
    GuardianLinkIn,
    GuardianOut,
    StatusChangeIn,
    StudentCreateIn,
    StudentListItem,
    StudentOut,
    StudentUpdateIn,
)
from app.services import audit, years
from app.services.people import display_phone, find_user_by_phone, flush_or_rule, grant_role, new_user, now

BIRTH_CERT, NIDA = "students.birth_cert_no", "students.nida"
TRANSITIONS = {
    S.APPLICANT: {S.ACTIVE, S.DROPPED_OUT},
    S.ACTIVE: {S.SUSPENDED, S.TRANSFERRED, S.GRADUATED, S.DROPPED_OUT},
    S.SUSPENDED: {S.ACTIVE, S.TRANSFERRED, S.DROPPED_OUT},
    S.TRANSFERRED: {S.ACTIVE},  # transferred back
    S.DROPPED_OUT: {S.ACTIVE},  # re-admitted
    S.GRADUATED: set(),
}
ENDS_ENROLMENT = {
    S.TRANSFERRED: EnrolmentStatus.TRANSFERRED_OUT,
    S.GRADUATED: EnrolmentStatus.GRADUATED,
    S.DROPPED_OUT: EnrolmentStatus.WITHDRAWN,
}
# A student's class in a year: the running enrolment, or one that finished the year (past years end this way).
SHOWN_ENROLMENTS = (
    EnrolmentStatus.ACTIVE,
    EnrolmentStatus.PROMOTED,
    EnrolmentStatus.REPEATED,
    EnrolmentStatus.GRADUATED,
)


def _encrypt(student: Student, birth_cert_no: str | None, nida: str | None) -> None:
    cipher = get_cipher()
    if birth_cert_no is not None:
        student.birth_cert_no_enc = cipher.encrypt(birth_cert_no, BIRTH_CERT)
        student.birth_cert_no_hash = cipher.blind_index(birth_cert_no, BIRTH_CERT)
    if nida is not None:
        student.nida_enc = cipher.encrypt(nida, NIDA)
        student.nida_hash = cipher.blind_index(nida, NIDA)


async def _current_year(session: AsyncSession) -> AcademicYear:
    year = (
        await session.execute(
            select(AcademicYear).where(AcademicYear.is_current.is_(True), AcademicYear.deleted_at.is_(None))
        )
    ).scalar_one_or_none()
    if year is None:
        raise AppError(422, "INVALID_REFERENCE", [{"field": "academic_year", "code": "required"}])
    return year


async def _student(session: AsyncSession, student_id: uuid.UUID, lock: bool = False) -> Student:
    stmt = select(Student).where(Student.id == student_id, Student.deleted_at.is_(None))
    student = (await session.execute(stmt.with_for_update() if lock else stmt)).scalar_one_or_none()
    if student is None:
        raise not_found()
    return student


async def admit(session: AsyncSession, principal: Principal, body: StudentCreateIn, commit: bool = True) -> uuid.UUID:
    """Admit one student. commit=False lets a bulk import put many admissions in one transaction."""
    if sum(g.is_primary for g in body.guardians) != 1:
        raise AppError(422, "ONE_PRIMARY_GUARDIAN", [{"field": "guardians", "code": "invalid_value"}])
    admitted_on = body.admission_date or date.today()
    prefix = (await session.execute(select(SchoolSettings.admission_prefix))).scalar() or "TZ"
    number = (
        await session.execute(
            select(
                func.next_document_no(principal.school_id, literal("ADMISSION"), cast(admitted_on.year, SmallInteger))
            )
        )
    ).scalar()
    status = S.ACTIVE if body.stream_id else S.APPLICANT

    user = new_user(
        principal,
        first_name=body.first_name,
        middle_name=body.middle_name,
        last_name=body.last_name,
        gender=body.gender,
        date_of_birth=body.date_of_birth,
        status=UserStatus.NO_LOGIN,
        language=body.preferred_language,
    )
    session.add(user)
    await session.flush()
    student = Student(
        school_id=principal.school_id,
        user_id=user.id,
        status=status,
        prem_number=body.prem_number,
        admission_no=f"{prefix}-{admitted_on.year}-{number:04d}",
        admission_date=admitted_on,
        created_by=principal.user_id,
    )
    _encrypt(student, body.birth_cert_no, body.nida)
    session.add(student)
    await session.flush()
    session.add(
        StudentStatusHistory(
            school_id=principal.school_id,
            student_id=student.id,
            old_status=None,
            new_status=status,
            reason="Admission" if body.stream_id else "Application",
            effective_date=admitted_on,
            created_by=principal.user_id,
        )
    )
    if body.stream_id:
        year = await _current_year(session)
        session.add(
            Enrolment(
                school_id=principal.school_id,
                student_id=student.id,
                stream_id=body.stream_id,
                academic_year_id=year.id,
                status=EnrolmentStatus.ACTIVE,
                started_on=admitted_on,
                created_by=principal.user_id,
            )
        )
        await flush_or_rule(session)
    for link in body.guardians:
        guardian = await link_guardian(session, principal, student.id, link)
        if link.is_primary:
            session.add(
                ConsentRecord(
                    school_id=principal.school_id,
                    guardian_id=guardian.id,
                    student_id=student.id,
                    purpose=ConsentPurpose.DATA_PROCESSING,
                    granted=True,
                    channel=ConsentChannel.PAPER,
                    created_by=principal.user_id,
                )
            )
    if commit:
        await session.commit()
    else:
        await session.flush()
    return student.id


async def link_guardian(
    session: AsyncSession, principal: Principal, student_id: uuid.UUID, link: GuardianLinkIn
) -> Guardian:
    """Attach a guardian to a student. A phone already known in this school reuses that person."""
    if link.guardian_id:
        guardian = (
            await session.execute(
                select(Guardian).where(Guardian.id == link.guardian_id, Guardian.deleted_at.is_(None))
            )
        ).scalar_one_or_none()
        if guardian is None:
            raise AppError(422, "INVALID_REFERENCE", [{"field": "guardian_id", "code": "invalid_value"}])
    else:
        user = await find_user_by_phone(session, link.phone)
        if user is None:
            user = new_user(
                principal,
                first_name=link.first_name,
                middle_name=link.middle_name,
                last_name=link.last_name,
                gender=link.gender,
                phone=link.phone,
                email=link.email,
            )
            session.add(user)  # parents sign in with an SMS code: no password
            await session.flush()
        guardian = (
            await session.execute(select(Guardian).where(Guardian.user_id == user.id, Guardian.deleted_at.is_(None)))
        ).scalar_one_or_none()
        if guardian is None:
            guardian = Guardian(
                school_id=principal.school_id, user_id=user.id, occupation=link.occupation, created_by=principal.user_id
            )
            session.add(guardian)
            await session.flush()
        await grant_role(session, principal, user.id, "parent", if_missing=True)

    already = (
        await session.execute(
            select(StudentGuardian.id).where(
                StudentGuardian.student_id == student_id,
                StudentGuardian.guardian_id == guardian.id,
                StudentGuardian.deleted_at.is_(None),
            )
        )
    ).scalar()
    if already:
        raise AppError(409, "DUPLICATE", [{"field": "guardian", "code": "duplicate_in_school"}])
    if link.is_primary:
        await session.execute(
            update(StudentGuardian)
            .where(
                StudentGuardian.student_id == student_id,
                StudentGuardian.is_primary.is_(True),
                StudentGuardian.deleted_at.is_(None),
            )
            .values(is_primary=False)
        )
    session.add(
        StudentGuardian(
            school_id=principal.school_id,
            student_id=student_id,
            guardian_id=guardian.id,
            relationship=link.relationship,
            is_primary=link.is_primary,
            receives_sms=link.receives_sms and link.sms_consent,
            created_by=principal.user_id,
        )
    )
    if link.sms_consent:
        session.add(
            ConsentRecord(
                school_id=principal.school_id,
                guardian_id=guardian.id,
                student_id=student_id,
                purpose=ConsentPurpose.SMS,
                granted=True,
                channel=ConsentChannel.PAPER,
                created_by=principal.user_id,
            )
        )
    await session.flush()
    return guardian


async def unlink_guardian(
    session: AsyncSession, principal: Principal, student_id: uuid.UUID, guardian_id: uuid.UUID, reason: str
) -> None:
    await _student(session, student_id)
    links = (
        (
            await session.execute(
                select(StudentGuardian)
                .where(StudentGuardian.student_id == student_id, StudentGuardian.deleted_at.is_(None))
                .with_for_update()
            )
        )
        .scalars()
        .all()
    )
    link = next((x for x in links if x.guardian_id == guardian_id), None)
    if link is None:
        raise not_found()
    if link.is_primary or len(links) == 1:
        raise AppError(409, "ONE_PRIMARY_GUARDIAN")
    link.deleted_at = now()
    await audit.record(session, "DELETE", "student_guardians", link.id, {"reason": reason})
    await session.commit()


async def guardians_of(session: AsyncSession, principal: Principal, student_id: uuid.UUID) -> list[GuardianOut]:
    rows = (
        await session.execute(
            select(StudentGuardian, Guardian.user_id, User)
            .join(Guardian, Guardian.id == StudentGuardian.guardian_id)
            .join(User, User.id == Guardian.user_id)
            .where(StudentGuardian.student_id == student_id, StudentGuardian.deleted_at.is_(None))
            .order_by(StudentGuardian.is_primary.desc(), User.last_name)
        )
    ).all()
    reveal = principal.has("guardians.manage")
    return [
        GuardianOut(
            guardian_id=link.guardian_id,
            user_id=user_id,
            full_name=user.full_name,
            phone=display_phone(user.phone_enc, user.phone_last4, reveal),
            relationship=link.relationship,
            is_primary=link.is_primary,
            receives_sms=link.receives_sms,
        )
        for link, user_id, user in rows
    ]


async def get(session: AsyncSession, principal: Principal, student_id: uuid.UUID) -> StudentOut:
    student = await _student(session, student_id)
    user = (await session.execute(select(User).where(User.id == student.user_id))).scalar_one()
    row = (
        await session.execute(
            select(
                Stream.id,
                Stream.name,
                SchoolClass.id.label("class_id"),
                SchoolClass.code,
                AcademicYear.name.label("year"),
            )
            .select_from(Enrolment)
            .join(Stream, Stream.id == Enrolment.stream_id)
            .join(SchoolClass, SchoolClass.id == Stream.class_id)
            .join(AcademicYear, AcademicYear.id == Enrolment.academic_year_id)
            .where(Enrolment.student_id == student.id, Enrolment.status == EnrolmentStatus.ACTIVE)
            .order_by(AcademicYear.start_date.desc())
            .limit(1)
        )
    ).first()
    enrolment = (
        EnrolmentOut(
            stream_id=row.id, stream_name=row.name, class_id=row.class_id, class_code=row.code, academic_year=row.year
        )
        if row
        else None
    )
    return StudentOut(
        id=student.id,
        user_id=user.id,
        admission_no=student.admission_no,
        first_name=user.first_name,
        middle_name=user.middle_name,
        last_name=user.last_name,
        full_name=user.full_name,
        gender=user.gender,
        date_of_birth=user.date_of_birth,
        status=student.status,
        admission_date=student.admission_date,
        prem_number=student.prem_number,
        has_birth_cert_no=student.birth_cert_no_enc is not None,
        has_nida=student.nida_enc is not None,
        preferred_language=user.preferred_language,
        enrolment=enrolment,
        guardians=await guardians_of(session, principal, student.id),
    )


async def list_page(
    session: AsyncSession,
    *,
    q: str | None,
    class_id: uuid.UUID | None,
    stream_id: uuid.UUID | None,
    status: S | None,
    limit: int,
    cursor: str | None,
) -> tuple[list[StudentListItem], str | None]:
    year = await years.viewing_year(session)
    current = (
        select(Enrolment.student_id, Enrolment.stream_id)
        .where(Enrolment.academic_year_id == year, Enrolment.status.in_(SHOWN_ENROLMENTS))
        .subquery()
    )
    sort_last = func.lower(User.last_name, type_=String).label("sort_last")
    sort_first = func.lower(User.first_name, type_=String).label("sort_first")
    stmt = (
        select(
            Student.id,
            Student.admission_no,
            User.first_name,
            User.middle_name,
            User.last_name,
            User.gender,
            Student.status,
            SchoolClass.code.label("class_code"),
            Stream.name.label("stream_name"),
            sort_last,
            sort_first,
        )
        .join(User, User.id == Student.user_id)
        .outerjoin(current, current.c.student_id == Student.id)
        .outerjoin(Stream, Stream.id == current.c.stream_id)
        .outerjoin(SchoolClass, SchoolClass.id == Stream.class_id)
        .where(Student.deleted_at.is_(None))
    )
    if q:
        term = q.strip().replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
        stmt = stmt.where(
            or_(
                Student.admission_no.ilike(f"{term}%"),
                User.last_name.ilike(f"{term}%"),
                User.first_name.ilike(f"{term}%"),
            )
        )
    if class_id:
        stmt = stmt.where(SchoolClass.id == class_id)
    if stream_id:
        stmt = stmt.where(Stream.id == stream_id)
    if status:
        stmt = stmt.where(Student.status == status)
    rows, next_cursor = await paginate(session, stmt, [sort_last, sort_first, Student.id], limit, cursor)
    items = [
        StudentListItem(
            id=r.id,
            admission_no=r.admission_no,
            gender=r.gender,
            status=r.status,
            full_name=" ".join(p for p in (r.first_name, r.middle_name, r.last_name) if p),
            class_code=r.class_code,
            stream_name=r.stream_name,
        )
        for r in rows
    ]
    return items, next_cursor


async def update_student(
    session: AsyncSession, principal: Principal, student_id: uuid.UUID, body: StudentUpdateIn
) -> None:
    student = await _student(session, student_id, lock=True)
    user = (await session.execute(select(User).where(User.id == student.user_id).with_for_update())).scalar_one()
    data = body.model_dump(exclude_unset=True)
    for field in ("first_name", "middle_name", "last_name", "gender", "date_of_birth", "preferred_language"):
        if field in data:
            setattr(user, field, data[field])
    if "prem_number" in data:
        student.prem_number = data["prem_number"]
    _encrypt(student, data.get("birth_cert_no"), data.get("nida"))
    await session.commit()


async def change_status(
    session: AsyncSession, principal: Principal, student_id: uuid.UUID, body: StatusChangeIn
) -> StudentStatusHistory:
    student = await _student(session, student_id, lock=True)
    if body.new_status not in TRANSITIONS[student.status]:
        raise AppError(
            409,
            "STATUS_TRANSITION",
            [{"from": student.status, "to": body.new_status}],
            old=student.status,
            new=body.new_status,
        )
    history = StudentStatusHistory(
        school_id=principal.school_id,
        student_id=student.id,
        old_status=student.status,
        new_status=body.new_status,
        reason=body.reason,
        effective_date=body.effective_date,
        created_by=principal.user_id,
    )
    session.add(history)
    student.status = body.new_status
    if body.new_status in ENDS_ENROLMENT:
        await session.execute(
            update(Enrolment)
            .where(Enrolment.student_id == student.id, Enrolment.status == EnrolmentStatus.ACTIVE)
            .values(status=ENDS_ENROLMENT[body.new_status], ended_on=body.effective_date)
        )
    await session.commit()
    return history


async def identifiers(session: AsyncSession, student_id: uuid.UUID) -> dict:
    """Decrypt the identifiers of one student; every read is audited (VIEW_SENSITIVE)."""
    student = await _student(session, student_id)
    cipher = get_cipher()
    out = {
        "birth_cert_no": cipher.decrypt(student.birth_cert_no_enc, BIRTH_CERT) if student.birth_cert_no_enc else None,
        "nida": cipher.decrypt(student.nida_enc, NIDA) if student.nida_enc else None,
    }
    await audit.record(session, "VIEW_SENSITIVE", "students", student.id, {"fields": ["birth_cert_no", "nida"]})
    await session.commit()
    return out


async def record_consent(
    session: AsyncSession, principal: Principal, guardian_id: uuid.UUID, body: ConsentIn
) -> ConsentRecord:
    guardian = (
        await session.execute(select(Guardian).where(Guardian.id == guardian_id, Guardian.deleted_at.is_(None)))
    ).scalar_one_or_none()
    if guardian is None:
        raise not_found()
    if not body.granted:  # withdrawal closes earlier grants for the same purpose
        scope = [
            ConsentRecord.guardian_id == guardian_id,
            ConsentRecord.purpose == body.purpose,
            ConsentRecord.granted.is_(True),
            ConsentRecord.withdrawn_at.is_(None),
        ]
        if body.student_id:
            scope.append(ConsentRecord.student_id == body.student_id)
        await session.execute(update(ConsentRecord).where(*scope).values(withdrawn_at=now()))
        if body.purpose == ConsentPurpose.SMS:
            links = [StudentGuardian.guardian_id == guardian_id, StudentGuardian.deleted_at.is_(None)]
            if body.student_id:
                links.append(StudentGuardian.student_id == body.student_id)
            await session.execute(update(StudentGuardian).where(*links).values(receives_sms=False))
    record = ConsentRecord(
        school_id=principal.school_id,
        guardian_id=guardian_id,
        student_id=body.student_id,
        purpose=body.purpose,
        granted=body.granted,
        channel=body.channel,
        created_by=principal.user_id,
    )
    session.add(record)
    await session.commit()
    return record


async def consents_of(session: AsyncSession, guardian_id: uuid.UUID) -> list[ConsentRecord]:
    return list(
        (
            await session.execute(
                select(ConsentRecord)
                .where(ConsentRecord.guardian_id == guardian_id)
                .order_by(ConsentRecord.recorded_at.desc())
                .limit(200)
            )
        ).scalars()
    )
