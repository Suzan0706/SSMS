"""Results: validation firewall, publication (database function publish_results), published results, report-card
data, comments, amendments (maker-checker via amend_result) and analytics.

Published results and summaries are frozen; a correction is a new version (supersedes_id). "Current" below
always means the newest version of each result.
"""

import uuid
from decimal import Decimal

from sqlalchemy import String, and_, cast, exists, func, select, text
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import aliased

from app.api.deps import Principal
from app.core.errors import AppError, forbidden, not_found
from app.core.pagination import paginate
from app.models import (
    AcademicYear,
    AssessmentComponent,
    Enrolment,
    GradeBand,
    GradingScheme,
    Guardian,
    MarkEntry,
    PublishedResult,
    ReportCardComment,
    ResultAmendment,
    ResultPublication,
    SchoolClass,
    Staff,
    Stream,
    StreamClassTeacher,
    Student,
    StudentGuardian,
    StudentTermSummary,
    Subject,
    TeachingAssignment,
    Term,
    User,
)
from app.models.enums import AmendmentStatus
from app.schemas.results import (
    AmendmentOut,
    AnalyticsOut,
    Attendance,
    ClassResultRow,
    Comments,
    ComponentScore,
    FirewallOut,
    FirewallProblem,
    PublicationOut,
    StudentResultsOut,
    StudentSubjectResult,
    SubjectResult,
    SubjectStats,
    Summary,
)
from app.services import crud
from app.services.people import now

PROBLEM_TEXT = {
    "MISSING_MARK": ("Alama haijaingizwa", "No mark entered"),
    "OUT_OF_RANGE": ("Alama imezidi kiwango cha juu", "Score is above the maximum"),
    "WEIGHTS_NOT_100": ("Jumla ya uzito wa vipengele si 100", "Component weights do not total 100"),
    "NO_GRADING_SCHEME": ("Hakuna mfumo wa madaraja unaotumika", "No active grading scheme"),
    "NO_STUDENTS": ("Darasa halina wanafunzi waliosajiliwa", "The class has no active students"),
    "ALREADY_PUBLISHED": ("Matokeo ya darasa hili yameshatolewa", "Results are already published"),
}
MAX_LISTED = 300


def _superseded(model):
    newer = aliased(model)
    return exists().where(newer.school_id == model.school_id, newer.supersedes_id == model.id)


def current_results():
    return select(PublishedResult).where(~_superseded(PublishedResult))


def current_summaries():
    return select(StudentTermSummary).where(~_superseded(StudentTermSummary))


# ---------------------------------------------------------------- firewall and publication


async def firewall(session: AsyncSession, term_id: uuid.UUID, class_id: uuid.UUID) -> FirewallOut:
    await crud.get_live(session, Term, term_id)
    await crud.get_live(session, SchoolClass, class_id)
    fw = func.results_firewall(term_id, class_id).table_valued(
        "problem_code", "admission_no", "student_name", "subject_code", "component_code", "teacher_name", "detail"
    )
    rows = (
        await session.execute(
            select(fw).order_by(fw.c.problem_code, fw.c.admission_no, fw.c.subject_code, fw.c.component_code)
        )
    ).all()
    problems = [
        FirewallProblem(
            problem=r.problem_code,
            admission_no=r.admission_no,
            student=r.student_name,
            subject=r.subject_code,
            component=r.component_code,
            teacher=r.teacher_name,
            detail=r.detail,
            message_sw=PROBLEM_TEXT.get(r.problem_code, (r.detail,))[0] or "",
            message_en=PROBLEM_TEXT.get(r.problem_code, (None, r.detail))[1] or "",
        )
        for r in rows[:MAX_LISTED]
    ]
    return FirewallOut(ok=not rows, total=len(rows), problems=problems)


async def publication_out(session: AsyncSession, publication: ResultPublication) -> PublicationOut:
    students = (
        await session.execute(
            select(func.count()).select_from(
                current_summaries().where(StudentTermSummary.publication_id == publication.id).subquery()
            )
        )
    ).scalar()
    results = (
        await session.execute(
            select(func.count()).select_from(
                current_results().where(PublishedResult.publication_id == publication.id).subquery()
            )
        )
    ).scalar()
    return PublicationOut(
        id=publication.id,
        term_id=publication.term_id,
        class_id=publication.class_id,
        scheme_version=publication.scheme_version,
        published_at=publication.published_at,
        students=students,
        results=results,
    )


async def publish(session: AsyncSession, term_id: uuid.UUID, class_id: uuid.UUID) -> ResultPublication:
    """Runs the firewall first (friendly 422 with the full list), then publish_results() in this transaction."""
    check = await firewall(session, term_id, class_id)
    if not check.ok:
        raise AppError(422, "INCOMPLETE_GRADES_BLOCK", [p.model_dump() for p in check.problems], count=check.total)
    publication_id = (await session.execute(select(func.publish_results(term_id, class_id)))).scalar_one()
    return (await session.execute(select(ResultPublication).where(ResultPublication.id == publication_id))).scalar_one()


async def publication_for(session: AsyncSession, term_id: uuid.UUID, class_id: uuid.UUID) -> ResultPublication:
    publication = (
        await session.execute(
            select(ResultPublication).where(
                ResultPublication.term_id == term_id, ResultPublication.class_id == class_id
            )
        )
    ).scalar_one_or_none()
    if publication is None:
        raise not_found()
    return publication


# ---------------------------------------------------------------- class results


async def class_results(
    session: AsyncSession, publication: ResultPublication, stream_id: uuid.UUID | None, limit: int, cursor: str | None
) -> tuple[list[ClassResultRow], str | None]:
    summaries = current_summaries().where(StudentTermSummary.publication_id == publication.id).subquery()
    stmt = (
        select(
            summaries.c.enrolment_id,
            summaries.c.average_score,
            summaries.c.total_points,
            summaries.c.division,
            summaries.c.class_position,
            Student.id.label("student_id"),
            Student.admission_no,
            User.first_name,
            User.middle_name,
            User.last_name,
            Stream.name.label("stream_name"),
        )
        .select_from(summaries)
        .join(Enrolment, Enrolment.id == summaries.c.enrolment_id)
        .join(Stream, Stream.id == Enrolment.stream_id)
        .join(Student, Student.id == Enrolment.student_id)
        .join(User, User.id == Student.user_id)
    )
    if stream_id:
        stmt = stmt.where(Enrolment.stream_id == stream_id)
    rows, next_cursor = await paginate(
        session, stmt, [summaries.c.class_position, summaries.c.enrolment_id], limit, cursor
    )
    enrolment_ids = [r.enrolment_id for r in rows]
    results: dict[uuid.UUID, list[SubjectResult]] = {e: [] for e in enrolment_ids}
    for result, code in (
        await session.execute(
            current_results()
            .add_columns(Subject.code)
            .join(Subject, Subject.id == PublishedResult.subject_id)
            .where(PublishedResult.publication_id == publication.id, PublishedResult.enrolment_id.in_(enrolment_ids))
            .order_by(Subject.code)
        )
    ).all():
        results[result.enrolment_id].append(
            SubjectResult(
                published_result_id=result.id,
                subject_id=result.subject_id,
                subject_code=code,
                final_score=result.final_score,
                letter_grade=result.letter_grade,
                points=result.points,
                subject_position=result.subject_position,
                amended=result.amendment_id is not None,
            )
        )
    items = [
        ClassResultRow(
            enrolment_id=r.enrolment_id,
            student_id=r.student_id,
            admission_no=r.admission_no,
            stream_name=r.stream_name,
            full_name=" ".join(p for p in (r.first_name, r.middle_name, r.last_name) if p),
            average_score=r.average_score,
            total_points=r.total_points,
            division=r.division,
            class_position=r.class_position,
            results=results[r.enrolment_id],
        )
        for r in rows
    ]
    return items, next_cursor


# ---------------------------------------------------------------- one student (report card data)


async def may_see_student(session: AsyncSession, principal: Principal, student: Student) -> bool:
    if principal.has("results.read"):
        return True
    if principal.has("portal.student") and student.user_id == principal.user_id:
        return True
    if principal.has("portal.parent"):
        return bool(
            (
                await session.execute(
                    select(StudentGuardian.id)
                    .join(Guardian, Guardian.id == StudentGuardian.guardian_id)
                    .where(
                        StudentGuardian.student_id == student.id,
                        StudentGuardian.deleted_at.is_(None),
                        Guardian.user_id == principal.user_id,
                    )
                )
            ).first()
        )
    return False


async def _attendance(session: AsyncSession, student_id: uuid.UUID, stream_id: uuid.UUID, term: Term) -> Attendance:
    """Morning registers of the stream during the term (attendance tables arrive with Phase 4 models)."""
    row = (
        await session.execute(
            text(
                "SELECT count(DISTINCT s.id) AS sessions, "
                "       count(r.id) FILTER (WHERE r.status IN ('PRESENT','LATE')) AS present "
                "FROM attendance_sessions s "
                "LEFT JOIN attendance_records r ON r.session_id = s.id AND r.student_id = :student "
                "WHERE s.kind = 'REGISTER' AND s.stream_id = :stream AND s.session_date BETWEEN :start AND :end"
            ).bindparams(student=student_id, stream=stream_id, start=term.start_date, end=term.end_date)
        )
    ).one()
    return Attendance(present=row.present or 0, sessions=row.sessions or 0)


async def student_results(
    session: AsyncSession, principal: Principal, student_id: uuid.UUID, term_id: uuid.UUID
) -> StudentResultsOut:
    student = await crud.get_live(session, Student, student_id)
    if not await may_see_student(session, principal, student):
        raise not_found()
    term = await crud.get_live(session, Term, term_id)
    row = (
        await session.execute(
            select(Enrolment, Stream, SchoolClass, ResultPublication, AcademicYear.name.label("year_name"))
            .join(Stream, Stream.id == Enrolment.stream_id)
            .join(SchoolClass, SchoolClass.id == Stream.class_id)
            .join(
                ResultPublication,
                and_(ResultPublication.class_id == SchoolClass.id, ResultPublication.term_id == term.id),
            )
            .join(AcademicYear, AcademicYear.id == Enrolment.academic_year_id)
            .where(Enrolment.student_id == student.id, Enrolment.academic_year_id == term.academic_year_id)
            .order_by(Enrolment.started_on.desc())
            .limit(1)
        )
    ).first()
    if row is None:
        raise not_found()
    enrolment, stream, school_class, publication, year_name = row
    return await _student_results(session, student, enrolment, stream, school_class, publication, term, year_name)


async def _student_results(session, student, enrolment, stream, school_class, publication, term, year_name):
    user = (await session.execute(select(User).where(User.id == student.user_id))).scalar_one()
    scheme = (
        await session.execute(select(GradingScheme).where(GradingScheme.id == publication.grading_scheme_id))
    ).scalar_one()
    summary = (
        await session.execute(
            current_summaries().where(
                StudentTermSummary.publication_id == publication.id, StudentTermSummary.enrolment_id == enrolment.id
            )
        )
    ).scalar_one_or_none()
    if summary is None:
        raise not_found()
    class_size = (
        await session.execute(
            select(func.count()).select_from(
                current_summaries().where(StudentTermSummary.publication_id == publication.id).subquery()
            )
        )
    ).scalar()
    bands = {
        b.letter: b
        for b in (await session.execute(select(GradeBand).where(GradeBand.grading_scheme_id == scheme.id))).scalars()
    }
    current = current_results().where(PublishedResult.publication_id == publication.id).subquery()
    cohort = dict(
        (await session.execute(select(current.c.subject_id, func.count()).group_by(current.c.subject_id))).all()
    )
    rows = (
        await session.execute(
            current_results()
            .add_columns(Subject.code, Subject.name_en, Subject.name_sw)
            .join(Subject, Subject.id == PublishedResult.subject_id)
            .where(PublishedResult.publication_id == publication.id, PublishedResult.enrolment_id == enrolment.id)
            .order_by(Subject.code)
        )
    ).all()
    marks = (
        await session.execute(
            select(
                MarkEntry.subject_id,
                AssessmentComponent.code,
                AssessmentComponent.max_score,
                AssessmentComponent.weight,
                MarkEntry.score,
                MarkEntry.is_absent,
            )
            .join(AssessmentComponent, AssessmentComponent.id == MarkEntry.component_id)
            .where(
                MarkEntry.enrolment_id == enrolment.id,
                AssessmentComponent.term_id == term.id,
                MarkEntry.deleted_at.is_(None),
            )
            .order_by(AssessmentComponent.code)
        )
    ).all()
    by_subject: dict[uuid.UUID, list[ComponentScore]] = {}
    for subject_id, code, max_score, weight, score, absent in marks:
        by_subject.setdefault(subject_id, []).append(
            ComponentScore(code=code, max_score=max_score, weight=weight, score=score, is_absent=absent)
        )
    subjects = [
        StudentSubjectResult(
            published_result_id=r.id,
            subject_id=r.subject_id,
            subject_code=code,
            subject_name_en=name_en,
            subject_name_sw=name_sw,
            final_score=r.final_score,
            letter_grade=r.letter_grade,
            points=r.points,
            subject_position=r.subject_position,
            out_of=cohort.get(r.subject_id, 0),
            amended=r.amendment_id is not None,
            remark_en=bands[r.letter_grade].remark_en if r.letter_grade in bands else None,
            remark_sw=bands[r.letter_grade].remark_sw if r.letter_grade in bands else None,
            components=by_subject.get(r.subject_id, []),
        )
        for r, code, name_en, name_sw in rows
    ]
    comment = (
        await session.execute(
            select(ReportCardComment).where(
                ReportCardComment.publication_id == publication.id, ReportCardComment.enrolment_id == enrolment.id
            )
        )
    ).scalar_one_or_none()
    amended_at = (
        await session.execute(
            select(func.max(ResultAmendment.decided_at))
            .join(PublishedResult, PublishedResult.amendment_id == ResultAmendment.id)
            .where(PublishedResult.publication_id == publication.id, PublishedResult.enrolment_id == enrolment.id)
        )
    ).scalar()
    return StudentResultsOut(
        publication_id=publication.id,
        enrolment_id=enrolment.id,
        student_id=student.id,
        admission_no=student.admission_no,
        full_name=user.full_name,
        class_code=school_class.code,
        class_name_en=school_class.name_en,
        class_name_sw=school_class.name_sw,
        stream_name=stream.name,
        term_name_en=term.name_en,
        term_name_sw=term.name_sw,
        academic_year=year_name,
        scheme_name=scheme.name,
        scheme_version=publication.scheme_version,
        published_at=publication.published_at,
        summary=Summary(
            total_score=summary.total_score,
            average_score=summary.average_score,
            subjects_sat=summary.subjects_sat,
            total_points=summary.total_points,
            division=summary.division,
            class_position=summary.class_position,
            class_size=class_size,
            best_n_subjects=scheme.best_n_subjects,
        ),
        subjects=subjects,
        comments=Comments(
            class_teacher_comment=comment.class_teacher_comment if comment else None,
            head_teacher_comment=comment.head_teacher_comment if comment else None,
        ),
        attendance=await _attendance(session, student.id, stream.id, term),
        amended_at=amended_at,
    )


async def results_for_enrolment(
    session: AsyncSession, publication: ResultPublication, enrolment_id: uuid.UUID
) -> StudentResultsOut:
    """Report-card data for one enrolment of a publication (used by the PDF job)."""
    enrolment = (await session.execute(select(Enrolment).where(Enrolment.id == enrolment_id))).scalar_one()
    stream = (await session.execute(select(Stream).where(Stream.id == enrolment.stream_id))).scalar_one()
    school_class = (await session.execute(select(SchoolClass).where(SchoolClass.id == stream.class_id))).scalar_one()
    student = (await session.execute(select(Student).where(Student.id == enrolment.student_id))).scalar_one()
    term = (await session.execute(select(Term).where(Term.id == publication.term_id))).scalar_one()
    year = (
        await session.execute(select(AcademicYear.name).where(AcademicYear.id == enrolment.academic_year_id))
    ).scalar()
    return await _student_results(session, student, enrolment, stream, school_class, publication, term, year)


# ---------------------------------------------------------------- comments


async def save_comments(
    session: AsyncSession, principal: Principal, publication_id: uuid.UUID, enrolment_id: uuid.UUID, data: dict
) -> ReportCardComment:
    publication = (
        await session.execute(select(ResultPublication).where(ResultPublication.id == publication_id))
    ).scalar_one_or_none()
    enrolment = (await session.execute(select(Enrolment).where(Enrolment.id == enrolment_id))).scalar_one_or_none()
    if publication is None or enrolment is None:
        raise not_found()
    if "head_teacher_comment" in data and not principal.has("results.publish"):
        raise forbidden()
    if "class_teacher_comment" in data and not principal.has("results.publish"):
        is_class_teacher = (
            await session.execute(
                select(StreamClassTeacher.id)
                .join(Staff, Staff.id == StreamClassTeacher.staff_id)
                .where(
                    StreamClassTeacher.stream_id == enrolment.stream_id,
                    StreamClassTeacher.academic_year_id == enrolment.academic_year_id,
                    Staff.user_id == principal.user_id,
                )
            )
        ).first()
        if not is_class_teacher:
            raise forbidden()
    comment = (
        await session.execute(
            select(ReportCardComment)
            .where(ReportCardComment.publication_id == publication_id, ReportCardComment.enrolment_id == enrolment_id)
            .with_for_update()
        )
    ).scalar_one_or_none()
    if comment is None:
        comment = ReportCardComment(
            school_id=principal.school_id,
            publication_id=publication_id,
            enrolment_id=enrolment_id,
            created_by=principal.user_id,
        )
        session.add(comment)
    for field, value in data.items():
        setattr(comment, field, value)
    await session.commit()
    return comment


# ---------------------------------------------------------------- amendments


async def _teaches(session: AsyncSession, principal: Principal, result: PublishedResult) -> bool:
    enrolment = (await session.execute(select(Enrolment).where(Enrolment.id == result.enrolment_id))).scalar_one()
    return bool(
        (
            await session.execute(
                select(TeachingAssignment.id)
                .join(Staff, Staff.id == TeachingAssignment.staff_id)
                .where(
                    TeachingAssignment.academic_year_id == enrolment.academic_year_id,
                    TeachingAssignment.stream_id == enrolment.stream_id,
                    TeachingAssignment.subject_id == result.subject_id,
                    TeachingAssignment.deleted_at.is_(None),
                    Staff.user_id == principal.user_id,
                )
            )
        ).first()
    )


async def request_amendment(
    session: AsyncSession, principal: Principal, result_id: uuid.UUID, new_score: Decimal, reason: str
) -> ResultAmendment:
    result = (
        await session.execute(select(PublishedResult).where(PublishedResult.id == result_id))
    ).scalar_one_or_none()
    if result is None:
        raise not_found()
    if not (principal.has("results.publish") or await _teaches(session, principal, result)):
        raise forbidden()
    newer = (
        await session.execute(select(PublishedResult.id).where(PublishedResult.supersedes_id == result.id))
    ).first()
    if newer:
        raise AppError(409, "NOT_ALLOWED", [{"field": "published_result_id", "code": "superseded"}])
    pending = (
        await session.execute(
            select(ResultAmendment.id).where(
                ResultAmendment.published_result_id == result.id, ResultAmendment.status == AmendmentStatus.PENDING
            )
        )
    ).first()
    if pending:
        raise AppError(409, "DUPLICATE", [{"field": "published_result_id", "code": "pending_amendment"}])
    amendment = ResultAmendment(
        school_id=principal.school_id,
        published_result_id=result.id,
        new_score=new_score,
        reason=reason,
        requested_by=principal.user_id,
        status=AmendmentStatus.PENDING,
        created_by=principal.user_id,
    )
    session.add(amendment)
    await session.commit()
    return amendment


async def _pending(session: AsyncSession, principal: Principal, amendment_id: uuid.UUID) -> ResultAmendment:
    amendment = (
        await session.execute(select(ResultAmendment).where(ResultAmendment.id == amendment_id).with_for_update())
    ).scalar_one_or_none()
    if amendment is None:
        raise not_found()
    if amendment.requested_by == principal.user_id:
        raise AppError(403, "FORBIDDEN", [{"field": "approver", "code": "maker_checker"}])
    if amendment.status != AmendmentStatus.PENDING:
        raise AppError(409, "NOT_ALLOWED", [{"field": "status", "code": "invalid_value"}])
    return amendment


async def approve_amendment(
    session: AsyncSession, principal: Principal, amendment_id: uuid.UUID, note: str | None
) -> tuple[ResultAmendment, uuid.UUID, uuid.UUID]:
    """Freeze a new result version. Returns (amendment, publication id, enrolment id) for the report-card job."""
    amendment = await _pending(session, principal, amendment_id)
    await session.execute(select(func.amend_result(amendment.id, note)))
    result = (
        await session.execute(select(PublishedResult).where(PublishedResult.id == amendment.published_result_id))
    ).scalar_one()
    await session.commit()
    await session.refresh(amendment)
    return amendment, result.publication_id, result.enrolment_id


async def reject_amendment(
    session: AsyncSession, principal: Principal, amendment_id: uuid.UUID, note: str
) -> ResultAmendment:
    amendment = await _pending(session, principal, amendment_id)
    amendment.status, amendment.decided_by, amendment.decided_at = AmendmentStatus.REJECTED, principal.user_id, now()
    amendment.decision_note = note
    await session.commit()
    return amendment


async def list_amendments(session: AsyncSession, principal: Principal, status: str | None) -> list[AmendmentOut]:
    requester = aliased(User)
    learner = aliased(User)
    stmt = (
        select(
            ResultAmendment,
            PublishedResult.final_score,
            Subject.code,
            Student.admission_no,
            learner.first_name,
            learner.last_name,
            requester.first_name.label("r_first"),
            requester.last_name.label("r_last"),
        )
        .join(PublishedResult, PublishedResult.id == ResultAmendment.published_result_id)
        .join(Subject, Subject.id == PublishedResult.subject_id)
        .join(Enrolment, Enrolment.id == PublishedResult.enrolment_id)
        .join(Student, Student.id == Enrolment.student_id)
        .join(learner, learner.id == Student.user_id)
        .join(requester, requester.id == ResultAmendment.requested_by)
    )
    if status:
        stmt = stmt.where(ResultAmendment.status == status)
    if not principal.has("results.amend_approve"):
        stmt = stmt.where(ResultAmendment.requested_by == principal.user_id)
    rows = (await session.execute(stmt.order_by(ResultAmendment.created_at.desc()).limit(200))).all()
    return [
        AmendmentOut(
            id=a.id,
            published_result_id=a.published_result_id,
            status=a.status,
            admission_no=adm,
            student=f"{first} {last}",
            subject_code=code,
            old_score=old,
            new_score=a.new_score,
            reason=a.reason,
            requested_by=a.requested_by,
            requested_by_name=f"{rf} {rl}",
            decided_by=a.decided_by,
            decided_at=a.decided_at,
            decision_note=a.decision_note,
            created_at=a.created_at,
        )
        for a, old, code, adm, first, last, rf, rl in rows
    ]


# ---------------------------------------------------------------- analytics


async def analytics(session: AsyncSession, publication: ResultPublication) -> AnalyticsOut:
    results = current_results().where(PublishedResult.publication_id == publication.id).subquery()
    summaries = current_summaries().where(StudentTermSummary.publication_id == publication.id).subquery()
    students, average = (
        await session.execute(
            select(func.count(), func.coalesce(func.avg(summaries.c.average_score), 0)).select_from(summaries)
        )
    ).one()
    divisions = dict(
        (
            await session.execute(
                select(func.coalesce(summaries.c.division, cast("—", String)), func.count()).group_by(
                    summaries.c.division
                )
            )
        ).all()
    )
    stats = (
        await session.execute(
            select(
                results.c.subject_id,
                Subject.code,
                func.count(),
                func.avg(results.c.final_score),
                func.max(results.c.final_score),
                func.min(results.c.final_score),
            )
            .join(Subject, Subject.id == results.c.subject_id)
            .group_by(results.c.subject_id, Subject.code)
            .order_by(Subject.code)
        )
    ).all()
    grades: dict[uuid.UUID, dict[str, int]] = {}
    for subject_id, letter, n in (
        await session.execute(
            select(results.c.subject_id, results.c.letter_grade, func.count()).group_by(
                results.c.subject_id, results.c.letter_grade
            )
        )
    ).all():
        grades.setdefault(subject_id, {})[letter] = n
    term = (await session.execute(select(Term).where(Term.id == publication.term_id))).scalar_one()
    teachers = {}
    for subject_id, first, last in (
        await session.execute(
            select(TeachingAssignment.subject_id, User.first_name, User.last_name)
            .join(Stream, Stream.id == TeachingAssignment.stream_id)
            .join(Staff, Staff.id == TeachingAssignment.staff_id)
            .join(User, User.id == Staff.user_id)
            .where(
                Stream.class_id == publication.class_id,
                TeachingAssignment.academic_year_id == term.academic_year_id,
                TeachingAssignment.deleted_at.is_(None),
            )
        )
    ).all():
        names = teachers.setdefault(subject_id, set())
        names.add(f"{first} {last}")
    top = (
        await session.execute(
            select(
                summaries.c.class_position,
                summaries.c.average_score,
                summaries.c.division,
                Student.admission_no,
                User.first_name,
                User.last_name,
            )
            .join(Enrolment, Enrolment.id == summaries.c.enrolment_id)
            .join(Student, Student.id == Enrolment.student_id)
            .join(User, User.id == Student.user_id)
            .order_by(summaries.c.class_position)
            .limit(5)
        )
    ).all()
    return AnalyticsOut(
        publication_id=publication.id,
        students=students,
        class_average=round(Decimal(average), 2),
        divisions={str(k): v for k, v in divisions.items()},
        subjects=[
            SubjectStats(
                subject_id=sid,
                subject_code=code,
                students=n,
                average=round(Decimal(avg), 2),
                highest=hi,
                lowest=lo,
                grades=grades.get(sid, {}),
                teacher=", ".join(sorted(teachers.get(sid, []))) or None,
            )
            for sid, code, n, avg, hi, lo in stats
        ],
        top_students=[
            {"position": p, "average": str(a), "division": d, "admission_no": adm, "name": f"{f} {l_}"}
            for p, a, d, adm, f, l_ in top
        ],
    )


async def progress(session: AsyncSession, principal: Principal, student_id: uuid.UUID) -> list[dict]:
    """The student's published term summaries, oldest first: average, points, division and class position (FR-Q/R
    "academic progress"). Same audience as the results: staff with results.read, the student, a linked guardian."""
    student = await session.get(Student, student_id)
    if student is None or student.deleted_at is not None or not await may_see_student(session, principal, student):
        raise not_found()
    summary = current_summaries().subquery()
    out_of = (
        select(StudentTermSummary.publication_id, func.count().label("n"))
        .where(~_superseded(StudentTermSummary))
        .group_by(StudentTermSummary.publication_id)
        .subquery()
    )
    rows = (
        await session.execute(
            select(Term, AcademicYear.name, summary, out_of.c.n)
            .select_from(summary)
            .join(Enrolment, Enrolment.id == summary.c.enrolment_id)
            .join(ResultPublication, ResultPublication.id == summary.c.publication_id)
            .join(Term, Term.id == ResultPublication.term_id)
            .join(AcademicYear, AcademicYear.id == Term.academic_year_id)
            .join(out_of, out_of.c.publication_id == summary.c.publication_id)
            .where(Enrolment.student_id == student.id)
            .order_by(Term.start_date)
        )
    ).all()
    return [
        {
            "term_id": row.Term.id,
            "term": f"{row.Term.name_en if principal.language == 'en' else row.Term.name_sw} {row.name}",
            "average": row.average_score,
            "total_points": row.total_points,
            "division": row.division,
            "position": row.class_position,
            "out_of": row.n,
        }
        for row in rows
    ]
