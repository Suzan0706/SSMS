"""Double-entry postings. Every money event writes one journal whose lines balance; the database re-checks the
balance at COMMIT (deferred trigger) and keeps journals append-only.

Accounts are found by their code (seeded at onboarding): 1000 cash, 1100 GePG clearing, 1110 mobile money,
1200 bank, 1300 fees receivable (per student), 2100 student credit (per student), 4900 discounts allowed.
"""

import uuid
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal

from sqlalchemy import SmallInteger, cast, func, literal, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import AppError
from app.models import Journal, LedgerAccount, LedgerEntry
from app.models.enums import Channel

CASH, GEPG, MOBILE, BANK, RECEIVABLE, CREDIT, DISCOUNTS = "1000", "1100", "1110", "1200", "1300", "2100", "4900"
CLEARING = {Channel.CASH: CASH, Channel.GEPG: GEPG, Channel.BANK: BANK}  # other channels: mobile money
ZERO = Decimal("0.00")


@dataclass
class Line:
    account_id: uuid.UUID
    debit: Decimal = ZERO
    credit: Decimal = ZERO
    student_id: uuid.UUID | None = None


async def accounts(session: AsyncSession) -> dict[str, uuid.UUID]:
    return dict((await session.execute(select(LedgerAccount.code, LedgerAccount.id))).all())


async def account(session: AsyncSession, code: str) -> uuid.UUID:
    found = (await accounts(session)).get(code)
    if found is None:
        raise AppError(
            422,
            "RULE_VIOLATION",
            [{"field": "ledger_account", "code": "invalid_value", "value": code}],
            detail=f"ledger account {code} is missing",
        )
    return found


def clearing_code(channel: Channel) -> str:
    return CLEARING.get(channel, MOBILE)


async def next_number(session: AsyncSession, school_id: uuid.UUID, doc_type: str, year: int, prefix: str) -> str:
    seq = (
        await session.execute(select(func.next_document_no(school_id, literal(doc_type), cast(year, SmallInteger))))
    ).scalar_one()
    return f"{prefix}-{year}-{seq:06d}"


async def post(
    session: AsyncSession,
    *,
    school_id: uuid.UUID,
    source_type: str,
    source_id: uuid.UUID,
    memo: str,
    lines: list[Line],
    posted_by: uuid.UUID | None,
    when: datetime,
) -> Journal:
    """Write one balanced journal (lines with zero amounts are dropped)."""
    lines = [ln for ln in lines if ln.debit > 0 or ln.credit > 0]
    debit, credit = sum((ln.debit for ln in lines), ZERO), sum((ln.credit for ln in lines), ZERO)
    if len(lines) < 2 or debit != credit:
        raise AppError(500, "INTERNAL_ERROR", detail=f"unbalanced journal {debit} / {credit}")
    journal = Journal(
        school_id=school_id,
        journal_no=await next_number(session, school_id, "JOURNAL", when.year, "JNL"),
        posted_at=when,
        source_type=source_type,
        source_id=source_id,
        memo=memo[:200],
        posted_by=posted_by,
        created_by=posted_by,
    )
    session.add(journal)
    await session.flush()
    session.add_all(
        [
            LedgerEntry(
                school_id=school_id,
                journal_id=journal.id,
                account_id=ln.account_id,
                student_id=ln.student_id,
                debit_tzs=ln.debit,
                credit_tzs=ln.credit,
                created_by=posted_by,
            )
            for ln in lines
        ]
    )
    await session.flush()
    return journal


def tzs(amount: Decimal) -> str:
    """680000.00 -> '680,000'; 12.50 -> '12.50'."""
    return f"{amount:,.0f}" if amount == amount.to_integral() else f"{amount:,.2f}"


# ---------------------------------------------------------------- amounts in words (receipts) — wording VERIFY

_SW_UNITS = ["", "moja", "mbili", "tatu", "nne", "tano", "sita", "saba", "nane", "tisa"]
_SW_TENS = ["", "kumi", "ishirini", "thelathini", "arobaini", "hamsini", "sitini", "sabini", "themanini", "tisini"]


def _sw(n: int) -> str:
    if n < 10:
        return _SW_UNITS[n]
    if n < 100:
        tens, unit = divmod(n, 10)
        return _SW_TENS[tens] + (f" na {_SW_UNITS[unit]}" if unit else "")
    if n < 1000:
        hundreds, rest = divmod(n, 100)
        return f"mia {_SW_UNITS[hundreds]}" + (f" na {_sw(rest)}" if rest else "")
    if n < 100_000:
        thousands, rest = divmod(n, 1000)
        return f"elfu {_sw(thousands)}" + (f" na {_sw(rest)}" if rest else "")
    if n < 1_000_000:
        lakh, rest = divmod(n, 100_000)
        return f"laki {_SW_UNITS[lakh]}" + (f" na {_sw(rest)}" if rest else "")
    millions, rest = divmod(n, 1_000_000)
    return f"milioni {_sw(millions)}" + (f", {_sw(rest)}" if rest else "")


_EN_SMALL = [
    "zero",
    "one",
    "two",
    "three",
    "four",
    "five",
    "six",
    "seven",
    "eight",
    "nine",
    "ten",
    "eleven",
    "twelve",
    "thirteen",
    "fourteen",
    "fifteen",
    "sixteen",
    "seventeen",
    "eighteen",
    "nineteen",
]
_EN_TENS = ["", "", "twenty", "thirty", "forty", "fifty", "sixty", "seventy", "eighty", "ninety"]


def _en(n: int) -> str:
    if n < 20:
        return _EN_SMALL[n]
    if n < 100:
        tens, unit = divmod(n, 10)
        return _EN_TENS[tens] + (f"-{_EN_SMALL[unit]}" if unit else "")
    if n < 1000:
        hundreds, rest = divmod(n, 100)
        return f"{_EN_SMALL[hundreds]} hundred" + (f" and {_en(rest)}" if rest else "")
    for size, name in ((1_000_000_000, "billion"), (1_000_000, "million"), (1000, "thousand")):
        if n >= size:
            head, rest = divmod(n, size)
            return f"{_en(head)} {name}" + ((" and " if rest < 100 else ", ") + _en(rest) if rest else "")
    return str(n)


def in_words(amount: Decimal, lang: str) -> str:
    shillings = int(amount)
    cents = int((amount - shillings) * 100)
    if lang == "sw":
        text = f"Shilingi {_sw(shillings) if shillings else 'sifuri'}"
        return text + (f" na senti {_sw(cents)}" if cents else "") + " tu"
    text = f"{_en(shillings).capitalize()} shillings"
    return text + (f" and {_en(cents)} cents" if cents else "") + " only"
