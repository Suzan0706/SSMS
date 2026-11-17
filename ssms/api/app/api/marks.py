"""/marks: sheet (ETag), offline batch sync, Excel template and upload (all-or-nothing job)."""

import hashlib
import json
import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, File, Form, Header, Response, UploadFile
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import Principal, active_principal, require_permission
from app.api.imports import XLSX, JobOut, job_out
from app.core.config import get_settings
from app.core.errors import forbidden
from app.core.files import read_limited
from app.core.storage import get_storage
from app.db.session import get_session
from app.models import BackgroundJob, Stream, Term
from app.models.enums import JobKind, JobStatus
from app.schemas.marks import BatchIn, BatchOut, SheetOut
from app.services import crud, idempotency, imports
from app.services import marks as service
from app.tasks.dispatch import get_dispatcher

router = APIRouter(prefix="/marks", tags=["marks"])
Session = Annotated[AsyncSession, Depends(get_session)]
Signed = Annotated[Principal, Depends(active_principal)]


@router.get(
    "/sheet",
    response_model=SheetOut,
    responses={304: {"description": "unchanged"}},
    summary="Students × components with score, absence, version and lock (own assignment only)",
)
async def get_sheet(
    term_id: uuid.UUID,
    stream_id: uuid.UUID,
    subject_id: uuid.UUID,
    principal: Signed,
    session: Session,
    response: Response,
    if_none_match: Annotated[str | None, Header(alias="If-None-Match")] = None,
):
    out = await service.sheet(session, principal, term_id, stream_id, subject_id)
    etag = service.sheet_etag(out)
    if if_none_match == etag:
        return Response(status_code=304, headers={"ETag": etag})
    response.headers["ETag"] = etag
    return out


@router.put(
    "/batch",
    response_model=BatchOut,
    summary="Sync marks entered offline; each item is ok, conflict (with the server value) or error",
)
async def put_batch(
    body: BatchIn, principal: Annotated[Principal, require_permission("marks.enter")], session: Session
):
    return await service.save_batch(session, principal, body.items)


@router.get(
    "/template",
    response_class=Response,
    responses={200: {"content": {XLSX: {}}}},
    summary="Excel sheet of one stream and subject with the current marks",
)
async def template(
    term_id: uuid.UUID, stream_id: uuid.UUID, subject_id: uuid.UUID, principal: Signed, session: Session
):
    data = await service.template(session, principal, term_id, stream_id, subject_id)
    return Response(data, media_type=XLSX, headers={"Content-Disposition": 'attachment; filename="marks.xlsx"'})


@router.post(
    "/upload",
    response_model=JobOut,
    status_code=202,
    summary="Upload the filled template (Idempotency-Key); validated and saved all-or-nothing",
)
async def upload(
    term_id: Annotated[uuid.UUID, Form()],
    stream_id: Annotated[uuid.UUID, Form()],
    subject_id: Annotated[uuid.UUID, Form()],
    file: Annotated[UploadFile, File()],
    principal: Annotated[Principal, require_permission("marks.enter")],
    session: Session,
    idempotency_key: Annotated[str | None, Header(alias="Idempotency-Key")] = None,
):
    key = idempotency.require_key(idempotency_key)
    term = await crud.get_live(session, Term, term_id)
    await crud.get_live(session, Stream, stream_id)
    if not await service.may_enter(session, principal, term, stream_id, subject_id):
        raise forbidden()
    data = await read_limited(file, get_settings().max_import_bytes)
    imports.sniff(data)  # XLSX or CSV, else FILE_TYPE
    digest = hashlib.sha256(data + f"{term_id}{stream_id}{subject_id}".encode()).hexdigest()
    previous = await idempotency.replay(session, "POST /marks/upload", key, digest)
    if previous:
        return job_out(await crud.get_live(session, BackgroundJob, uuid.UUID(previous["job_id"])))
    job = BackgroundJob(
        school_id=principal.school_id,
        kind=JobKind.IMPORT_MARKS,
        status=JobStatus.QUEUED,
        idempotency_key=key,
        requested_by=principal.user_id,
        created_by=principal.user_id,
    )
    storage = get_storage()
    job.input_file_key = storage.put(f"{principal.school_id}/marks/{job.id}/input.{imports.sniff(data)}", data)
    storage.put(
        service.params_key(principal.school_id, job.id),
        json.dumps({"term_id": str(term_id), "stream_id": str(stream_id), "subject_id": str(subject_id)}).encode(),
    )
    session.add(job)
    idempotency.remember(session, principal, "POST /marks/upload", key, digest, 202, {"job_id": str(job.id)})
    await session.commit()
    get_dispatcher().send("marks.upload", job_id=str(job.id), school_id=str(principal.school_id))
    return job_out(job)
