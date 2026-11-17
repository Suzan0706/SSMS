"""Other income and expenses, the income statement, the cash book and late-payment fines (FR-87, FR-88, FR-89).

Every entry posts one balanced journal through ledger.post (ADR 0006): income debits the money account of the method
and credits the category's income account; an expense debits the category's expense account and credits the money
account. A posted entry never changes (database trigger); a reversal is asked for by one person and approved by
another, and posts the mirror journal.
"""

import uuid
from datetime import date, datetime, time, timedelta
from decimal import Decimal

from sqlalchemy import and_, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import Principal
from app.core.errors import AppError, not_found
from app.models import (
    CashEntry,
    FeeItem,
    FinanceCategory,
    FineRule,
    Invoice,
    InvoiceLine,
    Journal,
    LedgerAccount,
    LedgerEntry,
    StoredFile,
)
from app.models.enums import FilePurpose, JournalSource
from app.services import audit, calendar, crud, invoices, ledger
from app.services.ledger import Line
from app.services.people import now

MONEY_ACCOUNTS = {"CASH": ledger.CASH, "BANK": ledger.BANK, "MOBILE_MONEY": ledger.MOBILE, "CHEQUE": ledger.BANK}
ZERO = Decimal("0.00")


# ---------------------------------------------------------------- categories


async def list_categories(session: AsyncSession, principal: Principal, kind: str | None) -> list[dict]:
    stmt = (
        select(FinanceCategory, LedgerAccount.code)
        .join(LedgerAccount, LedgerAccount.id == FinanceCategory.ledger_account_id)
        .where(FinanceCategory.deleted_at.is_(None))
        .order_by(FinanceCategory.kind, FinanceCategory.name_en)
    )
    if kind:
        stmt = stmt.where(FinanceCategory.kind == kind)
    return [
        {
            "id": c.id,
            "kind": c.kind,
            "name": c.name_en if principal.language == "en" else c.name_sw,
            "name_en": c.name_en,
            "name_sw": c.name_sw,
            "account_code": code,
        }
        for c, code in (await session.execute(stmt)).all()
    ]


async def create_category(session: AsyncSession, principal: Principal, body) -> uuid.UUID:
    account = await session.get(LedgerAccount, body.ledger_account_id)
    if account is None or account.kind != body.kind:
        raise AppError(422, "VALIDATION_ERROR", [{"field": "ledger_account_id", "code": "wrong_kind"}])
    item = FinanceCategory(
        school_id=principal.school_id,
        kind=body.kind,
        name_en=body.name_en,
        name_sw=body.name_sw,
        ledger_account_id=account.id,
        created_by=principal.user_id,
    )
    session.add(item)
    await crud.flush_checked(session, "name_en", "duplicate")
    await session.commit()
    return item.id


async def accounts_of_kind(session: AsyncSession, kind: str) -> list[dict]:
    rows = await session.execute(
        select(LedgerAccount.id, LedgerAccount.code, LedgerAccount.name_en, LedgerAccount.name_sw)
        .where(LedgerAccount.kind == kind)
        .order_by(LedgerAccount.code)
    )
    return [{"id": i, "code": c, "name_en": en, "name_sw": sw} for i, c, en, sw in rows]


# ---------------------------------------------------------------- entries


def _lines(kind: str, category_account: uuid.UUID, money_account: uuid.UUID, amount: Decimal) -> list[Line]:
    if kind == "INCOME":
        return [Line(money_account, debit=amount), Line(category_account, credit=amount)]
    return [Line(category_account, debit=amount), Line(money_account, credit=amount)]


async def record(session: AsyncSession, principal: Principal, body) -> CashEntry:
    if body.entry_date > calendar.today():
        raise AppError(422, "VALIDATION_ERROR", [{"field": "entry_date", "code": "future_date"}])
    category = await session.get(FinanceCategory, body.category_id)
    if category is None or category.deleted_at is not None:
        raise AppError(422, "INVALID_REFERENCE", [{"field": "category_id", "code": "invalid_value"}])
    if body.attachment_file_id:
        upload = await session.get(StoredFile, body.attachment_file_id)
        if upload is None or upload.purpose != FilePurpose.RECEIPT or upload.created_by != principal.user_id:
            raise AppError(422, "VALIDATION_ERROR", [{"field": "attachment_file_id", "code": "invalid_value"}])
    entry_id = uuid.uuid4()
    money = await ledger.account(session, MONEY_ACCOUNTS[body.method])
    when = datetime.combine(body.entry_date, time(12, 0), tzinfo=calendar.EAT)
    journal = await ledger.post(
        session,
        school_id=principal.school_id,
        source_type=JournalSource.CASH_ENTRY,
        source_id=entry_id,
        memo=f"{category.name_en}: {body.description}",
        lines=_lines(category.kind, category.ledger_account_id, money, body.amount_tzs),
        posted_by=principal.user_id,
        when=when,
    )
    entry = CashEntry(
        id=entry_id,
        school_id=principal.school_id,
        entry_no=await ledger.next_number(session, principal.school_id, "CASH_ENTRY", body.entry_date.year, "CE"),
        category_id=category.id,
        entry_date=body.entry_date,
        amount_tzs=body.amount_tzs,
        method=body.method,
        reference=body.reference,
        party=body.party,
        description=body.description,
        attachment_file_id=body.attachment_file_id,
        journal_id=journal.id,
        created_by=principal.user_id,
    )
    session.add(entry)
    await session.commit()
    return entry


async def list_entries(
    session: AsyncSession, principal: Principal, *, start: date, end: date, kind: str | None
) -> list[dict]:
    stmt = (
        select(CashEntry, FinanceCategory)
        .join(FinanceCategory, FinanceCategory.id == CashEntry.category_id)
        .where(CashEntry.entry_date.between(start, end))
        .order_by(CashEntry.entry_date.desc(), CashEntry.entry_no.desc())
        .limit(500)
    )
    if kind:
        stmt = stmt.where(FinanceCategory.kind == kind)
    return [
        {
            "id": e.id,
            "entry_no": e.entry_no,
            "entry_date": e.entry_date,
            "kind": c.kind,
            "category": c.name_en if principal.language == "en" else c.name_sw,
            "amount_tzs": e.amount_tzs,
            "method": e.method,
            "reference": e.reference,
            "party": e.party,
            "description": e.description,
            "status": e.status,
            "reversal_pending": e.status == "POSTED" and e.reversal_requested_by is not None,
            "reversal_reason": e.reversal_reason,
            "requested_by_me": e.reversal_requested_by == principal.user_id,
            "has_attachment": e.attachment_file_id is not None,
        }
        for e, c in (await session.execute(stmt)).all()
    ]


async def _entry(session: AsyncSession, entry_id: uuid.UUID) -> CashEntry:
    entry = await session.get(CashEntry, entry_id, with_for_update=True)
    if entry is None:
        raise not_found()
    return entry


async def request_reversal(session: AsyncSession, principal: Principal, entry_id: uuid.UUID, reason: str) -> None:
    entry = await _entry(session, entry_id)
    if entry.status != "POSTED" or entry.reversal_requested_by is not None:
        raise AppError(409, "NOT_ALLOWED", [{"field": "status", "code": "already_requested"}])
    entry.reversal_requested_by, entry.reversal_reason = principal.user_id, reason
    await session.commit()


async def decide_reversal(session: AsyncSession, principal: Principal, entry_id: uuid.UUID, approve: bool) -> None:
    entry = await _entry(session, entry_id)
    if entry.status != "POSTED" or entry.reversal_requested_by is None:
        raise AppError(409, "NOT_ALLOWED", [{"field": "status", "code": "no_request"}])
    if entry.reversal_requested_by == principal.user_id:
        raise AppError(403, "NOT_ALLOWED", [{"field": "reversal_approved_by", "code": "own_request"}])
    if not approve:
        entry.reversal_requested_by, entry.reversal_reason = None, None
        await session.commit()
        return
    lines = (await session.execute(select(LedgerEntry).where(LedgerEntry.journal_id == entry.journal_id))).scalars()
    mirror = [Line(ln.account_id, debit=ln.credit_tzs, credit=ln.debit_tzs, student_id=ln.student_id) for ln in lines]
    journal = await ledger.post(
        session,
        school_id=entry.school_id,
        source_type=JournalSource.CASH_REVERSE,
        source_id=entry.id,
        memo=f"Reversal of {entry.entry_no}: {entry.reversal_reason}",
        lines=mirror,
        posted_by=principal.user_id,
        when=now(),
    )
    entry.status, entry.reversal_approved_by, entry.reversal_journal_id = "REVERSED", principal.user_id, journal.id
    await session.commit()


# ---------------------------------------------------------------- statements


def _range(start: date, end: date):
    first = datetime.combine(start, time.min, tzinfo=calendar.EAT)
    after = datetime.combine(end + timedelta(days=1), time.min, tzinfo=calendar.EAT)
    return Journal.posted_at >= first, Journal.posted_at < after


async def income_statement(session: AsyncSession, principal: Principal, start: date, end: date) -> dict:
    """Income and expenses by account for a period, from the ledger (fees included)."""
    rows = (
        await session.execute(
            select(
                LedgerAccount.code,
                LedgerAccount.name_en,
                LedgerAccount.name_sw,
                LedgerAccount.kind,
                func.sum(LedgerEntry.credit_tzs - LedgerEntry.debit_tzs),
            )
            .join(LedgerEntry, LedgerEntry.account_id == LedgerAccount.id)
            .join(Journal, Journal.id == LedgerEntry.journal_id)
            .where(LedgerAccount.kind.in_(("INCOME", "EXPENSE")), *_range(start, end))
            .group_by(LedgerAccount.code, LedgerAccount.name_en, LedgerAccount.name_sw, LedgerAccount.kind)
            .order_by(LedgerAccount.code)
        )
    ).all()
    income, expenses = [], []
    for code, en, sw, kind, net in rows:
        amount = net or ZERO
        row = {"code": code, "name": en if principal.language == "en" else sw}
        if kind == "INCOME":
            income.append({**row, "amount_tzs": amount})
        else:
            expenses.append({**row, "amount_tzs": -amount})
    total_in = sum((r["amount_tzs"] for r in income), ZERO)
    total_out = sum((r["amount_tzs"] for r in expenses), ZERO)
    return {
        "date_from": start,
        "date_to": end,
        "income": income,
        "expenses": expenses,
        "total_income_tzs": total_in,
        "total_expenses_tzs": total_out,
        "net_tzs": total_in - total_out,
    }


async def cash_book(session: AsyncSession, account_code: str, start: date, end: date) -> dict:
    """Movements of one money account with opening and running balances."""
    account = await ledger.account(session, account_code)
    first, _after = _range(start, end)
    opening = (
        await session.execute(
            select(func.coalesce(func.sum(LedgerEntry.debit_tzs - LedgerEntry.credit_tzs), 0))
            .join(Journal, Journal.id == LedgerEntry.journal_id)
            .where(LedgerEntry.account_id == account, ~first)
        )
    ).scalar_one()
    rows = (
        await session.execute(
            select(Journal.posted_at, Journal.journal_no, Journal.memo, LedgerEntry.debit_tzs, LedgerEntry.credit_tzs)
            .join(Journal, Journal.id == LedgerEntry.journal_id)
            .where(LedgerEntry.account_id == account, *_range(start, end))
            .order_by(Journal.posted_at, Journal.journal_no)
        )
    ).all()
    balance = Decimal(opening)
    lines = []
    for posted_at, number, memo, debit, credit in rows:
        balance += debit - credit
        lines.append(
            {
                "date": calendar.local(posted_at).date(),
                "journal_no": number,
                "memo": memo,
                "money_in_tzs": debit,
                "money_out_tzs": credit,
                "balance_tzs": balance,
            }
        )
    return {"account_code": account_code, "opening_tzs": Decimal(opening), "closing_tzs": balance, "lines": lines}


# ---------------------------------------------------------------- fines


async def fine_rule(session: AsyncSession, kind: str = "LATE_FEE") -> FineRule | None:
    """The active rule of a kind: LATE_FEE (flat, per overdue invoice) or LIBRARY_DAY (per day a book is late)."""
    return (
        await session.execute(select(FineRule).where(FineRule.kind == kind, FineRule.active.is_(True)))
    ).scalar_one_or_none()


async def set_fine_rule(session: AsyncSession, principal: Principal, body, kind: str = "LATE_FEE") -> FineRule:
    """Replace the active rule of a kind (the old one stays on record, inactive)."""
    item = (await session.execute(select(FeeItem.id).where(FeeItem.code == "FINE"))).scalar_one_or_none()
    if item is None:
        raise AppError(422, "RULE_VIOLATION", [{"field": "fee_item", "code": "missing", "value": "FINE"}])
    old = await fine_rule(session, kind)
    if old is not None:
        old.active = False
        await session.flush()
    rule = FineRule(
        school_id=principal.school_id,
        kind=kind,
        fee_item_id=item,
        amount_tzs=body.amount_tzs,
        grace_days=body.grace_days,
        active=body.active,
        created_by=principal.user_id,
    )
    session.add(rule)
    await session.commit()
    return rule


async def apply_late_fees(session: AsyncSession, principal: Principal) -> list[str]:
    """Charge the fine once on every unpaid invoice past its due date plus the grace days. Returns invoice numbers."""
    rule = await fine_rule(session)
    if rule is None:
        raise AppError(409, "NOT_ALLOWED", [{"field": "fine_rule", "code": "none_active"}])
    cutoff = calendar.today() - timedelta(days=rule.grace_days)
    fined = select(InvoiceLine.invoice_id).where(InvoiceLine.fee_item_id == rule.fee_item_id)
    due = (
        await session.execute(
            select(Invoice.id, Invoice.student_id, Invoice.term_id).where(
                and_(
                    Invoice.cancelled_at.is_(None),
                    Invoice.balance_tzs > 0,
                    Invoice.due_date < cutoff,
                    Invoice.id.not_in(fined),
                )
            )
        )
    ).all()
    charged = []
    for _invoice_id, student_id, term_id in due:
        number = await invoices.add_charges(
            session,
            principal.school_id,
            student_id,
            term_id,
            [(rule.fee_item_id, "Late payment fine / Faini ya kuchelewa", rule.amount_tzs)],
            principal.user_id,
        )
        if number:
            charged.append(number)
    await audit.record(session, "UPDATE", "fine_rules", rule.id, {"applied_to": len(charged)})
    await session.commit()
    return charged
