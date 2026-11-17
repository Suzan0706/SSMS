"""Daily reconciliation of one channel against the provider/bank statement (CSV: external_ref, amount).

Each statement line is MATCHED, AMOUNT_MISMATCH or MISSING_IN_SYSTEM; confirmed payments of that channel and day
that are not on the statement are MISSING_IN_STATEMENT. A run with no exception is BALANCED.
"""

import csv
import io
import uuid
from datetime import date
from decimal import Decimal, InvalidOperation

from sqlalchemy import Date, cast, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import Principal
from app.core.errors import AppError, not_found
from app.core.storage import get_storage
from app.models import Payment, ReconciliationItem, ReconciliationRun
from app.models.enums import Channel, MatchStatus, PaymentStatus, RunStatus
from app.schemas.finance import ReconciliationItemOut, ReconciliationRunOut
from app.services.people import now


def parse_statement(data: bytes) -> list[tuple[str, Decimal]]:
    try:
        rows = list(csv.DictReader(io.StringIO(data.decode("utf-8-sig"))))
    except UnicodeDecodeError:
        raise AppError(422, "FILE_TYPE") from None
    lines = []
    for n, row in enumerate(rows, start=2):
        ref = (row.get("external_ref") or row.get("reference") or "").strip()
        try:
            amount = Decimal((row.get("amount") or "").replace(",", ""))
        except InvalidOperation:
            raise AppError(422, "VALIDATION_ERROR", [{"field": f"row {n}", "code": "invalid_value"}]) from None
        if ref:
            lines.append((ref, amount))
    if not lines:
        raise AppError(422, "IMPORT_HEADERS", [{"field": "file", "code": "required"}])
    return lines


async def run(
    session: AsyncSession, principal: Principal, run_date: date, channel: Channel, data: bytes
) -> ReconciliationRun:
    lines = parse_statement(data)
    local_day = cast(func.timezone("Africa/Dar_es_Salaam", Payment.received_at), Date)
    payments = (
        (
            await session.execute(
                select(Payment).where(
                    Payment.channel == channel,
                    local_day == run_date,
                    Payment.status.in_([PaymentStatus.CONFIRMED, PaymentStatus.REVERSED]),
                )
            )
        )
        .scalars()
        .all()
    )
    by_ref = {p.external_ref: p for p in payments}
    referenced = {ref: p for ref, p in by_ref.items()}
    # statement lines may also refer to payments recorded on another day
    others = (
        await session.execute(
            select(Payment).where(
                Payment.channel == channel, Payment.external_ref.in_([ref for ref, _ in lines if ref not in by_ref])
            )
        )
    ).scalars()
    referenced.update({p.external_ref: p for p in others})
    rec = ReconciliationRun(
        school_id=principal.school_id,
        run_date=run_date,
        channel=channel,
        created_by=principal.user_id,
        status=RunStatus.RUNNING,
    )
    rec.statement_file_key = get_storage().put(f"{principal.school_id}/reconciliation/{rec.id}.csv", data)
    session.add(rec)
    await session.flush()  # one run per day and channel -> 409 DUPLICATE
    items, seen = [], set()
    for ref, amount in lines:
        payment = referenced.get(ref)
        seen.add(ref)
        if payment is None:
            status = MatchStatus.MISSING_IN_SYSTEM
        elif payment.amount_tzs != amount or payment.status != PaymentStatus.CONFIRMED:
            status = MatchStatus.AMOUNT_MISMATCH
        else:
            status = MatchStatus.MATCHED
        items.append(
            ReconciliationItem(
                school_id=principal.school_id,
                run_id=rec.id,
                external_ref=ref,
                statement_amount_tzs=amount,
                payment_id=payment.id if payment else None,
                status=status,
                created_by=principal.user_id,
            )
        )
    for ref, payment in by_ref.items():
        if ref not in seen and payment.status == PaymentStatus.CONFIRMED:
            items.append(
                ReconciliationItem(
                    school_id=principal.school_id,
                    run_id=rec.id,
                    external_ref=ref,
                    payment_id=payment.id,
                    status=MatchStatus.MISSING_IN_STATEMENT,
                    created_by=principal.user_id,
                )
            )
    session.add_all(items)
    rec.statement_total_tzs = sum((a for _, a in lines), Decimal("0"))
    rec.system_total_tzs = sum((p.amount_tzs for p in payments if p.status == PaymentStatus.CONFIRMED), Decimal("0"))
    balanced = all(i.status == MatchStatus.MATCHED for i in items)
    rec.status = RunStatus.BALANCED if balanced else RunStatus.EXCEPTIONS
    rec.completed_at = now()
    await session.commit()
    return rec


async def _counts(session: AsyncSession, run_ids: list[uuid.UUID]) -> dict[uuid.UUID, dict[str, int]]:
    matched = func.count().filter(ReconciliationItem.status == MatchStatus.MATCHED)
    exceptions = func.count().filter(ReconciliationItem.status != MatchStatus.MATCHED)
    rows = await session.execute(
        select(ReconciliationItem.run_id, matched, exceptions)
        .where(ReconciliationItem.run_id.in_(run_ids))
        .group_by(ReconciliationItem.run_id)
    )
    return {run: {"matched_count": m, "exception_count": e} for run, m, e in rows.all()}


async def out_many(session: AsyncSession, runs: list[ReconciliationRun]) -> list[ReconciliationRunOut]:
    counts = await _counts(session, [r.id for r in runs])
    return [ReconciliationRunOut.model_validate(r).model_copy(update=counts.get(r.id, {})) for r in runs]


async def out(session: AsyncSession, rec: ReconciliationRun, with_items: bool = True) -> ReconciliationRunOut:
    items = []
    if with_items:
        items = (
            (
                await session.execute(
                    select(ReconciliationItem)
                    .where(ReconciliationItem.run_id == rec.id)
                    .order_by(ReconciliationItem.status, ReconciliationItem.external_ref)
                )
            )
            .scalars()
            .all()
        )
    [run] = await out_many(session, [rec])
    return run.model_copy(update={"items": [ReconciliationItemOut.model_validate(i) for i in items]})


async def resolve(
    session: AsyncSession, principal: Principal, item_id: uuid.UUID, note: str, payment_id: uuid.UUID | None
) -> ReconciliationItem:
    item = (
        await session.execute(select(ReconciliationItem).where(ReconciliationItem.id == item_id).with_for_update())
    ).scalar_one_or_none()
    if item is None:
        raise not_found()
    if payment_id:
        if not (await session.execute(select(Payment.id).where(Payment.id == payment_id))).first():
            raise AppError(422, "INVALID_REFERENCE", [{"field": "payment_id", "code": "invalid_value"}])
        item.payment_id = payment_id
    item.note, item.resolved_by, item.resolved_at = note, principal.user_id, now()
    await session.commit()
    return item
