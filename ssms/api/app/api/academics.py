"""Academic configuration: everyone signed in may read it; changes need academics.configure."""

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, Query, Response, status
from sqlalchemy import extract, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import Principal, active_principal, require_permission
from app.db.session import get_session
from app.models import (
    AcademicYear,
    AssessmentComponent,
    ClassSubject,
    Combination,
    EducationLevel,
    Enrolment,
    EquipmentItem,
    MarkEntry,
    PublicHoliday,
    Room,
    RoomEquipment,
    SchoolClass,
    Stream,
    Subject,
    Term,
    TimetableSlot,
)
from app.models.enums import EnrolmentStatus
from app.schemas.academics import (
    AcademicYearOut,
    ClassIn,
    ClassOut,
    ClassSubjectItem,
    ClassSubjectOut,
    ClassTeacherIn,
    ClassTeacherOut,
    ClassUpdate,
    CombinationIn,
    CombinationOut,
    CombinationUpdate,
    ComponentIn,
    ComponentOut,
    ComponentUpdate,
    EquipmentItemIn,
    EquipmentItemOut,
    GradingSchemeIn,
    GradingSchemeOut,
    HolidayIn,
    HolidayOut,
    LevelIn,
    LevelOut,
    RoomIn,
    RoomOut,
    RoomUpdate,
    StreamIn,
    StreamOut,
    StreamUpdate,
    SubjectIn,
    SubjectOut,
    SubjectUpdate,
    TermIn,
    TermOut,
    TermUpdate,
    WeightCheckRow,
    YearIn,
    YearUpdate,
)
from app.services import academics as service
from app.services import crud
from app.services import rooms as rooms_service

router = APIRouter(tags=["academics"])
Session = Annotated[AsyncSession, Depends(get_session)]
Reader = Annotated[Principal, Depends(active_principal)]
Configurer = Annotated[Principal, require_permission("academics.configure")]
Reason = Annotated[str, Query(min_length=3, max_length=300, description="Why it is removed (audited)")]


def _gone() -> Response:
    return Response(status_code=status.HTTP_204_NO_CONTENT)


# ---------------------------------------------------------------- levels


@router.get("/education-levels", response_model=list[LevelOut])
async def list_levels(_: Reader, session: Session):
    return await crud.list_live(session, EducationLevel, EducationLevel.sort_order)


@router.post("/education-levels", response_model=LevelOut, status_code=201)
async def create_level(body: LevelIn, principal: Configurer, session: Session):
    return await crud.create(session, principal, EducationLevel, body.model_dump())


# ---------------------------------------------------------------- years


@router.get("/academic-years", response_model=list[AcademicYearOut])
async def list_years(_: Reader, session: Session):
    return await crud.list_live(session, AcademicYear, AcademicYear.start_date.desc(), limit=50)


@router.post(
    "/academic-years",
    response_model=AcademicYearOut,
    status_code=201,
    summary="New year; is_current=true makes it the only current year",
)
async def create_year(body: YearIn, principal: Configurer, session: Session):
    return await service.create_year(session, principal, body)


@router.patch("/academic-years/{year_id}", response_model=AcademicYearOut)
async def update_year(year_id: uuid.UUID, body: YearUpdate, _: Configurer, session: Session):
    return await service.update_year(session, year_id, body)


@router.delete("/academic-years/{year_id}", status_code=204, responses={409: {"description": "in use"}})
async def delete_year(year_id: uuid.UUID, reason: Reason, _: Configurer, session: Session):
    await crud.soft_delete(
        session,
        AcademicYear,
        year_id,
        reason,
        blockers=[
            select(Term.id).where(Term.academic_year_id == year_id, Term.deleted_at.is_(None)),
            select(Enrolment.id).where(Enrolment.academic_year_id == year_id),
        ],
    )
    return _gone()


# ---------------------------------------------------------------- terms


@router.get("/terms", response_model=list[TermOut])
async def list_terms(_: Reader, session: Session, academic_year_id: uuid.UUID | None = None):
    where = [Term.academic_year_id == academic_year_id] if academic_year_id else []
    return await crud.list_live(session, Term, Term.start_date.desc(), where=where, limit=50)


@router.post(
    "/terms",
    response_model=TermOut,
    status_code=201,
    responses={409: {"description": "overlaps another term"}, 422: {"description": "outside_year"}},
)
async def create_term(body: TermIn, principal: Configurer, session: Session):
    return await service.create_term(session, principal, body)


@router.patch("/terms/{term_id}", response_model=TermOut)
async def update_term(term_id: uuid.UUID, body: TermUpdate, _: Configurer, session: Session):
    return await service.update_term(session, term_id, body)


@router.delete("/terms/{term_id}", status_code=204)
async def delete_term(term_id: uuid.UUID, reason: Reason, _: Configurer, session: Session):
    await crud.soft_delete(
        session,
        Term,
        term_id,
        reason,
        blockers=[
            select(AssessmentComponent.id).where(
                AssessmentComponent.term_id == term_id, AssessmentComponent.deleted_at.is_(None)
            )
        ],
    )
    return _gone()


# ---------------------------------------------------------------- holidays


@router.get("/public-holidays", response_model=list[HolidayOut])
async def list_holidays(_: Reader, session: Session, year: Annotated[int | None, Query(ge=2000, le=2100)] = None):
    where = [extract("year", PublicHoliday.holiday_date) == year] if year else []
    return await crud.list_live(session, PublicHoliday, PublicHoliday.holiday_date, where=where)


@router.post("/public-holidays", response_model=HolidayOut, status_code=201)
async def create_holiday(body: HolidayIn, principal: Configurer, session: Session):
    return await crud.create(session, principal, PublicHoliday, body.model_dump())


@router.delete("/public-holidays/{holiday_id}", status_code=204)
async def delete_holiday(holiday_id: uuid.UUID, reason: Reason, _: Configurer, session: Session):
    await crud.soft_delete(session, PublicHoliday, holiday_id, reason)
    return _gone()


# ---------------------------------------------------------------- classes


@router.get("/classes", response_model=list[ClassOut])
async def list_classes(_: Reader, session: Session):
    return await crud.list_live(session, SchoolClass, SchoolClass.sort_order)


@router.post("/classes", response_model=ClassOut, status_code=201)
async def create_class(body: ClassIn, principal: Configurer, session: Session):
    await service.check_next_class(session, body.education_level_id, body.next_class_id)
    return await crud.create(session, principal, SchoolClass, body.model_dump())


@router.patch("/classes/{class_id}", response_model=ClassOut)
async def update_class(class_id: uuid.UUID, body: ClassUpdate, _: Configurer, session: Session):
    current = await crud.get_live(session, SchoolClass, class_id)
    data = body.model_dump(exclude_unset=True)
    if "next_class_id" in data:
        await service.check_next_class(session, current.education_level_id, data["next_class_id"], class_id)
    return await crud.update(session, SchoolClass, class_id, data)


@router.delete("/classes/{class_id}", status_code=204)
async def delete_class(class_id: uuid.UUID, reason: Reason, _: Configurer, session: Session):
    await crud.soft_delete(
        session,
        SchoolClass,
        class_id,
        reason,
        blockers=[
            select(Stream.id).where(Stream.class_id == class_id, Stream.deleted_at.is_(None)),
            select(SchoolClass.id).where(SchoolClass.next_class_id == class_id, SchoolClass.deleted_at.is_(None)),
        ],
    )
    return _gone()


@router.get("/classes/{class_id}/subjects", response_model=list[ClassSubjectOut])
async def get_class_subjects(class_id: uuid.UUID, _: Reader, session: Session):
    return await service.class_subjects(session, class_id)


@router.put(
    "/classes/{class_id}/subjects",
    response_model=list[ClassSubjectOut],
    summary="Replace the curriculum of a class (subjects left out are removed)",
)
async def put_class_subjects(
    class_id: uuid.UUID, body: list[ClassSubjectItem], principal: Configurer, session: Session
):
    return await service.replace_class_subjects(session, principal, class_id, body)


# ---------------------------------------------------------------- streams


@router.get("/streams", response_model=list[StreamOut], summary="Streams with current-year enrolment counts")
async def list_streams(_: Reader, session: Session, class_id: uuid.UUID | None = None):
    where = [Stream.class_id == class_id] if class_id else []
    streams = await crud.list_live(session, Stream, Stream.class_id, Stream.name, where=where)
    counts = await service.stream_occupancy(session, [s.id for s in streams])
    return [StreamOut.model_validate(s).model_copy(update={"enrolled": counts.get(s.id, 0)}) for s in streams]


@router.post("/streams", response_model=StreamOut, status_code=201)
async def create_stream(body: StreamIn, principal: Configurer, session: Session):
    await crud.get_live(session, SchoolClass, body.class_id)
    return await crud.create(session, principal, Stream, body.model_dump())


@router.patch("/streams/{stream_id}", response_model=StreamOut)
async def update_stream(stream_id: uuid.UUID, body: StreamUpdate, _: Configurer, session: Session):
    data = body.model_dump(exclude_unset=True)
    if "capacity" in data:
        enrolled = (await service.stream_occupancy(session, [stream_id])).get(stream_id, 0)
        if data["capacity"] < enrolled:
            raise service._invalid("capacity", "stream_full")
    return await crud.update(session, Stream, stream_id, data)


@router.delete("/streams/{stream_id}", status_code=204)
async def delete_stream(stream_id: uuid.UUID, reason: Reason, _: Configurer, session: Session):
    await crud.soft_delete(
        session,
        Stream,
        stream_id,
        reason,
        blockers=[
            select(Enrolment.id).where(Enrolment.stream_id == stream_id, Enrolment.status == EnrolmentStatus.ACTIVE)
        ],
    )
    return _gone()


@router.put("/streams/{stream_id}/class-teacher", response_model=ClassTeacherOut)
async def put_class_teacher(stream_id: uuid.UUID, body: ClassTeacherIn, principal: Configurer, session: Session):
    await crud.get_live(session, Stream, stream_id)
    return await service.set_class_teacher(session, principal, stream_id, body.academic_year_id, body.staff_id)


# ---------------------------------------------------------------- subjects, combinations, rooms


@router.get("/subjects", response_model=list[SubjectOut])
async def list_subjects(_: Reader, session: Session):
    return await crud.list_live(session, Subject, Subject.code)


@router.post("/subjects", response_model=SubjectOut, status_code=201)
async def create_subject(body: SubjectIn, principal: Configurer, session: Session):
    return await crud.create(session, principal, Subject, body.model_dump())


@router.patch("/subjects/{subject_id}", response_model=SubjectOut)
async def update_subject(subject_id: uuid.UUID, body: SubjectUpdate, _: Configurer, session: Session):
    return await crud.update(session, Subject, subject_id, body.model_dump(exclude_unset=True))


@router.delete("/subjects/{subject_id}", status_code=204)
async def delete_subject(subject_id: uuid.UUID, reason: Reason, _: Configurer, session: Session):
    await crud.soft_delete(
        session,
        Subject,
        subject_id,
        reason,
        blockers=[
            select(ClassSubject.id).where(ClassSubject.subject_id == subject_id, ClassSubject.deleted_at.is_(None)),
            select(MarkEntry.id).where(MarkEntry.subject_id == subject_id, MarkEntry.deleted_at.is_(None)),
        ],
    )
    return _gone()


@router.get("/combinations", response_model=list[CombinationOut])
async def list_combinations(_: Reader, session: Session):
    return [
        await service.combination_out(session, c) for c in await crud.list_live(session, Combination, Combination.code)
    ]


@router.post("/combinations", response_model=CombinationOut, status_code=201)
async def create_combination(body: CombinationIn, principal: Configurer, session: Session):
    return await service.create_combination(session, principal, body)


@router.patch("/combinations/{combination_id}", response_model=CombinationOut)
async def update_combination(
    combination_id: uuid.UUID, body: CombinationUpdate, principal: Configurer, session: Session
):
    return await service.update_combination(session, principal, combination_id, body)


@router.delete("/combinations/{combination_id}", status_code=204)
async def delete_combination(combination_id: uuid.UUID, reason: Reason, _: Configurer, session: Session):
    await crud.soft_delete(
        session,
        Combination,
        combination_id,
        reason,
        blockers=[
            select(Enrolment.id).where(
                Enrolment.combination_id == combination_id, Enrolment.status == EnrolmentStatus.ACTIVE
            )
        ],
    )
    return _gone()


@router.get("/rooms", response_model=list[RoomOut], summary="Rooms; repeat equipment_id to need all of them")
async def list_rooms(_: Reader, session: Session, equipment_id: Annotated[list[uuid.UUID], Query()] = []):  # noqa: B006
    return await rooms_service.list_rooms(session, equipment_id)


@router.post("/rooms", response_model=RoomOut, status_code=201)
async def create_room(body: RoomIn, principal: Configurer, session: Session):
    return await rooms_service.create_room(session, principal, body)


@router.patch("/rooms/{room_id}", response_model=RoomOut)
async def update_room(room_id: uuid.UUID, body: RoomUpdate, principal: Configurer, session: Session):
    return await rooms_service.update_room(session, principal, room_id, body)


@router.get("/equipment-items", response_model=list[EquipmentItemOut], summary="Equipment names in this school")
async def list_equipment_items(_: Reader, session: Session):
    return await rooms_service.list_items(session)


@router.patch("/equipment-items/{item_id}", response_model=EquipmentItemOut, summary="Rename, e.g. a misspelling")
async def rename_equipment_item(item_id: uuid.UUID, body: EquipmentItemIn, _: Configurer, session: Session):
    item = await crud.update(session, EquipmentItem, item_id, {"name": body.name})
    return EquipmentItemOut(id=item.id, name=item.name)


@router.delete("/equipment-items/{item_id}", status_code=204, summary="Only when no room has it")
async def delete_equipment_item(item_id: uuid.UUID, reason: Reason, _: Configurer, session: Session):
    await crud.soft_delete(
        session,
        EquipmentItem,
        item_id,
        reason,
        blockers=[
            select(RoomEquipment.id).where(RoomEquipment.equipment_id == item_id, RoomEquipment.deleted_at.is_(None))
        ],
    )
    return _gone()


@router.delete("/rooms/{room_id}", status_code=204)
async def delete_room(room_id: uuid.UUID, reason: Reason, _: Configurer, session: Session):
    await crud.soft_delete(
        session,
        Room,
        room_id,
        reason,
        blockers=[
            select(TimetableSlot.id).where(TimetableSlot.room_id == room_id, TimetableSlot.deleted_at.is_(None)),
            select(Stream.id).where(Stream.home_room_id == room_id, Stream.deleted_at.is_(None)),
        ],
    )
    return _gone()


# ---------------------------------------------------------------- grading and assessment


@router.get("/grading-schemes", response_model=list[GradingSchemeOut])
async def list_schemes(
    _: Reader,
    session: Session,
    education_level_id: uuid.UUID | None = None,
    academic_year_id: uuid.UUID | None = None,
    active: bool = True,
):
    return await service.list_schemes(session, education_level_id, academic_year_id, active)


@router.post(
    "/grading-schemes",
    response_model=GradingSchemeOut,
    status_code=201,
    summary="Save a scheme for a level and year: creates version n+1 and makes it active",
)
async def save_scheme(body: GradingSchemeIn, principal: Configurer, session: Session):
    return await service.save_scheme(session, principal, body)


@router.get("/assessment-components", response_model=list[ComponentOut])
async def list_components(term_id: uuid.UUID, _: Reader, session: Session):
    return await crud.list_live(
        session,
        AssessmentComponent,
        AssessmentComponent.education_level_id,
        AssessmentComponent.code,
        where=[AssessmentComponent.term_id == term_id],
    )


@router.get(
    "/assessment-components/weight-check",
    response_model=list[WeightCheckRow],
    summary="Weight totals per level and subject; each must be 100 before results can be published",
)
async def weight_check(term_id: uuid.UUID, _: Configurer, session: Session):
    return await service.weight_check(session, term_id)


@router.post("/assessment-components", response_model=ComponentOut, status_code=201)
async def create_component(body: ComponentIn, principal: Configurer, session: Session):
    await crud.get_live(session, Term, body.term_id)
    return await crud.create(session, principal, AssessmentComponent, body.model_dump())


@router.patch(
    "/assessment-components/{component_id}",
    response_model=ComponentOut,
    responses={409: {"description": "results_published"}, 422: {"description": "scores_exceed_max"}},
)
async def update_component(component_id: uuid.UUID, body: ComponentUpdate, _: Configurer, session: Session):
    return await service.update_component(session, component_id, body)


@router.delete("/assessment-components/{component_id}", status_code=204)
async def delete_component(component_id: uuid.UUID, reason: Reason, _: Configurer, session: Session):
    await service.delete_component(session, component_id, reason)
    return _gone()
