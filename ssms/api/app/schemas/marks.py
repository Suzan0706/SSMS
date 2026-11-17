"""Mark sheets and offline batch sync."""

import uuid
from datetime import datetime
from decimal import Decimal

from pydantic import BaseModel, Field, model_validator


class SheetComponent(BaseModel):
    id: uuid.UUID
    code: str
    name_en: str
    name_sw: str
    max_score: Decimal
    weight: Decimal


class SheetMark(BaseModel):
    score: Decimal | None
    is_absent: bool
    version: int
    locked: bool


class SheetStudent(BaseModel):
    enrolment_id: uuid.UUID
    admission_no: str
    full_name: str
    marks: dict[str, SheetMark] = Field(description="component id -> mark")


class SheetOut(BaseModel):
    term_id: uuid.UUID
    stream_id: uuid.UUID
    subject_id: uuid.UUID
    locked: bool
    components: list[SheetComponent]
    students: list[SheetStudent]


class MarkItem(BaseModel):
    enrolment_id: uuid.UUID
    subject_id: uuid.UUID
    component_id: uuid.UUID
    score: Decimal | None = Field(default=None, ge=0, max_digits=6, decimal_places=2)
    is_absent: bool = False
    version: int = Field(default=0, ge=0, description="0 = new on this device; else the version it was based on")
    client_updated_at: datetime | None = None

    @model_validator(mode="after")
    def _absent(self):
        if self.is_absent and self.score is not None:
            raise ValueError("invalid_value")
        return self


class BatchIn(BaseModel):
    items: list[MarkItem] = Field(min_length=1, max_length=500)


class ServerMark(BaseModel):
    score: Decimal | None
    is_absent: bool
    version: int


class ItemResult(BaseModel):
    index: int
    status: str = Field(description="ok, conflict or error")
    version: int | None = None
    error_code: str | None = None
    server: ServerMark | None = Field(default=None, description="Current server value when status is conflict")


class BatchOut(BaseModel):
    saved: int
    conflicts: int
    errors: int
    results: list[ItemResult]
