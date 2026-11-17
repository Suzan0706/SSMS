"""UC-02: register, search, update students; status changes with history."""
from dataclasses import dataclass, field
from datetime import date

from sqlalchemy import exists, func, or_, select
from sqlalchemy.orm import Session

from app.core.errors import AppError, forbidden, rule_violation
from app.core.security import generate_temporary_password, hash_password
from app.models import (AcademicYear, CourseOffering, Enrolment, Guardian, Student, StudentGuardian,
                        StudentStatusHistory, User)
from app.models.enums import STAFF_ROLES, EnrolmentStatus, Role, StudentStatus
from app.schemas.students import GuardianIn, StatusChangeIn, StudentCreate, StudentUpdate
from app.services.auth import revoke_all_tokens
from app.services.common import next_number

S = StudentStatus

# Allowed status transitions (UC-02 business rule).
ALLOWED_TRANSITIONS: dict[StudentStatus, set[StudentStatus]] = {
    S.APPLICANT: {S.ACTIVE},                       # only through enrolment confirmation
    S.ACTIVE: {S.SUSPENDED, S.TRANSFERRED, S.DROPPED_OUT, S.GRADUATED},
    S.SUSPENDED: {S.ACTIVE, S.DROPPED_OUT},
    S.TRANSFERRED: {S.ACTIVE},                     # re-admission, ADMIN only
    S.DROPPED_OUT: {S.ACTIVE},                     # re-admission, ADMIN only
    S.GRADUATED: set(),
}
READMISSION_FROM = {S.TRANSFERRED, S.DROPPED_OUT}
DEACTIVATES_LOGIN = {S.TRANSFERRED, S.DROPPED_OUT}


@dataclass
class NewAccount:
    user: User
    password: str


@dataclass
class StudentCreated:
    student: Student
    password: str
    new_guardian_accounts: list[NewAccount] = field(default_factory=list)


def _find_or_create_guardian(db: Session, g: GuardianIn) -> tuple[Guardian, NewAccount | None]:
    existing = db.scalar(select(Guardian).join(User, User.user_id == Guardian.user_id)
                         .where(User.phone == g.phone, User.role == Role.PARENT))
    if existing:
        return existing, None
    password = generate_temporary_password()
    user = User(username=f"p{g.phone}", password_hash=hash_password(password), role=Role.PARENT,
                first_name=g.first_name, last_name=g.last_name, gender=g.gender, phone=g.phone,
                preferred_language=g.preferred_language)
    db.add(user)
    db.flush()
    guardian = Guardian(user_id=user.user_id, nida_no=g.nida_no, occupation=g.occupation, address=g.address)
    db.add(guardian)
    db.flush()
    return guardian, NewAccount(user, password)


def create_student(db: Session, data: StudentCreate) -> StudentCreated:
    admission_no = next_number(db, "admission")
    password = generate_temporary_password()
    user = User(username=admission_no.lower(), password_hash=hash_password(password), role=Role.STUDENT,
                first_name=data.first_name, middle_name=data.middle_name, last_name=data.last_name,
                gender=data.gender, date_of_birth=data.date_of_birth, phone=data.phone,
                preferred_language=data.preferred_language)
    db.add(user)
    db.flush()
    student = Student(user_id=user.user_id, admission_no=admission_no, birth_cert_no=data.birth_cert_no,
                      necta_index_no=data.necta_index_no, region=data.region, district=data.district,
                      home_address=data.home_address)
    db.add(student)
    db.flush()
    result = StudentCreated(student, password)
    for g in data.guardians:
        guardian, account = _find_or_create_guardian(db, g)
        if account:
            result.new_guardian_accounts.append(account)
        db.add(StudentGuardian(student_id=student.student_id, guardian_id=guardian.guardian_id,
                               relationship_=g.relationship, is_primary=g.is_primary))
    db.flush()
    db.refresh(student)
    return result


def get_student(db: Session, student_id: int) -> Student:
    student = db.get(Student, student_id)
    if student is None:
        raise AppError(404, "NOT_FOUND", "Student not found", "Mwanafunzi hakupatikana")
    return student


def ensure_can_view(db: Session, user: User, student: Student) -> None:
    """Staff and instructors see all students; a student sees self; a parent sees linked children.
    Others get 404 (not 403) so the existence of a record is not revealed."""
    if user.role in STAFF_ROLES or user.role == Role.INSTRUCTOR:
        return
    if user.role == Role.STUDENT and student.user_id == user.user_id:
        return
    if user.role == Role.PARENT and db.scalar(select(exists().where(
            StudentGuardian.student_id == student.student_id,
            StudentGuardian.guardian_id == Guardian.guardian_id,
            Guardian.user_id == user.user_id))):
        return
    raise AppError(404, "NOT_FOUND", "Student not found", "Mwanafunzi hakupatikana")


def search_students(db: Session, q: str | None, status: StudentStatus | None, level_id: int | None,
                    stream: str | None, page: int, size: int) -> tuple[list[Student], int]:
    stmt = select(Student).join(User, User.user_id == Student.user_id)
    if q:
        like = f"%{q.strip()}%"
        stmt = stmt.where(or_(User.first_name.ilike(like), User.last_name.ilike(like),
                              Student.admission_no.ilike(like), Student.necta_index_no.ilike(like)))
    if status:
        stmt = stmt.where(Student.current_status == status)
    if level_id or stream:
        current = (select(Enrolment.student_id)
                   .join(CourseOffering, CourseOffering.offering_id == Enrolment.offering_id)
                   .join(AcademicYear, AcademicYear.academic_year_id == CourseOffering.academic_year_id)
                   .where(AcademicYear.is_current, Enrolment.status == EnrolmentStatus.CONFIRMED))
        if level_id:
            current = current.where(CourseOffering.level_id == level_id)
        if stream:
            current = current.where(Enrolment.stream == stream)
        stmt = stmt.where(Student.student_id.in_(current))
    total = db.scalar(select(func.count()).select_from(stmt.subquery()))
    rows = db.scalars(stmt.order_by(User.last_name, User.first_name)
                      .offset((page - 1) * size).limit(size)).all()
    return list(rows), total or 0


def update_student(db: Session, student: Student, data: StudentUpdate) -> Student:
    changes = data.model_dump(exclude_unset=True)
    for field_name in ("first_name", "middle_name", "last_name", "gender", "date_of_birth", "phone"):
        if field_name in changes:
            setattr(student.user, field_name, changes.pop(field_name))
    for field_name, value in changes.items():
        setattr(student, field_name, value)
    db.flush()
    return student


def change_status(db: Session, student: Student, data: StatusChangeIn, actor: User,
                  via_enrolment: bool = False) -> StudentStatusHistory:
    # Lock only the students row (serialises concurrent changes), then reload it.
    db.execute(select(Student.student_id).where(Student.student_id == student.student_id).with_for_update())
    db.refresh(student)
    old, new = student.current_status, data.new_status
    if new not in ALLOWED_TRANSITIONS[old]:
        raise rule_violation(f"Status change {old} -> {new} is not allowed",
                             f"Kubadilisha hali kutoka {old} kwenda {new} hakuruhusiwi")
    if old == S.APPLICANT and not via_enrolment:
        raise rule_violation("Applicants become ACTIVE only when their enrolment is confirmed",
                             "Mwombaji anakuwa hai pale tu usajili wake unapothibitishwa")
    if old in READMISSION_FROM and actor.role != Role.ADMIN:
        raise forbidden()

    student.current_status = new
    history = StudentStatusHistory(student_id=student.student_id, old_status=old, new_status=new,
                                   reason=data.reason, effective_date=data.effective_date or date.today(),
                                   changed_by=actor.user_id)
    db.add(history)
    if new in DEACTIVATES_LOGIN:
        student.user.is_active = False
        revoke_all_tokens(db, student.user_id)
    elif old in READMISSION_FROM:
        student.user.is_active = True
    db.flush()
    return history


def status_history(db: Session, student_id: int) -> list[StudentStatusHistory]:
    return list(db.scalars(select(StudentStatusHistory).where(StudentStatusHistory.student_id == student_id)
                           .order_by(StudentStatusHistory.changed_at.desc())).all())
