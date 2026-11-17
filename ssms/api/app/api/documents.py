"""Certificates, ID cards, staff photographs and the email channel (FR-78, FR-94, FR-95, FR-98)."""

import uuid
from datetime import date
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, Query, Response, status
from pydantic import BaseModel, ConfigDict, Field, model_validator
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import Principal, active_principal, require_permission
from app.core.config import get_settings
from app.core.errors import AppError, forbidden, not_found
from app.core.storage import get_storage
from app.db.session import get_session
from app.models import Staff, StoredFile
from app.models.enums import FilePurpose
from app.services import crud, documents, files
from app.services import email as mail
from app.tasks.dispatch import get_dispatcher

router = APIRouter(tags=["documents"])
Session = Annotated[AsyncSession, Depends(get_session)]
Signed = Annotated[Principal, Depends(active_principal)]
Issuer = Annotated[Principal, require_permission("certificates.issue")]
Printer = Annotated[Principal, require_permission("cards.print")]
Mailer = Annotated[Principal, require_permission("email.manage")]
Lang = Literal["sw", "en"] | None
PDF = {200: {"content": {"application/pdf": {}}}}


def _pdf(data: bytes, name: str) -> Response:
    return Response(
        data, media_type="application/pdf", headers={"Content-Disposition": f'attachment; filename="{name}"'}
    )


# ---------------------------------------------------------------- certificates


class TemplateIn(BaseModel):
    kind: Literal["LEAVING", "TRANSFER", "CHARACTER", "ACHIEVEMENT"]
    name: str = Field(min_length=2, max_length=80)
    language: Literal["sw", "en"] = "sw"
    body: str = Field(
        min_length=10,
        max_length=4000,
        description="Text with {{name}}, {{admission_no}}, {{class}}, "
        "{{date_of_birth}}, {{school}}, {{issued_on}}, {{year}}",
    )
    background_file_id: uuid.UUID | None = Field(default=None, description="A CERT_TEMPLATE upload")


class TemplateOut(TemplateIn):
    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID


class IssueIn(BaseModel):
    template_id: uuid.UUID
    student_ids: list[uuid.UUID] = Field(min_length=1, max_length=300)
    issued_on: date


class RevokeIn(BaseModel):
    reason: str = Field(min_length=5, max_length=300)


@router.get("/certificate-templates", response_model=list[TemplateOut])
async def list_templates(_: Issuer, session: Session):
    return await documents.templates(session)


@router.post("/certificate-templates", response_model=TemplateOut, status_code=status.HTTP_201_CREATED)
async def create_template(body: TemplateIn, principal: Issuer, session: Session):
    return await documents.save_template(session, principal, body)


@router.put(
    "/certificate-templates/{template_id}", response_model=TemplateOut, summary="Issued certificates keep their text"
)
async def update_template(template_id: uuid.UUID, body: TemplateIn, principal: Issuer, session: Session):
    return await documents.save_template(session, principal, body, template_id)


@router.post("/certificates", status_code=status.HTTP_201_CREATED, summary="Issue one certificate per student")
async def issue_certificates(body: IssueIn, principal: Issuer, session: Session) -> dict:
    issued = await documents.issue(session, principal, body.template_id, body.student_ids, body.issued_on)
    return {"issued": [{"id": c.id, "serial_no": c.serial_no} for c in issued]}


@router.get("/certificates", summary="Issued certificates, newest first")
async def list_certificates(_: Issuer, session: Session, student_id: uuid.UUID | None = None) -> list[dict]:
    return await documents.certificates(session, student_id)


@router.post("/certificates/{certificate_id}/revoke", status_code=status.HTTP_204_NO_CONTENT)
async def revoke_certificate(certificate_id: uuid.UUID, body: RevokeIn, _: Issuer, session: Session):
    await documents.revoke_certificate(session, certificate_id, body.reason)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get("/certificates/{certificate_id}.pdf", response_class=Response, responses=PDF)
async def certificate_pdf(certificate_id: uuid.UUID, principal: Issuer, session: Session, lang: Lang = None):
    return _pdf(await documents.certificate_pdf(session, certificate_id, lang or principal.language), "certificate.pdf")


# ---------------------------------------------------------------- ID cards


class IdCardsIn(BaseModel):
    stream_id: uuid.UUID | None = None
    staff: bool = Field(default=False, description="Every active staff member instead of a stream")

    @model_validator(mode="after")
    def _one(self):
        if (self.stream_id is None) == (not self.staff):
            raise ValueError("give a stream or staff=true")
        return self


@router.get("/identity-cards", summary="Live ID cards of a stream, or of the staff")
async def list_id_cards(
    principal: Printer, session: Session, stream_id: uuid.UUID | None = None, staff: bool = False
) -> list[dict]:
    rows = await documents.id_cards(session, principal.language, stream_id=stream_id, staff=staff)
    return [{k: v for k, v in r.items() if k != "photo_key"} | {"has_photo": bool(r["photo_key"])} for r in rows]


@router.post("/identity-cards", summary="Issue cards to those of a stream (or the staff) who have none")
async def issue_id_cards(body: IdCardsIn, principal: Printer, session: Session) -> dict:
    return {"issued": await documents.issue_id_cards(session, principal, stream_id=body.stream_id, staff=body.staff)}


@router.post("/identity-cards/{card_id}/revoke", status_code=status.HTTP_204_NO_CONTENT)
async def revoke_id_card(card_id: uuid.UUID, _: Printer, session: Session):
    await documents.revoke_id_card(session, card_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get("/identity-cards.pdf", response_class=Response, responses=PDF, summary="Eight cards per A4 page")
async def id_cards_pdf(
    principal: Printer, session: Session, stream_id: uuid.UUID | None = None, staff: bool = False, lang: Lang = None
):
    lang = lang or principal.language
    rows = await documents.id_cards(session, lang, stream_id=stream_id, staff=staff)
    return _pdf(await documents.id_cards_pdf(session, rows, lang), "id-cards.pdf")


@router.get(
    "/portal/id-card.pdf", response_class=Response, responses=PDF, tags=["portal"], summary="A student's own card"
)
async def own_id_card(principal: Signed, session: Session, lang: Lang = None):
    if not principal.has("portal.student"):
        raise forbidden()
    lang = lang or principal.language
    rows = await documents.id_cards(session, lang, user_id=principal.user_id)
    if not rows:
        raise not_found()
    return _pdf(await documents.id_cards_pdf(session, rows, lang), "id-card.pdf")


# ---------------------------------------------------------------- staff photographs


class PhotoIn(BaseModel):
    file_id: uuid.UUID = Field(description="A PHOTO uploaded with POST /files")


@router.put("/staff/{staff_id}/photo", status_code=status.HTTP_204_NO_CONTENT, tags=["staff"])
async def set_staff_photo(
    staff_id: uuid.UUID,
    body: PhotoIn,
    principal: Annotated[Principal, require_permission("staff.manage")],
    session: Session,
):
    upload = await files.get(session, body.file_id)
    if upload.purpose != FilePurpose.PHOTO or not files.may_read(upload, principal):
        raise AppError(422, "VALIDATION_ERROR", [{"field": "file_id", "code": "invalid_value"}])
    member = await crud.get_live(session, Staff, staff_id, lock=True)
    member.photo_file_key = upload.storage_key
    await session.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get(
    "/staff/{staff_id}/photo",
    response_class=Response,
    tags=["staff"],
    responses={200: {"content": {"image/jpeg": {}, "image/png": {}}}},
)
async def get_staff_photo(
    staff_id: uuid.UUID,
    _: Annotated[Principal, require_permission("staff.read", "staff.manage")],
    session: Session,
):
    member = await crud.get_live(session, Staff, staff_id)
    upload = (
        (
            await session.execute(
                select(StoredFile).where(
                    StoredFile.storage_key == member.photo_file_key, StoredFile.deleted_at.is_(None)
                )
            )
        ).scalar_one_or_none()
        if member.photo_file_key
        else None
    )
    if upload is None:
        raise not_found()
    return Response(
        get_storage().get(upload.storage_key),
        media_type=upload.content_type,
        headers={"Cache-Control": "private, max-age=300"},
    )


# ---------------------------------------------------------------- email


@router.get("/email-messages", summary="Email sent by the school, newest first", tags=["communication"])
async def email_history(_: Mailer, session: Session, limit: Annotated[int, Query(ge=1, le=200)] = 100) -> list[dict]:
    return await mail.history(session, limit)


@router.post("/email-messages/test", summary="Send a test email to yourself", tags=["communication"])
async def email_test(principal: Mailer, session: Session) -> dict:
    message = await mail.queue_email(
        session,
        school_id=principal.school_id,
        user_id=principal.user_id,
        subject="SSMS: barua pepe ya majaribio / test email",
        body="Barua pepe zinafanya kazi. / Email is working.",
        idempotency_key=f"test:{principal.user_id}:{uuid.uuid4().hex[:12]}",
        template_key="test",
    )
    if message is None:
        code = "no_address" if get_settings().email_enabled else "email_off"
        raise AppError(422, "VALIDATION_ERROR", [{"field": "email", "code": code}])
    await session.commit()
    get_dispatcher().send("email.send", email_id=str(message.id), school_id=str(principal.school_id))
    return {"id": message.id}
