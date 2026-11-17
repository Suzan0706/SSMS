"""Validation firewall, publication, published results, comments, amendments, analytics."""

import uuid
from datetime import datetime
from decimal import Decimal

from pydantic import BaseModel, Field


class FirewallProblem(BaseModel):
    problem: str
    admission_no: str | None = None
    student: str | None = None
    subject: str | None = None
    component: str | None = None
    teacher: str | None = None
    detail: str | None = None
    message_sw: str
    message_en: str


class FirewallOut(BaseModel):
    ok: bool
    total: int
    problems: list[FirewallProblem] = Field(description="At most 300 are listed; `total` counts all")


class PublishIn(BaseModel):
    term_id: uuid.UUID
    class_id: uuid.UUID


class PublicationOut(BaseModel):
    id: uuid.UUID
    term_id: uuid.UUID
    class_id: uuid.UUID
    scheme_version: int
    published_at: datetime
    students: int
    results: int


class SubjectResult(BaseModel):
    published_result_id: uuid.UUID
    subject_id: uuid.UUID
    subject_code: str
    final_score: Decimal
    letter_grade: str
    points: int
    subject_position: int
    amended: bool


class ClassResultRow(BaseModel):
    enrolment_id: uuid.UUID
    student_id: uuid.UUID
    admission_no: str
    full_name: str
    stream_name: str
    average_score: Decimal
    total_points: int | None
    division: str | None
    class_position: int
    results: list[SubjectResult]


class ClassResultsOut(BaseModel):
    publication: PublicationOut
    items: list[ClassResultRow]
    next_cursor: str | None = None


class ComponentScore(BaseModel):
    code: str
    max_score: Decimal
    weight: Decimal
    score: Decimal | None
    is_absent: bool


class StudentSubjectResult(SubjectResult):
    subject_name_en: str
    subject_name_sw: str
    out_of: int
    remark_en: str | None
    remark_sw: str | None
    components: list[ComponentScore]


class Summary(BaseModel):
    total_score: Decimal
    average_score: Decimal
    subjects_sat: int
    total_points: int | None
    division: str | None
    class_position: int
    class_size: int
    best_n_subjects: int | None


class Attendance(BaseModel):
    present: int
    sessions: int


class Comments(BaseModel):
    class_teacher_comment: str | None = None
    head_teacher_comment: str | None = None


class StudentResultsOut(BaseModel):
    publication_id: uuid.UUID
    enrolment_id: uuid.UUID
    student_id: uuid.UUID
    admission_no: str
    full_name: str
    class_code: str
    class_name_en: str
    class_name_sw: str
    stream_name: str
    term_name_en: str
    term_name_sw: str
    academic_year: str
    scheme_name: str
    scheme_version: int
    published_at: datetime
    summary: Summary
    subjects: list[StudentSubjectResult]
    comments: Comments
    attendance: Attendance
    amended_at: datetime | None = Field(description="Latest approved amendment, shown on the report card")


class CommentsIn(BaseModel):
    class_teacher_comment: str | None = Field(default=None, max_length=400)
    head_teacher_comment: str | None = Field(default=None, max_length=400)


class AmendmentIn(BaseModel):
    new_score: Decimal = Field(ge=0, le=100, max_digits=5, decimal_places=2)
    reason: str = Field(min_length=5, max_length=300)


class DecisionIn(BaseModel):
    note: str | None = Field(default=None, max_length=300)


class RejectIn(BaseModel):
    note: str = Field(min_length=3, max_length=300)


class AmendmentOut(BaseModel):
    id: uuid.UUID
    published_result_id: uuid.UUID
    status: str
    admission_no: str
    student: str
    subject_code: str
    old_score: Decimal
    new_score: Decimal
    reason: str
    requested_by: uuid.UUID
    requested_by_name: str
    decided_by: uuid.UUID | None
    decided_at: datetime | None
    decision_note: str | None
    created_at: datetime


class SubjectStats(BaseModel):
    subject_id: uuid.UUID
    subject_code: str
    students: int
    average: Decimal
    highest: Decimal
    lowest: Decimal
    grades: dict[str, int]
    teacher: str | None


class AnalyticsOut(BaseModel):
    publication_id: uuid.UUID
    students: int
    class_average: Decimal
    divisions: dict[str, int]
    subjects: list[SubjectStats]
    top_students: list[dict]
