"""/files: upload a file for a purpose, read it back, discard it (design/20 §20.3)."""

import uuid
from datetime import datetime
from typing import Annotated
from urllib.parse import quote

from fastapi import APIRouter, Depends, File, Form, Response, UploadFile, status
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import Principal, active_principal
from app.core.files import read_limited
from app.db.session import get_session
from app.models.enums import FilePurpose
from app.services import files as service

router = APIRouter(tags=["files"])


class FileOut(BaseModel):
    id: uuid.UUID
    purpose: FilePurpose
    original_name: str
    content_type: str
    size_bytes: int
    created_at: datetime
    url: str


def file_out(row) -> FileOut:
    return FileOut(
        id=row.id,
        purpose=row.purpose,
        original_name=row.original_name,
        content_type=row.content_type,
        size_bytes=row.size_bytes,
        created_at=row.created_at,
        url=f"/api/v1/files/{row.id}",
    )


@router.post(
    "/files",
    response_model=FileOut,
    status_code=status.HTTP_201_CREATED,
    summary="Upload a file; its type is read from the content and must suit the purpose",
)
async def upload(
    purpose: Annotated[FilePurpose, Form()],
    file: Annotated[UploadFile, File()],
    principal: Principal = Depends(active_principal),
    session: AsyncSession = Depends(get_session),
):
    rule = service.rule(purpose, principal)
    data = await read_limited(file, rule.max_bytes)
    row = await service.save(session, principal, purpose, file.filename, data)
    await session.commit()
    await session.refresh(row)
    return file_out(row)


@router.get(
    "/files/{file_id}",
    response_class=Response,
    summary="Read a file (the uploader, or people allowed by the record that uses it)",
    responses={200: {"content": {"application/octet-stream": {}}}},
)
async def read(
    file_id: uuid.UUID, principal: Principal = Depends(active_principal), session: AsyncSession = Depends(get_session)
):
    row, data = await service.open_for(session, principal, file_id)
    disposition = "inline" if row.content_type.startswith("image/") else "attachment"
    return Response(
        data,
        media_type=row.content_type,
        headers={
            "Content-Disposition": f"{disposition}; filename*=UTF-8''{quote(row.original_name)}",
            "Cache-Control": "private, no-store",
        },
    )


@router.delete("/files/{file_id}", status_code=status.HTTP_204_NO_CONTENT, summary="Discard your own upload")
async def discard(
    file_id: uuid.UUID, principal: Principal = Depends(active_principal), session: AsyncSession = Depends(get_session)
):
    await service.discard(session, principal, file_id)
    await session.commit()
