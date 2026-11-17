"""Results: firewall, publication, class and student results, report cards, comments, amendments, analytics."""

import hashlib
import uuid
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, Header, Query, Response
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import Principal, active_principal, require_permission
from app.core.errors import not_found
from app.core.pagination import Cursor, Limit
from app.core.storage import get_storage
from app.db.session import get_session
from app.models import ResultPublication
from app.schemas.results import (
    AmendmentIn,
    AmendmentOut,
    AnalyticsOut,
    ClassResultsOut,
    CommentsIn,
    DecisionIn,
    FirewallOut,
    PublicationOut,
    PublishIn,
    RejectIn,
    StudentResultsOut,
)
from app.services import idempotency, report_cards
from app.services import results as service
from app.tasks.dispatch import get_dispatcher

router = APIRouter(tags=["results"])
Session = Annotated[AsyncSession, Depends(get_session)]
Publisher = Annotated[Principal, require_permission("results.publish")]
Reader = Annotated[Principal, require_permission("results.read")]
PDF = "application/pdf"


class PublishOut(PublicationOut):
    report_card_job_id: uuid.UUID | None = None


@router.get(
    "/results/firewall",
    response_model=FirewallOut,
    summary="Every problem that blocks publishing (same list as the 422 details), sw/en",
)
async def firewall(term_id: uuid.UUID, class_id: uuid.UUID, _: Publisher, session: Session):
    return await service.firewall(session, term_id, class_id)


@router.post(
    "/results/publish",
    response_model=PublishOut,
    status_code=201,
    responses={422: {"description": "INCOMPLETE_GRADES_BLOCK with the full problem list"}},
    summary="Freeze the term's results of a class in one transaction; queue report cards and SMS",
)
async def publish(
    body: PublishIn,
    principal: Publisher,
    session: Session,
    idempotency_key: Annotated[str | None, Header(alias="Idempotency-Key")] = None,
):
    key = idempotency.require_key(idempotency_key)
    digest = hashlib.sha256(body.model_dump_json().encode()).hexdigest()
    previous = await idempotency.replay(session, "POST /results/publish", key, digest)
    if previous:
        publication = (
            await session.execute(
                select(ResultPublication).where(ResultPublication.id == uuid.UUID(previous["publication_id"]))
            )
        ).scalar_one()
        return PublishOut(
            **(await service.publication_out(session, publication)).model_dump(),
            report_card_job_id=previous.get("job_id"),
        )
    publication = await service.publish(session, body.term_id, body.class_id)
    job = report_cards.queue(session, principal, publication.id, notify=True)
    idempotency.remember(
        session,
        principal,
        "POST /results/publish",
        key,
        digest,
        201,
        {"publication_id": str(publication.id), "job_id": str(job.id)},
    )
    out = await service.publication_out(session, publication)
    await session.commit()
    get_dispatcher().send("report_cards.run", job_id=str(job.id), school_id=str(principal.school_id))
    return PublishOut(**out.model_dump(), report_card_job_id=job.id)


@router.get(
    "/results",
    response_model=ClassResultsOut,
    summary="Current results of a published class, best position first (cursor pages of students)",
)
async def class_results(
    term_id: uuid.UUID,
    class_id: uuid.UUID,
    _: Reader,
    session: Session,
    stream_id: uuid.UUID | None = None,
    limit: Limit = 50,
    cursor: Cursor = None,
):
    publication = await service.publication_for(session, term_id, class_id)
    items, next_cursor = await service.class_results(session, publication, stream_id, limit, cursor)
    return ClassResultsOut(
        publication=await service.publication_out(session, publication), items=items, next_cursor=next_cursor
    )


@router.get(
    "/results/report-cards",
    response_class=Response,
    responses={200: {"content": {PDF: {}}}},
    summary="Printable PDF of every report card of the class (made by the report-card job)",
)
async def class_report_cards(term_id: uuid.UUID, class_id: uuid.UUID, principal: Reader, session: Session):
    publication = await service.publication_for(session, term_id, class_id)
    key = f"{principal.school_id}/report-cards/{publication.id}/class.pdf"
    if not get_storage().exists(key):
        raise not_found()
    return Response(
        get_storage().get(key),
        media_type=PDF,
        headers={"Content-Disposition": f'attachment; filename="report-cards-{publication.id}.pdf"'},
    )


@router.get(
    "/students/{student_id}/results",
    response_model=StudentResultsOut,
    summary="One student's published results for a term (staff, the student, or a guardian)",
)
async def student_results(
    student_id: uuid.UUID,
    term_id: uuid.UUID,
    principal: Annotated[Principal, Depends(active_principal)],
    session: Session,
):
    return await service.student_results(session, principal, student_id, term_id)


@router.get(
    "/students/{student_id}/report-card",
    response_class=Response,
    responses={200: {"content": {PDF: {}}}},
    summary="Report card PDF, always built from the current (amended) results",
)
async def report_card(
    student_id: uuid.UUID,
    term_id: uuid.UUID,
    principal: Annotated[Principal, Depends(active_principal)],
    session: Session,
    lang: Annotated[Literal["sw", "en"] | None, Query()] = None,
):
    card, pdf = await report_cards.single(session, principal, student_id, term_id, lang or principal.language)
    return Response(
        pdf, media_type=PDF, headers={"Content-Disposition": f'attachment; filename="report-{card.admission_no}.pdf"'}
    )


@router.put(
    "/publications/{publication_id}/comments/{enrolment_id}",
    response_model=CommentsIn,
    summary="Class teacher comment (class teacher) and head teacher comment (results.publish)",
)
async def put_comments(
    publication_id: uuid.UUID,
    enrolment_id: uuid.UUID,
    body: CommentsIn,
    principal: Annotated[Principal, Depends(active_principal)],
    session: Session,
):
    comment = await service.save_comments(
        session, principal, publication_id, enrolment_id, body.model_dump(exclude_unset=True)
    )
    return CommentsIn(
        class_teacher_comment=comment.class_teacher_comment, head_teacher_comment=comment.head_teacher_comment
    )


@router.post(
    "/published-results/{result_id}/amendments",
    response_model=AmendmentOut,
    status_code=201,
    responses={409: {"description": "superseded / pending amendment exists"}},
)
async def request_amendment(
    result_id: uuid.UUID,
    body: AmendmentIn,
    principal: Annotated[Principal, require_permission("results.amend_request")],
    session: Session,
):
    amendment = await service.request_amendment(session, principal, result_id, body.new_score, body.reason)
    return next(a for a in await service.list_amendments(session, principal, None) if a.id == amendment.id)


@router.get("/amendments", response_model=list[AmendmentOut], summary="Approvers see all; requesters see their own")
async def list_amendments(
    principal: Annotated[Principal, require_permission("results.amend_request", "results.amend_approve")],
    session: Session,
    status: Annotated[Literal["PENDING", "APPROVED", "REJECTED"] | None, Query()] = None,
):
    return await service.list_amendments(session, principal, status)


@router.post(
    "/amendments/{amendment_id}/approve",
    response_model=AmendmentOut,
    responses={403: {"description": "approver is the requester (maker-checker)"}},
)
async def approve(
    amendment_id: uuid.UUID,
    body: DecisionIn,
    principal: Annotated[Principal, require_permission("results.amend_approve")],
    session: Session,
):
    amendment, publication_id, _ = await service.approve_amendment(session, principal, amendment_id, body.note)
    job = report_cards.queue(session, principal, publication_id, notify=False)  # refresh the class bundle
    await session.commit()
    get_dispatcher().send("report_cards.run", job_id=str(job.id), school_id=str(principal.school_id))
    return next(a for a in await service.list_amendments(session, principal, None) if a.id == amendment.id)


@router.post("/amendments/{amendment_id}/reject", response_model=AmendmentOut)
async def reject(
    amendment_id: uuid.UUID,
    body: RejectIn,
    principal: Annotated[Principal, require_permission("results.amend_approve")],
    session: Session,
):
    amendment = await service.reject_amendment(session, principal, amendment_id, body.note)
    return next(a for a in await service.list_amendments(session, principal, None) if a.id == amendment.id)


@router.get(
    "/analytics/results",
    response_model=AnalyticsOut,
    summary="Subject averages and grade distribution, divisions, teachers, top students",
)
async def analytics(term_id: uuid.UUID, class_id: uuid.UUID, _: Reader, session: Session):
    return await service.analytics(session, await service.publication_for(session, term_id, class_id))


@router.get(
    "/students/{student_id}/progress",
    summary="Term-by-term average, division and position (staff, the student, or a guardian)",
)
async def student_progress(
    student_id: uuid.UUID,
    principal: Annotated[Principal, Depends(active_principal)],
    session: Session,
) -> list[dict]:
    return await service.progress(session, principal, student_id)
