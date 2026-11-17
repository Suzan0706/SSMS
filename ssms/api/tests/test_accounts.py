"""Other income and expenses on the ledger, reversals, income statement, cash book and fines (FR-87, FR-88, FR-89)."""

from datetime import timedelta
from decimal import Decimal

import pytest
from sqlalchemy import func, select

from app.models import Invoice, InvoiceLine, Journal, LedgerEntry
from app.services import calendar
from tests.helpers import SCHOOL_A, as_school, bearer, login

API = "/api/v1"


@pytest.fixture
async def admin(client) -> dict:
    return bearer(await login(client))  # accounts.read, accounts.approve, fines.configure


@pytest.fixture
async def bursar(client) -> dict:
    return bearer(await login(client, username="bursar"))  # accounts.record, accounts.read


async def category(client, headers, kind: str, code: str) -> str:
    rows = (await client.get(f"{API}/accounts/categories?kind={kind}", headers=headers)).json()
    return next(c["id"] for c in rows if c["account_code"] == code)


async def test_an_expense_and_an_income_post_balanced_journals_and_show_in_the_books(client, db, admin, bursar):
    today = calendar.today().isoformat()
    utilities = await category(client, bursar, "EXPENSE", "5100")
    donations = await category(client, bursar, "INCOME", "4810")
    paid = await client.post(
        f"{API}/accounts/entries",
        headers=bursar,
        json={
            "category_id": utilities,
            "entry_date": today,
            "amount_tzs": "150000",
            "method": "CASH",
            "party": "TANESCO",
            "description": "Umeme wa mwezi",
        },
    )
    assert paid.status_code == 201, paid.text
    assert paid.json()["entry_no"].startswith(f"CE-{today[:4]}-")
    received = await client.post(
        f"{API}/accounts/entries",
        headers=bursar,
        json={
            "category_id": donations,
            "entry_date": today,
            "amount_tzs": "500000",
            "method": "BANK",
            "party": "Wazazi",
            "description": "Mchango wa maktaba",
        },
    )
    assert received.status_code == 201

    await as_school(db, SCHOOL_A)
    totals = (
        await db.execute(
            select(func.sum(LedgerEntry.debit_tzs), func.sum(LedgerEntry.credit_tzs))
            .join(Journal, Journal.id == LedgerEntry.journal_id)
            .where(Journal.source_type == "CASH_ENTRY")
        )
    ).one()
    assert totals[0] == totals[1] == Decimal("650000.00")

    statement = (await client.get(f"{API}/accounts/income-statement?from={today}&to={today}", headers=admin)).json()
    assert {"code": "5100", "amount_tzs": "150000.00"}.items() <= next(
        e for e in statement["expenses"] if e["code"] == "5100"
    ).items()
    assert next(i for i in statement["income"] if i["code"] == "4810")["amount_tzs"] == "500000.00"
    book = (await client.get(f"{API}/accounts/cash-book?account=1000&from={today}&to={today}", headers=bursar)).json()
    assert book["lines"][-1]["money_out_tzs"] == "150000.00"
    assert Decimal(book["closing_tzs"]) == Decimal(book["opening_tzs"]) - Decimal("150000")


async def test_entries_are_validated_and_only_the_bursar_records(client, bursar):
    teacher = bearer(await login(client, username="tch.mwita"))
    utilities = await category(client, bursar, "EXPENSE", "5100")
    body = {
        "category_id": utilities,
        "entry_date": calendar.today().isoformat(),
        "amount_tzs": "1000",
        "method": "CASH",
        "description": "Maji",
    }
    assert (await client.post(f"{API}/accounts/entries", headers=teacher, json=body)).status_code == 403
    future = {**body, "entry_date": (calendar.today() + timedelta(days=1)).isoformat()}
    assert (await client.post(f"{API}/accounts/entries", headers=bursar, json=future)).status_code == 422
    assert (
        await client.post(f"{API}/accounts/entries", headers=bursar, json={**body, "amount_tzs": "0"})
    ).status_code == 422
    assert (await client.get(f"{API}/accounts/entries", headers=teacher)).status_code == 403


async def test_a_reversal_is_asked_by_one_person_and_approved_by_another(client, admin, bursar):
    today = calendar.today().isoformat()
    supplies = await category(client, bursar, "EXPENSE", "5200")
    entry = (
        await client.post(
            f"{API}/accounts/entries",
            headers=bursar,
            json={
                "category_id": supplies,
                "entry_date": today,
                "amount_tzs": "80000",
                "method": "MOBILE_MONEY",
                "description": "Chaki na madaftari",
            },
        )
    ).json()
    url = f"{API}/accounts/entries/{entry['id']}"
    assert (await client.post(f"{url}/reversal-decision", headers=admin, json={"approve": True})).status_code == 409
    assert (
        await client.post(f"{url}/reversal-request", headers=bursar, json={"reason": "Kiasi si sahihi"})
    ).status_code == 204
    assert (
        await client.post(f"{url}/reversal-request", headers=bursar, json={"reason": "Tena tena"})
    ).status_code == 409
    assert (await client.post(f"{url}/reversal-decision", headers=bursar, json={"approve": True})).status_code == 403
    assert (await client.post(f"{url}/reversal-decision", headers=admin, json={"approve": True})).status_code == 204

    rows = (await client.get(f"{API}/accounts/entries?from={today}&to={today}", headers=admin)).json()
    reversed_entry = next(r for r in rows if r["id"] == entry["id"])
    assert reversed_entry["status"] == "REVERSED"
    statement = (await client.get(f"{API}/accounts/income-statement?from={today}&to={today}", headers=admin)).json()
    assert next(e for e in statement["expenses"] if e["code"] == "5200")["amount_tzs"] == "0.00"  # nets to nothing
    assert (
        await client.post(f"{url}/reversal-request", headers=bursar, json={"reason": "Mara ya pili"})
    ).status_code == 409


async def test_categories_post_to_an_account_of_their_own_kind(client, admin):
    expense_accounts = (await client.get(f"{API}/accounts/ledger-accounts?kind=EXPENSE", headers=admin)).json()
    income_accounts = (await client.get(f"{API}/accounts/ledger-accounts?kind=INCOME", headers=admin)).json()
    other = next(a["id"] for a in expense_accounts if a["code"] == "5900")
    ok = await client.post(
        f"{API}/accounts/categories",
        headers=admin,
        json={"kind": "EXPENSE", "name_en": "Travel", "name_sw": "Safari", "ledger_account_id": other},
    )
    assert ok.status_code == 201
    wrong = await client.post(
        f"{API}/accounts/categories",
        headers=admin,
        json={"kind": "EXPENSE", "name_en": "Wrong", "name_sw": "Kosa", "ledger_account_id": income_accounts[0]["id"]},
    )
    assert wrong.status_code == 422


async def test_the_late_fee_is_charged_once_on_overdue_invoices(client, db, admin, bursar):
    assert (await client.post(f"{API}/fine-rules/late-fee/apply", headers=admin)).status_code == 409  # no rule yet
    rule = await client.put(f"{API}/fine-rules/late-fee", headers=admin, json={"amount_tzs": "5000", "grace_days": 7})
    assert rule.status_code == 200 and Decimal(rule.json()["amount_tzs"]) == Decimal("5000")
    assert (await client.put(f"{API}/fine-rules/late-fee", headers=bursar, json={"amount_tzs": "1"})).status_code == 200
    rule = await client.put(f"{API}/fine-rules/late-fee", headers=admin, json={"amount_tzs": "5000", "grace_days": 7})

    await as_school(db, SCHOOL_A)
    overdue = (
        await db.execute(
            select(func.count()).where(
                Invoice.cancelled_at.is_(None),
                Invoice.balance_tzs > 0,
                Invoice.due_date < calendar.today() - timedelta(days=7),
            )
        )
    ).scalar_one()
    first = (await client.post(f"{API}/fine-rules/late-fee/apply", headers=admin)).json()
    assert first["charged"] == overdue and overdue >= 1
    again = (await client.post(f"{API}/fine-rules/late-fee/apply", headers=admin)).json()
    assert again["charged"] == 0  # once per invoice
    fines = (
        await db.execute(select(func.count()).where(InvoiceLine.description.like("Late payment fine%")))
    ).scalar_one()
    assert fines == overdue
