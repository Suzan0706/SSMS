from pydantic import BaseModel, ConfigDict, Field

from app.models.enums import EducationLevel, RoomType


class SubjectIn(BaseModel):
    subject_code: str = Field(max_length=10, pattern=r"^[A-Z0-9-]+$")
    necta_code: str | None = Field(default=None, max_length=5)
    name_en: str = Field(max_length=80)
    name_sw: str = Field(max_length=80)
    department_id: int
    room_type_required: RoomType = RoomType.CLASSROOM
    description: str | None = None


class SubjectOut(SubjectIn):
    model_config = ConfigDict(from_attributes=True)

    subject_id: int
    is_active: bool


class CourseIn(BaseModel):
    course_code: str = Field(max_length=10, pattern=r"^[A-Z0-9-]+$")
    course_name: str = Field(max_length=100)
    course_name_sw: str = Field(max_length=100)
    course_desc: str | None = None
    education_level: EducationLevel


class CourseUpdate(BaseModel):
    course_name: str | None = Field(default=None, max_length=100)
    course_name_sw: str | None = Field(default=None, max_length=100)
    course_desc: str | None = None
    is_active: bool | None = None


class CourseOut(CourseIn):
    model_config = ConfigDict(from_attributes=True)

    course_id: int
    is_active: bool


class CourseSubjectIn(BaseModel):
    subject_id: int
    is_compulsory: bool = True
    periods_per_week: int = Field(default=4, ge=1, le=12)


class CourseSubjectOut(CourseSubjectIn):
    model_config = ConfigDict(from_attributes=True)

    level_id: int
    subject: SubjectOut


class OfferingIn(BaseModel):
    course_id: int
    academic_year_id: int
    level_id: int
    capacity: int = Field(gt=0, le=2000)
    is_open: bool = True


class OfferingOut(BaseModel):
    offering_id: int
    course_id: int
    course_code: str
    course_name: str
    course_name_sw: str
    academic_year: str
    level_code: str
    level_name_en: str
    level_name_sw: str
    capacity: int
    confirmed: int
    places_left: int
    is_open: bool


class RequirementOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    requirement_id: int
    code: str
    name_en: str
    name_sw: str
    is_mandatory: bool


class OfferingDetail(OfferingOut):
    subjects: list[CourseSubjectOut]
    requirements: list[RequirementOut]
