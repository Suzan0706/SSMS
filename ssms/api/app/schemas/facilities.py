"""Hostels and accommodation, transport, venues."""

import uuid
from datetime import date, datetime, time
from decimal import Decimal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.models.enums import BusStatus, HostelGender
from app.schemas.finance import MoneyOut


class _Out(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID


# ---------------------------------------------------------------- hostels


class HostelIn(BaseModel):
    name: str = Field(min_length=2, max_length=60)
    gender: HostelGender
    warden_staff_id: uuid.UUID | None = None


class HostelUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=2, max_length=60)
    warden_staff_id: uuid.UUID | None = None


class HostelOut(_Out):
    name: str
    gender: str
    warden_staff_id: uuid.UUID | None
    rooms: int = 0
    beds: int = 0


class RoomIn(BaseModel):
    hostel_id: uuid.UUID
    name: str = Field(min_length=1, max_length=20)
    capacity: int = Field(ge=1, le=100)


class RoomUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=20)
    capacity: int | None = Field(default=None, ge=1, le=100)


class RoomOut(_Out):
    hostel_id: uuid.UUID
    name: str
    capacity: int


class AccommodationIn(BaseModel):
    term_id: uuid.UUID
    student_id: uuid.UUID | None = Field(
        default=None, description="Required for guardians and staff; students apply for themselves"
    )
    preferred_hostel_id: uuid.UUID | None = None
    note: str | None = Field(default=None, max_length=300)


class DecisionIn(BaseModel):
    approve: bool
    room_id: uuid.UUID | None = None
    note: str | None = Field(default=None, max_length=300)

    @model_validator(mode="after")
    def _room(self):
        if self.approve != (self.room_id is not None):
            raise ValueError("invalid_value")
        return self


class AccommodationOut(BaseModel):
    id: uuid.UUID
    student_id: uuid.UUID
    admission_no: str
    full_name: str
    gender: str
    term_id: uuid.UUID
    preferred_hostel_id: uuid.UUID | None
    status: str
    note: str | None
    decided_at: datetime | None
    room: str | None = Field(default=None, description="'<hostel> / <room>' once allocated")
    invoice_no: str | None = Field(default=None, description="Invoice the boarding fee was added to")


class Occupant(BaseModel):
    allocation_id: uuid.UUID
    student_id: uuid.UUID
    admission_no: str
    full_name: str


class RoomOccupancy(BaseModel):
    room_id: uuid.UUID
    name: str
    capacity: int
    occupants: list[Occupant]


class OccupancyOut(BaseModel):
    hostel_id: uuid.UUID
    term_id: uuid.UUID
    beds: int
    used: int
    rooms: list[RoomOccupancy]


# ---------------------------------------------------------------- transport


class BusIn(BaseModel):
    bus_no: str = Field(pattern=r"^T ?[0-9]{3} ?[A-Z]{3}$", description="Tanzanian plate, e.g. T 123 DEF")
    capacity: int = Field(ge=1, le=100)
    driver_staff_id: uuid.UUID | None = None


class BusUpdate(BaseModel):
    capacity: int | None = Field(default=None, ge=1, le=100)
    driver_staff_id: uuid.UUID | None = None
    status: BusStatus | None = None


class BusOut(_Out):
    bus_no: str
    capacity: int
    driver_staff_id: uuid.UUID | None
    status: str


class BusSeats(BusOut):
    used: int
    free: int
    driver_name: str | None = None
    driver_phone: str | None = Field(default=None, description="For the transport office: the driver's contact")


class StopIn(BaseModel):
    seq: int = Field(ge=1, le=50)
    name: str = Field(min_length=2, max_length=60)
    pickup_time: time


class StopOut(_Out):
    seq: int
    name: str
    pickup_time: time


class RouteIn(BaseModel):
    name: str = Field(min_length=2, max_length=60)
    description: str | None = Field(default=None, max_length=300)
    term_fee_tzs: Decimal = Field(ge=0, max_digits=14, decimal_places=2)
    stops: list[StopIn] = Field(default_factory=list, max_length=50)


class RouteUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=2, max_length=60)
    description: str | None = Field(default=None, max_length=300)
    term_fee_tzs: Decimal | None = Field(default=None, ge=0, max_digits=14, decimal_places=2)
    stops: list[StopIn] | None = Field(default=None, max_length=50, description="Replaces every stop")


class RouteOut(_Out):
    name: str
    description: str | None
    term_fee_tzs: MoneyOut
    stops: list[StopOut] = []


class AssignmentIn(BaseModel):
    student_id: uuid.UUID
    bus_id: uuid.UUID
    stop_id: uuid.UUID
    term_id: uuid.UUID


class AssignmentOut(BaseModel):
    id: uuid.UUID
    student_id: uuid.UUID
    admission_no: str
    full_name: str
    route_id: uuid.UUID
    route_name: str
    bus_id: uuid.UUID
    bus_no: str
    stop_name: str
    pickup_time: time
    term_id: uuid.UUID
    ended_at: datetime | None
    invoice_no: str | None = Field(default=None, description="Invoice the route fee was added to")


# ---------------------------------------------------------------- venues


class VenueIn(BaseModel):
    name: str = Field(min_length=2, max_length=60)
    total_seats: int = Field(ge=1, le=10000)


class VenueOut(_Out):
    name: str
    total_seats: int


class EventIn(BaseModel):
    venue_id: uuid.UUID
    name: str = Field(min_length=2, max_length=100)
    event_date: date
    time_start: time
    time_end: time
    seats_occupied: int = Field(default=0, ge=0)

    @model_validator(mode="after")
    def _times(self):
        if self.time_end <= self.time_start:
            raise ValueError("invalid_value")
        return self


class EventUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=2, max_length=100)
    event_date: date | None = None
    time_start: time | None = None
    time_end: time | None = None
    seats_occupied: int | None = Field(default=None, ge=0)


class EventOut(_Out):
    venue_id: uuid.UUID
    name: str
    event_date: date
    time_start: time
    time_end: time
    seats_occupied: int
    organiser_id: uuid.UUID | None
