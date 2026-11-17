"""/devices (gate readers: API key shown once), /rfid-cards, and /devices/taps (device key, no JWT)."""

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, Header
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import Principal, require_permission
from app.core.errors import AppError
from app.db.session import get_session
from app.models import Device, RfidCard
from app.schemas.attendance import (
    CardIn,
    CardOut,
    CardUpdate,
    DeviceCreated,
    DeviceIn,
    DeviceOut,
    DeviceUpdate,
    TapsIn,
    TapsOut,
)
from app.services import crud
from app.services import devices as service

router = APIRouter(tags=["devices"])
Session = Annotated[AsyncSession, Depends(get_session)]
# The gatekeeper operates devices and cards; the school office (settings.update) may register them too.
Gate = Annotated[Principal, require_permission("attendance.device", "settings.update")]


@router.post(
    "/devices/taps",
    response_model=TapsOut,
    responses={401: {"description": "unknown or disabled device key"}},
    summary="Gate taps from an RFID reader or QR scanner (X-Device-Key); first tap of the day counts",
)
async def taps(body: TapsIn, device_key: Annotated[str | None, Header(alias="X-Device-Key")] = None):
    results = await service.taps(device_key, body.taps)
    if results is None:
        raise AppError(401, "NOT_AUTHENTICATED")
    return TapsOut(results=results)


@router.get("/devices", response_model=list[DeviceOut])
async def list_devices(_: Gate, session: Session):
    return await crud.list_live(session, Device, Device.name)


@router.post("/devices", response_model=DeviceCreated, status_code=201, summary="Register a device; key shown once")
async def create_device(body: DeviceIn, principal: Gate, session: Session):
    return await service.create_device(session, principal, body)


@router.patch("/devices/{device_id}", response_model=DeviceOut, summary="Rename, move or disable a device")
async def update_device(device_id: uuid.UUID, body: DeviceUpdate, _: Gate, session: Session):
    device = await crud.update(session, Device, device_id, body.model_dump(exclude_unset=True))
    return service.device_out(device)


@router.post("/devices/{device_id}/rotate-key", response_model=DeviceCreated, summary="New key; the old one stops")
async def rotate_key(device_id: uuid.UUID, _: Gate, session: Session):
    return await service.rotate_key(session, device_id)


@router.get("/rfid-cards", response_model=list[CardOut])
async def list_cards(_: Gate, session: Session, student_id: uuid.UUID | None = None):
    return await service.card_rows(session, *([RfidCard.student_id == student_id] if student_id else []))


@router.post(
    "/rfid-cards",
    response_model=CardOut,
    status_code=201,
    responses={409: {"description": "card already registered (card_in_use)"}},
    summary="Issue a card; it replaces the student's active card of the same kind",
)
async def issue_card(body: CardIn, principal: Gate, session: Session):
    return await service.issue_card(session, principal, body)


@router.patch("/rfid-cards/{card_id}", response_model=CardOut, summary="Report a card LOST or REVOKED")
async def update_card(card_id: uuid.UUID, body: CardUpdate, _: Gate, session: Session):
    return await service.set_card_status(session, card_id, body.status)
