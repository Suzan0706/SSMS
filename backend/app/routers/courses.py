"""UC-03 Manage Courses & Subjects, and course offerings (D2 Course Offers)."""
from fastapi import APIRouter, Depends, Query, status
from sqlalchemy import func, or_, select

from app.core.errors import not_found
from app.deps import CurrentUser, DbSession, require_roles
from app.models import (AcademicYear, Course, CourseOffering, CourseSubject, Enrolment, EnrolmentRequirement,
                        Subject)
from app.models.enums import EnrolmentStatus, Role
from app.schemas.courses import (CourseIn, CourseOut, CourseSubjectIn, CourseSubjectOut, CourseUpdate,
                                 OfferingDetail, OfferingIn, OfferingOut, RequirementOut, SubjectIn, SubjectOut)

router = APIRouter(tags=["Courses & Subjects"])
AdminOnly = [Depends(require_roles(Role.ADMIN))]


# ----- Subjects -----
@router.get("/subjects", response_model=list[SubjectOut])
def list_subjects(db: DbSession, user: CurrentUser, active_only: bool = True):
    stmt = select(Subject).order_by(Subject.subject_code)
    if active_only:
        stmt = stmt.where(Subject.is_active)
    return db.scalars(stmt).all()


@router.post("/subjects", response_model=SubjectOut, status_code=status.HTTP_201_CREATED, dependencies=AdminOnly)
def create_subject(body: SubjectIn, db: DbSession):
    subject = Subject(**body.model_dump())
    db.add(subject)
    db.commit()                            # duplicate subject_code -> 409 DUPLICATE
    db.refresh(subject)
    return subject


@router.patch("/subjects/{subject_id}", response_model=SubjectOut, dependencies=AdminOnly)
def update_subject(subject_id: int, body: SubjectIn, db: DbSession):
    subject = db.get(Subject, subject_id)
    if subject is None:
        raise not_found("Subject")
    for k, v in body.model_dump().items():
        setattr(subject, k, v)
    db.commit()
    return subject


# ----- Courses -----
@router.get("/courses", response_model=list[CourseOut])
def list_courses(db: DbSession, user: CurrentUser):
    return db.scalars(select(Course).order_by(Course.course_code)).all()


@router.post("/courses", response_model=CourseOut, status_code=status.HTTP_201_CREATED, dependencies=AdminOnly)
def create_course(body: CourseIn, db: DbSession):
    course = Course(**body.model_dump())
    db.add(course)
    db.commit()
    db.refresh(course)
    return course


@router.patch("/courses/{course_id}", response_model=CourseOut, dependencies=AdminOnly)
def update_course(course_id: int, body: CourseUpdate, db: DbSession):
    course = db.get(Course, course_id)
    if course is None:
        raise not_found("Course")
    for k, v in body.model_dump(exclude_unset=True).items():
        setattr(course, k, v)
    db.commit()
    return course


def _course_subjects(db, course_id: int, level_id: int) -> list[CourseSubject]:
    return list(db.scalars(select(CourseSubject).where(CourseSubject.course_id == course_id,
                                                       CourseSubject.level_id == level_id)).all())


@router.get("/courses/{course_id}/levels/{level_id}/subjects", response_model=list[CourseSubjectOut])
def course_subjects(course_id: int, level_id: int, db: DbSession, user: CurrentUser):
    return _course_subjects(db, course_id, level_id)


@router.put("/courses/{course_id}/levels/{level_id}/subjects", response_model=list[CourseSubjectOut],
            dependencies=AdminOnly)
def set_course_subjects(course_id: int, level_id: int, body: list[CourseSubjectIn], db: DbSession):
    """Replace the subject list of a course at one level."""
    course = db.get(Course, course_id)
    if course is None:
        raise not_found("Course")
    course.subjects = [cs for cs in course.subjects if cs.level_id != level_id] + [
        CourseSubject(course_id=course_id, level_id=level_id, **item.model_dump()) for item in body]
    db.commit()
    return _course_subjects(db, course_id, level_id)


# ----- Offerings -----
def _offering_out(db, o: CourseOffering) -> dict:
    confirmed = db.scalar(select(func.count()).select_from(Enrolment).where(
        Enrolment.offering_id == o.offering_id, Enrolment.status == EnrolmentStatus.CONFIRMED)) or 0
    return dict(offering_id=o.offering_id, course_id=o.course_id, course_code=o.course.course_code,
                course_name=o.course.course_name, course_name_sw=o.course.course_name_sw,
                academic_year=o.academic_year.name, level_code=o.level.code, level_name_en=o.level.name_en,
                level_name_sw=o.level.name_sw, capacity=o.capacity, confirmed=confirmed,
                places_left=max(o.capacity - confirmed, 0), is_open=o.is_open)


@router.get("/course-offerings", response_model=list[OfferingOut])
def list_offerings(db: DbSession, user: CurrentUser, academic_year_id: int | None = None,
                   is_open: bool | None = Query(default=None)):
    """List of courses offered. Defaults to the current academic year."""
    stmt = select(CourseOffering).join(AcademicYear)
    stmt = stmt.where(CourseOffering.academic_year_id == academic_year_id) if academic_year_id \
        else stmt.where(AcademicYear.is_current)
    if is_open is not None:
        stmt = stmt.where(CourseOffering.is_open == is_open)
    return [_offering_out(db, o) for o in db.scalars(stmt.order_by(CourseOffering.offering_id)).all()]


@router.get("/course-offerings/{offering_id}", response_model=OfferingDetail)
def get_offering(offering_id: int, db: DbSession, user: CurrentUser):
    """Course information: subjects at this level and the enrolment requirements."""
    o = db.get(CourseOffering, offering_id)
    if o is None:
        raise not_found("Course offering")
    subjects = db.scalars(select(CourseSubject).where(CourseSubject.course_id == o.course_id,
                                                      CourseSubject.level_id == o.level_id)).all()
    requirements = db.scalars(select(EnrolmentRequirement).where(
        EnrolmentRequirement.is_active,
        or_(EnrolmentRequirement.education_level.is_(None),
            EnrolmentRequirement.education_level == o.course.education_level))).all()
    return OfferingDetail(**_offering_out(db, o),
                          subjects=[CourseSubjectOut.model_validate(s) for s in subjects],
                          requirements=[RequirementOut.model_validate(r) for r in requirements])


@router.post("/course-offerings", response_model=OfferingOut, status_code=status.HTTP_201_CREATED,
             dependencies=AdminOnly)
def create_offering(body: OfferingIn, db: DbSession):
    offering = CourseOffering(**body.model_dump())
    db.add(offering)
    db.commit()                            # one offering per course + year + level
    db.refresh(offering)
    return _offering_out(db, offering)
