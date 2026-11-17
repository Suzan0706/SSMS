"""Academic configuration: levels, years, terms, holidays, classes, streams, subjects, combinations, rooms,
grading schemes and assessment components."""

import uuid
from datetime import date
from decimal import Decimal
from typing import Annotated

from pydantic import AfterValidator, BaseModel, ConfigDict, Field, model_validator

from app.models.enums import ComponentCode, EducationLevelCode, RoomType

NameEn = Annotated[str, Field(min_length=2, max_length=80)]
NameSw = Annotated[str, Field(min_length=2, max_length=80)]


class _Out(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID


# ---------------------------------------------------------------- levels, years, terms, holidays


class LevelIn(BaseModel):
    code: EducationLevelCode
    name_en: str = Field(min_length=2, max_length=40)
    name_sw: str = Field(min_length=2, max_length=40)
    sort_order: int = Field(ge=1, le=20)


class LevelOut(_Out):
    code: str
    name_en: str
    name_sw: str
    sort_order: int


class YearIn(BaseModel):
    name: str = Field(pattern=r"^\d{4}(/\d{4})?$", examples=["2027"])
    start_date: date
    end_date: date
    is_current: bool = False

    @model_validator(mode="after")
    def _dates(self):
        if self.end_date <= self.start_date:
            raise ValueError("invalid_value")
        return self


class YearUpdate(BaseModel):
    start_date: date | None = None
    end_date: date | None = None
    is_current: bool | None = None


class AcademicYearOut(_Out):
    name: str
    start_date: date
    end_date: date
    is_current: bool


class TermIn(BaseModel):
    academic_year_id: uuid.UUID
    term_no: int = Field(ge=1, le=4)
    name_en: str = Field(min_length=2, max_length=30)
    name_sw: str = Field(min_length=2, max_length=30)
    start_date: date
    end_date: date


class TermUpdate(BaseModel):
    name_en: str | None = Field(default=None, min_length=2, max_length=30)
    name_sw: str | None = Field(default=None, min_length=2, max_length=30)
    start_date: date | None = None
    end_date: date | None = None


class TermOut(_Out):
    academic_year_id: uuid.UUID
    term_no: int
    name_en: str
    name_sw: str
    start_date: date
    end_date: date


class HolidayIn(BaseModel):
    holiday_date: date
    name_en: NameEn
    name_sw: NameSw
    kind: str = Field(default="NATIONAL", pattern=r"^(NATIONAL|SCHOOL_CLOSURE)$")


class HolidayOut(_Out):
    holiday_date: date
    name_en: str
    name_sw: str
    kind: str


# ---------------------------------------------------------------- classes and streams


class ClassIn(BaseModel):
    education_level_id: uuid.UUID
    code: str = Field(pattern=r"^[A-Z0-9]{1,6}$", examples=["F3"])
    name_en: str = Field(min_length=2, max_length=30)
    name_sw: str = Field(min_length=2, max_length=30)
    sort_order: int = Field(ge=1, le=100)
    next_class_id: uuid.UUID | None = None


class ClassUpdate(BaseModel):
    name_en: str | None = Field(default=None, min_length=2, max_length=30)
    name_sw: str | None = Field(default=None, min_length=2, max_length=30)
    sort_order: int | None = Field(default=None, ge=1, le=100)
    next_class_id: uuid.UUID | None = None


class ClassOut(_Out):
    education_level_id: uuid.UUID
    code: str
    name_en: str
    name_sw: str
    sort_order: int
    next_class_id: uuid.UUID | None


class StreamIn(BaseModel):
    class_id: uuid.UUID
    name: str = Field(pattern=r"^[A-Za-z0-9 ]{1,10}$", examples=["B"])
    capacity: int = Field(ge=1, le=200)
    home_room_id: uuid.UUID | None = None


class StreamUpdate(BaseModel):
    name: str | None = Field(default=None, pattern=r"^[A-Za-z0-9 ]{1,10}$")
    capacity: int | None = Field(default=None, ge=1, le=200)
    home_room_id: uuid.UUID | None = None


class StreamOut(_Out):
    class_id: uuid.UUID
    name: str
    capacity: int
    home_room_id: uuid.UUID | None = None
    enrolled: int | None = Field(default=None, description="Active enrolments in the current year")


class ClassTeacherIn(BaseModel):
    academic_year_id: uuid.UUID
    staff_id: uuid.UUID


class ClassTeacherOut(_Out):
    stream_id: uuid.UUID
    academic_year_id: uuid.UUID
    staff_id: uuid.UUID


# ---------------------------------------------------------------- subjects, combinations, rooms


class SubjectIn(BaseModel):
    code: str = Field(pattern=r"^[A-Z0-9-]{2,10}$", examples=["CHEM"])
    necta_code: str | None = Field(default=None, pattern=r"^[0-9]{3,5}$", examples=["032"])
    name_en: NameEn
    name_sw: NameSw
    department_id: uuid.UUID | None = None
    room_type: RoomType = RoomType.CLASSROOM


class SubjectUpdate(BaseModel):
    necta_code: str | None = Field(default=None, pattern=r"^[0-9]{3,5}$")
    name_en: NameEn | None = None
    name_sw: NameSw | None = None
    department_id: uuid.UUID | None = None
    room_type: RoomType | None = None


class SubjectOut(_Out):
    code: str
    necta_code: str | None
    name_en: str
    name_sw: str
    department_id: uuid.UUID | None
    room_type: str


class ClassSubjectItem(BaseModel):
    subject_id: uuid.UUID
    is_compulsory: bool = True
    periods_per_week: int = Field(default=4, ge=1, le=12)


class ClassSubjectOut(ClassSubjectItem):
    model_config = ConfigDict(from_attributes=True)
    code: str
    name_en: str
    name_sw: str


class CombinationSubjectItem(BaseModel):
    subject_id: uuid.UUID
    is_principal: bool = True


class CombinationIn(BaseModel):
    education_level_id: uuid.UUID
    code: str = Field(pattern=r"^[A-Z]{2,6}$", examples=["PCM"])
    name_en: str = Field(min_length=2, max_length=100)
    name_sw: str = Field(min_length=2, max_length=100)
    subjects: list[CombinationSubjectItem] = Field(min_length=1, max_length=8)


class CombinationUpdate(BaseModel):
    name_en: str | None = Field(default=None, min_length=2, max_length=100)
    name_sw: str | None = Field(default=None, min_length=2, max_length=100)
    subjects: list[CombinationSubjectItem] | None = Field(default=None, min_length=1, max_length=8)


class CombinationOut(_Out):
    education_level_id: uuid.UUID
    code: str
    name_en: str
    name_sw: str
    subjects: list[CombinationSubjectItem] = []


def _clean_name(value: str) -> str:
    cleaned = " ".join(value.split())
    if len(cleaned) < 2:
        raise ValueError("Name is too short")
    return cleaned


class RoomEquipmentIn(BaseModel):
    name: Annotated[str, AfterValidator(_clean_name)] = Field(min_length=2, max_length=60, examples=["Projector"])
    quantity: int = Field(default=1, ge=1, le=10000)


class RoomEquipmentOut(BaseModel):
    equipment_id: uuid.UUID
    name: str
    quantity: int


class EquipmentItemIn(BaseModel):
    name: Annotated[str, AfterValidator(_clean_name)] = Field(min_length=2, max_length=60)


class EquipmentItemOut(BaseModel):
    id: uuid.UUID
    name: str
    rooms: int = Field(default=0, description="How many rooms have it")


class RoomIn(BaseModel):
    code: str = Field(pattern=r"^[A-Za-z0-9-]{1,12}$", examples=["LAB1"])
    name: str = Field(min_length=2, max_length=60)
    room_type: RoomType = RoomType.CLASSROOM
    capacity: int = Field(ge=1, le=1000)
    equipment: list[RoomEquipmentIn] = Field(default=[], max_length=50)


class RoomUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=2, max_length=60)
    room_type: RoomType | None = None
    capacity: int | None = Field(default=None, ge=1, le=1000)
    equipment: list[RoomEquipmentIn] | None = Field(default=None, max_length=50, description="Replaces the whole list")


class RoomOut(_Out):
    code: str
    name: str
    room_type: str
    capacity: int
    equipment: list[RoomEquipmentOut] = []


# ---------------------------------------------------------------- grading and assessment


class BandIn(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    letter: str = Field(pattern=r"^[A-Z][+-]?$")
    min_score: int = Field(ge=0, le=100)
    max_score: int = Field(ge=0, le=100)
    points: int = Field(ge=0, le=9)
    remark_en: str = Field(min_length=1, max_length=20)
    remark_sw: str = Field(min_length=1, max_length=20)


class DivisionIn(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    division: str = Field(pattern=r"^(I|II|III|IV|0)$")
    min_points: int = Field(ge=0)
    max_points: int = Field(ge=0)


class GradingSchemeIn(BaseModel):
    """A change creates a new version; published results keep the version they were graded with."""

    education_level_id: uuid.UUID
    academic_year_id: uuid.UUID
    name: str = Field(min_length=2, max_length=60)
    best_n_subjects: int | None = Field(default=None, ge=1, le=12)
    bands: list[BandIn] = Field(min_length=2, max_length=12)
    divisions: list[DivisionIn] = Field(default_factory=list, max_length=6)

    @model_validator(mode="after")
    def _ranges(self):
        bands = sorted(self.bands, key=lambda b: b.min_score)
        if len({b.letter for b in bands}) != len(bands) or any(b.max_score < b.min_score for b in bands):
            raise ValueError("invalid_value")
        if (
            bands[0].min_score != 0
            or bands[-1].max_score != 100
            or any(nxt.min_score != cur.max_score + 1 for cur, nxt in zip(bands, bands[1:], strict=False))
        ):
            raise ValueError("bands_gap")  # every whole score 0..100 must have one grade
        divisions = sorted(self.divisions, key=lambda d: d.min_points)
        if any(d.max_points < d.min_points for d in divisions) or any(
            nxt.min_points <= cur.max_points for cur, nxt in zip(divisions, divisions[1:], strict=False)
        ):
            raise ValueError("divisions_overlap")
        if divisions and not self.best_n_subjects:
            raise ValueError("required")  # divisions are computed from the best n subjects
        return self


class GradingSchemeOut(_Out):
    education_level_id: uuid.UUID
    academic_year_id: uuid.UUID
    name: str
    version: int
    best_n_subjects: int | None
    is_active: bool
    bands: list[BandIn]
    divisions: list[DivisionIn]


class ComponentIn(BaseModel):
    term_id: uuid.UUID
    education_level_id: uuid.UUID
    subject_id: uuid.UUID | None = Field(default=None, description="Empty = every subject of the level")
    code: ComponentCode
    name_en: str = Field(min_length=2, max_length=40)
    name_sw: str = Field(min_length=2, max_length=40)
    max_score: Decimal = Field(gt=0, le=1000, max_digits=6, decimal_places=2)
    weight: Decimal = Field(gt=0, le=100, max_digits=5, decimal_places=2)


class ComponentUpdate(BaseModel):
    name_en: str | None = Field(default=None, min_length=2, max_length=40)
    name_sw: str | None = Field(default=None, min_length=2, max_length=40)
    max_score: Decimal | None = Field(default=None, gt=0, le=1000, max_digits=6, decimal_places=2)
    weight: Decimal | None = Field(default=None, gt=0, le=100, max_digits=5, decimal_places=2)


class ComponentOut(_Out):
    term_id: uuid.UUID
    education_level_id: uuid.UUID
    subject_id: uuid.UUID | None
    code: str
    name_en: str
    name_sw: str
    max_score: Decimal
    weight: Decimal


class WeightCheckRow(BaseModel):
    education_level_id: uuid.UUID
    subject_id: uuid.UUID | None
    subject_code: str | None
    total_weight: Decimal
    components: int
    ok: bool
