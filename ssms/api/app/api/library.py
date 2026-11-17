"""/library/categories, /library/publishers and /library/cards (FR-96)."""

import uuid
from datetime import date
from typing import Annotated

from fastapi import APIRouter, Depends, Response, status
from pydantic import BaseModel, Field, model_validator
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import Principal, require_permission
from app.db.session import get_session
from app.models import LibraryCategory, LibraryPublisher
from app.services import library as service

router = APIRouter(prefix="/library", tags=["library"])
Session = Annotated[AsyncSession, Depends(get_session)]
Librarian = Annotated[Principal, require_permission("library.manage")]
Printer = Annotated[Principal, require_permission("library.manage", "cards.print")]


class NameIn(BaseModel):
    name: str = Field(min_length=2, max_length=80)


class Named(BaseModel):
    id: uuid.UUID
    name: str


class CardsIn(BaseModel):
    stream_id: uuid.UUID | None = Field(default=None, description="Every student of the stream without a card")
    user_ids: list[uuid.UUID] = Field(default_factory=list, max_length=500)

    @model_validator(mode="after")
    def _someone(self):
        if self.stream_id is None and not self.user_ids:
            raise ValueError("give a stream or people")
        return self


class CardOut(BaseModel):
    id: uuid.UUID
    user_id: uuid.UUID
    card_no: str
    issued_on: date
    full_name: str
    admission_no: str | None
    class_stream: str | None


@router.get("/categories", response_model=list[Named])
async def categories(_: Librarian, session: Session):
    return await service.named(session, LibraryCategory)


@router.post("/categories", response_model=Named, status_code=status.HTTP_201_CREATED)
async def add_category(body: NameIn, principal: Librarian, session: Session):
    return {"id": await service.add_named(session, principal, LibraryCategory, body.name), "name": body.name.strip()}


@router.get("/publishers", response_model=list[Named])
async def publishers(_: Librarian, session: Session):
    return await service.named(session, LibraryPublisher)


@router.post("/publishers", response_model=Named, status_code=status.HTTP_201_CREATED)
async def add_publisher(body: NameIn, principal: Librarian, session: Session):
    return {"id": await service.add_named(session, principal, LibraryPublisher, body.name), "name": body.name.strip()}


@router.get("/cards", response_model=list[CardOut], summary="Live library cards (of a stream)")
async def cards(_: Printer, session: Session, stream_id: uuid.UUID | None = None):
    return await service.cards(session, stream_id)


@router.post("/cards", summary="Issue cards to people (or a stream) who have none")
async def issue(body: CardsIn, principal: Printer, session: Session) -> dict:
    return {"issued": await service.issue_cards(session, principal, body.stream_id, body.user_ids)}


@router.post("/cards/{card_id}/revoke", status_code=status.HTTP_204_NO_CONTENT, summary="A lost or withdrawn card")
async def revoke(card_id: uuid.UUID, _: Printer, session: Session):
    await service.revoke_card(session, card_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get("/cards.pdf", response_class=Response, responses={200: {"content": {"application/pdf": {}}}})
async def cards_pdf(_: Printer, session: Session, stream_id: uuid.UUID | None = None):
    return Response(
        await service.cards_pdf(session, stream_id),
        media_type="application/pdf",
        headers={"Content-Disposition": 'attachment; filename="library-cards.pdf"'},
    )
