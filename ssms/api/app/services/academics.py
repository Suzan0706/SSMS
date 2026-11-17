"""Academic configuration rules beyond plain CRUD (caller's school context, RLS)."""

import uuid

from sqlalchemy import and_, func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import Principal
from app.core.errors import AppError, not_found
from app.models import (
    AcademicYear,
    AssessmentComponent,
    ClassSubject,
    Combination,
    CombinationSubject,
    DivisionRule,
    EducationLevel,
    Enrolment,
    GradeBand,
    GradingScheme,
    MarkEntry,
    SchoolClass,
    Staff,
    StreamClassTeacher,
    Subject,
    Term,
)
from app.models.enums import EnrolmentStatus, StaffStatus
from app.schemas.academics import (
    ClassSubjectItem,
    CombinationIn,
    CombinationSubjectItem,
    CombinationUpdate,
    ComponentUpdate,
    GradingSchemeIn,
    GradingSchemeOut,
    TermIn,
    TermUpdate,
    WeightCheckRow,
    YearIn,
    YearUpdate,
)
from app.services import crud
from app.services.people import now


def _invalid(field: str, code: str, status: int = 422) -> AppError:
    return AppError(status, "VALIDATION_ERROR" if status == 422 else "NOT_ALLOWED", [{"field": field, "code": code}])


# ---------------------------------------------------------------- years and terms


async def _clear_current(session: AsyncSession, keep: uuid.UUID | None) -> None:
    await session.execute(
        update(AcademicYear).where(AcademicYear.is_current.is_(True), AcademicYear.id != keep).values(is_current=False)
    )
    await session.flush()


async def create_year(session: AsyncSession, principal: Principal, body: YearIn) -> AcademicYear:
    year = await crud.create(session, principal, AcademicYear, body.model_dump() | {"is_current": False}, commit=False)
    if body.is_current:
        await _clear_current(session, year.id)
        year.is_current = True
    await session.commit()
    return year


async def update_year(session: AsyncSession, year_id: uuid.UUID, body: YearUpdate) -> AcademicYear:
    year = await crud.get_live(session, AcademicYear, year_id, lock=True)
    data = body.model_dump(exclude_unset=True)
    start, end = data.get("start_date", year.start_date), data.get("end_date", year.end_date)
    if end <= start:
        raise _invalid("end_date", "invalid_value")
    terms_outside = (
        await session.execute(
            select(Term.id)
            .where(
                Term.academic_year_id == year.id,
                Term.deleted_at.is_(None),
                (Term.start_date < start) | (Term.end_date > end),
            )
            .limit(1)
        )
    ).first()
    if terms_outside:
        raise _invalid("start_date", "outside_year")
    year.start_date, year.end_date = start, end
    if data.get("is_current"):
        await _clear_current(session, year.id)
        year.is_current = True
    elif data.get("is_current") is False:
        year.is_current = False
    await session.commit()
    return year


async def _check_term_dates(session: AsyncSession, year_id: uuid.UUID, start, end) -> None:
    year = await crud.get_live(session, AcademicYear, year_id)
    if end <= start:
        raise _invalid("end_date", "invalid_value")
    if start < year.start_date or end > year.end_date:
        raise _invalid("start_date", "outside_year")


async def create_term(session: AsyncSession, principal: Principal, body: TermIn) -> Term:
    await _check_term_dates(session, body.academic_year_id, body.start_date, body.end_date)
    return await crud.create(session, principal, Term, body.model_dump())  # overlap: EXCLUDE -> 409


async def update_term(session: AsyncSession, term_id: uuid.UUID, body: TermUpdate) -> Term:
    term = await crud.get_live(session, Term, term_id, lock=True)
    data = body.model_dump(exclude_unset=True)
    await _check_term_dates(
        session, term.academic_year_id, data.get("start_date", term.start_date), data.get("end_date", term.end_date)
    )
    return await crud.update(session, Term, term_id, data)


# ---------------------------------------------------------------- classes, streams, class teachers


async def check_next_class(
    session: AsyncSession, level_id: uuid.UUID, next_class_id: uuid.UUID | None, class_id: uuid.UUID | None = None
) -> None:
    if next_class_id is None:
        return
    target = await crud.get_live(session, SchoolClass, next_class_id)
    if target.id == class_id or target.education_level_id != level_id:
        raise _invalid("next_class_id", "invalid_value")  # promotion stays within the level


async def set_class_teacher(
    session: AsyncSession, principal: Principal, stream_id: uuid.UUID, year_id: uuid.UUID, staff_id: uuid.UUID
) -> StreamClassTeacher:
    staff = await crud.get_live(session, Staff, staff_id)
    if staff.status != StaffStatus.ACTIVE:
        raise _invalid("staff_id", "invalid_value")
    row = (
        await session.execute(
            select(StreamClassTeacher)
            .where(StreamClassTeacher.stream_id == stream_id, StreamClassTeacher.academic_year_id == year_id)
            .with_for_update()
        )
    ).scalar_one_or_none()
    if row is None:
        row = StreamClassTeacher(
            school_id=principal.school_id,
            stream_id=stream_id,
            academic_year_id=year_id,
            staff_id=staff_id,
            created_by=principal.user_id,
        )
        session.add(row)
    else:
        row.staff_id = staff_id
    await session.commit()
    return row


async def stream_occupancy(session: AsyncSession, stream_ids: list[uuid.UUID]) -> dict[uuid.UUID, int]:
    if not stream_ids:
        return {}
    rows = await session.execute(
        select(Enrolment.stream_id, func.count())
        .join(AcademicYear, and_(AcademicYear.id == Enrolment.academic_year_id, AcademicYear.is_current))
        .where(Enrolment.stream_id.in_(stream_ids), Enrolment.status == EnrolmentStatus.ACTIVE)
        .group_by(Enrolment.stream_id)
    )
    return dict(rows.all())


# ---------------------------------------------------------------- curriculum


async def class_subjects(session: AsyncSession, class_id: uuid.UUID) -> list:
    return (
        await session.execute(
            select(
                ClassSubject.subject_id,
                ClassSubject.is_compulsory,
                ClassSubject.periods_per_week,
                Subject.code,
                Subject.name_en,
                Subject.name_sw,
            )
            .join(Subject, Subject.id == ClassSubject.subject_id)
            .where(ClassSubject.class_id == class_id, ClassSubject.deleted_at.is_(None))
            .order_by(Subject.code)
        )
    ).all()


async def replace_class_subjects(
    session: AsyncSession, principal: Principal, class_id: uuid.UUID, items: list[ClassSubjectItem]
) -> list:
    await crud.get_live(session, SchoolClass, class_id)
    wanted = {i.subject_id: i for i in items}
    if len(wanted) != len(items):
        raise _invalid("subjects", "duplicate_in_file")
    current = {
        r.subject_id: r
        for r in (
            await session.execute(
                select(ClassSubject)
                .where(ClassSubject.class_id == class_id, ClassSubject.deleted_at.is_(None))
                .with_for_update()
            )
        ).scalars()
    }
    for subject_id, row in current.items():
        if subject_id not in wanted:
            row.deleted_at = now()
        else:
            row.is_compulsory = wanted[subject_id].is_compulsory
            row.periods_per_week = wanted[subject_id].periods_per_week
    await session.flush()  # free the partial unique index before re-adding
    for subject_id, item in wanted.items():
        if subject_id not in current:
            session.add(
                ClassSubject(
                    school_id=principal.school_id, class_id=class_id, created_by=principal.user_id, **item.model_dump()
                )
            )
    await session.commit()
    return await class_subjects(session, class_id)


async def _combination_subjects(session: AsyncSession, combination_id: uuid.UUID) -> list[CombinationSubjectItem]:
    rows = (
        await session.execute(
            select(CombinationSubject.subject_id, CombinationSubject.is_principal).where(
                CombinationSubject.combination_id == combination_id, CombinationSubject.deleted_at.is_(None)
            )
        )
    ).all()
    return [CombinationSubjectItem(subject_id=s, is_principal=p) for s, p in rows]


async def _set_combination_subjects(
    session: AsyncSession, principal: Principal, combination_id: uuid.UUID, items: list[CombinationSubjectItem]
) -> None:
    wanted = {i.subject_id: i.is_principal for i in items}
    if len(wanted) != len(items):
        raise _invalid("subjects", "duplicate_in_file")
    rows = {
        r.subject_id: r
        for r in (
            await session.execute(
                select(CombinationSubject).where(CombinationSubject.combination_id == combination_id).with_for_update()
            )
        ).scalars()
    }
    for subject_id, row in rows.items():
        if subject_id in wanted:
            row.deleted_at, row.is_principal = None, wanted[subject_id]
        elif row.deleted_at is None:
            row.deleted_at = now()
    for subject_id, principal_flag in wanted.items():
        if subject_id not in rows:
            session.add(
                CombinationSubject(
                    school_id=principal.school_id,
                    combination_id=combination_id,
                    subject_id=subject_id,
                    is_principal=principal_flag,
                    created_by=principal.user_id,
                )
            )
    await session.flush()


async def combination_out(session: AsyncSession, combination: Combination) -> dict:
    return {
        "id": combination.id,
        "education_level_id": combination.education_level_id,
        "code": combination.code,
        "name_en": combination.name_en,
        "name_sw": combination.name_sw,
        "subjects": await _combination_subjects(session, combination.id),
    }


async def create_combination(session: AsyncSession, principal: Principal, body: CombinationIn) -> dict:
    combination = await crud.create(
        session, principal, Combination, body.model_dump(exclude={"subjects"}), commit=False
    )
    await _set_combination_subjects(session, principal, combination.id, body.subjects)
    await session.commit()
    return await combination_out(session, combination)


async def update_combination(
    session: AsyncSession, principal: Principal, combination_id: uuid.UUID, body: CombinationUpdate
) -> dict:
    data = body.model_dump(exclude_unset=True, exclude={"subjects"})
    combination = await crud.update(session, Combination, combination_id, data, commit=False)
    if body.subjects is not None:
        await _set_combination_subjects(session, principal, combination_id, body.subjects)
    await session.commit()
    return await combination_out(session, combination)


# ---------------------------------------------------------------- grading schemes


async def scheme_out(session: AsyncSession, scheme: GradingScheme) -> GradingSchemeOut:
    bands = (
        (
            await session.execute(
                select(GradeBand).where(GradeBand.grading_scheme_id == scheme.id).order_by(GradeBand.min_score.desc())
            )
        )
        .scalars()
        .all()
    )
    divisions = (
        (
            await session.execute(
                select(DivisionRule)
                .where(DivisionRule.grading_scheme_id == scheme.id)
                .order_by(DivisionRule.min_points)
            )
        )
        .scalars()
        .all()
    )
    return GradingSchemeOut(
        id=scheme.id,
        education_level_id=scheme.education_level_id,
        academic_year_id=scheme.academic_year_id,
        name=scheme.name,
        version=scheme.version,
        best_n_subjects=scheme.best_n_subjects,
        is_active=scheme.is_active,
        bands=list(bands),
        divisions=list(divisions),
    )


async def save_scheme(session: AsyncSession, principal: Principal, body: GradingSchemeIn) -> GradingSchemeOut:
    """Create version n+1 for the level and year and make it the active one (results already published keep
    the version they were graded with)."""
    await crud.get_live(session, EducationLevel, body.education_level_id)
    await crud.get_live(session, AcademicYear, body.academic_year_id)
    scope = [
        GradingScheme.education_level_id == body.education_level_id,
        GradingScheme.academic_year_id == body.academic_year_id,
    ]
    latest = (await session.execute(select(func.max(GradingScheme.version)).where(*scope))).scalar() or 0
    await session.execute(
        update(GradingScheme).where(*scope, GradingScheme.is_active.is_(True)).values(is_active=False)
    )
    await session.flush()
    scheme = await crud.create(
        session,
        principal,
        GradingScheme,
        {
            "education_level_id": body.education_level_id,
            "academic_year_id": body.academic_year_id,
            "name": body.name,
            "best_n_subjects": body.best_n_subjects,
            "version": latest + 1,
            "is_active": True,
        },
        commit=False,
    )
    common = {"school_id": principal.school_id, "grading_scheme_id": scheme.id, "created_by": principal.user_id}
    session.add_all([GradeBand(**common, **b.model_dump()) for b in body.bands])
    session.add_all([DivisionRule(**common, **d.model_dump()) for d in body.divisions])
    await session.commit()
    return await scheme_out(session, scheme)


async def list_schemes(
    session: AsyncSession, level_id: uuid.UUID | None, year_id: uuid.UUID | None, active_only: bool
) -> list[GradingSchemeOut]:
    where = [GradingScheme.deleted_at.is_(None)]
    if level_id:
        where.append(GradingScheme.education_level_id == level_id)
    if year_id:
        where.append(GradingScheme.academic_year_id == year_id)
    if active_only:
        where.append(GradingScheme.is_active.is_(True))
    schemes = (
        (
            await session.execute(
                select(GradingScheme)
                .where(*where)
                .order_by(GradingScheme.education_level_id, GradingScheme.version.desc())
                .limit(50)
            )
        )
        .scalars()
        .all()
    )
    return [await scheme_out(session, s) for s in schemes]


# ---------------------------------------------------------------- assessment components


async def update_component(
    session: AsyncSession, component_id: uuid.UUID, body: ComponentUpdate
) -> AssessmentComponent:
    component = await crud.get_live(session, AssessmentComponent, component_id, lock=True)
    data = body.model_dump(exclude_unset=True)
    locked = (
        await session.execute(
            select(MarkEntry.id)
            .where(MarkEntry.component_id == component.id, MarkEntry.locked_at.is_not(None))
            .limit(1)
        )
    ).first()
    if locked and ({"max_score", "weight"} & set(data)):
        raise _invalid("component", "results_published", status=409)
    if "max_score" in data:
        highest = (
            await session.execute(
                select(func.max(MarkEntry.score)).where(
                    MarkEntry.component_id == component.id, MarkEntry.deleted_at.is_(None)
                )
            )
        ).scalar()
        if highest is not None and highest > data["max_score"]:
            raise _invalid("max_score", "scores_exceed_max")
    return await crud.update(session, AssessmentComponent, component_id, data)


async def delete_component(session: AsyncSession, component_id: uuid.UUID, reason: str) -> None:
    await crud.soft_delete(
        session,
        AssessmentComponent,
        component_id,
        reason,
        blockers=[select(MarkEntry.id).where(MarkEntry.component_id == component_id, MarkEntry.deleted_at.is_(None))],
    )


async def weight_check(session: AsyncSession, term_id: uuid.UUID) -> list[WeightCheckRow]:
    """Totals per level and subject (NULL subject = the level-wide set). Every set must total 100."""
    await crud.get_live(session, Term, term_id)
    rows = (
        await session.execute(
            select(
                AssessmentComponent.education_level_id,
                AssessmentComponent.subject_id,
                Subject.code,
                func.sum(AssessmentComponent.weight),
                func.count(),
            )
            .outerjoin(Subject, Subject.id == AssessmentComponent.subject_id)
            .where(AssessmentComponent.term_id == term_id, AssessmentComponent.deleted_at.is_(None))
            .group_by(AssessmentComponent.education_level_id, AssessmentComponent.subject_id, Subject.code)
            .order_by(AssessmentComponent.education_level_id, Subject.code.nulls_first())
        )
    ).all()
    return [
        WeightCheckRow(
            education_level_id=lvl, subject_id=sid, subject_code=code, total_weight=total, components=n, ok=total == 100
        )
        for lvl, sid, code, total, n in rows
    ]


async def term_of(session: AsyncSession, term_id: uuid.UUID) -> Term:
    term = (
        await session.execute(select(Term).where(Term.id == term_id, Term.deleted_at.is_(None)))
    ).scalar_one_or_none()
    if term is None:
        raise not_found()
    return term
