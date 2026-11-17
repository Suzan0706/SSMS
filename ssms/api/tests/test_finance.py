"""Finance end to end through the API, with the accounting invariants checked after every money operation."""

import base64
import hashlib
import hmac
import json
from datetime import date

import pytest
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding, rsa
from sqlalchemy import select, text

from app.core.config import get_settings
from app.models import GepgBill, Payment, SmsMessage
from app.services import fee_reports, gepg
from app.services import invoices as invoice_service
from app.services import payments as payment_service
from tests.finance_helpers import assert_books_balance
from tests.helpers import F1, F2, F5, SCHOOL_A, TERM1, YEAR_2026, as_school, bearer, login, parent_login, rekey_phone, u

API = "/api/v1"
TERM2 = u(13, 2)
TUITION, MEALS, DEVELOPMENT = u(34, 1), u(34, 2), u(34, 4)
INCOME_TUITION, CASH_ACCOUNT = u(33, 7), u(33, 1)
INV = {n: u(36, n) for n in range(11, 17)}  # Form II, Term One; student u(6, n)


@pytest.fixture
async def admin(client) -> dict:
    return bearer(await login(client))


@pytest.fixture
async def bursar(client) -> dict:
    return bearer(await login(client, username="bursar"))


@pytest.fixture
def gepg_keys(monkeypatch):
    """Our service-provider key signs requests and ACKs; a second key plays GePG and signs its callbacks."""
    ours = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    theirs = rsa.generate_private_key(public_exponent=65537, key_size=2048)

    def pem(key) -> str:
        return key.private_bytes(
            serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption()
        ).decode()

    public = (
        theirs.public_key()
        .public_bytes(serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo)
        .decode()
    )
    monkeypatch.setattr(get_settings(), "gepg_private_key", pem(ours))
    monkeypatch.setattr(get_settings(), "gepg_public_key", public)

    def as_gepg(inner_tag: str, fields: dict) -> bytes:
        def sign(data: bytes) -> str:
            return base64.b64encode(theirs.sign(data, padding.PKCS1v15(), hashes.SHA256())).decode()

        return gepg.envelope(inner_tag, fields, sign_with=sign)

    return as_gepg, ours.public_key()


async def invoice(client, headers, invoice_id) -> dict:
    response = await client.get(f"{API}/invoices/{invoice_id}", headers=headers)
    assert response.status_code == 200, response.text
    return response.json()


# ---------------------------------------------------------------- fee setup


async def test_fee_items_and_structures(client, admin, bursar):
    bad = await client.post(
        f"{API}/fee-items",
        headers=admin,
        json={"code": "UNIFORM", "name_en": "Uniform", "name_sw": "Sare", "income_account_id": str(CASH_ACCOUNT)},
    )
    assert bad.status_code == 422
    item = await client.post(
        f"{API}/fee-items",
        headers=admin,
        json={"code": "UNIFORM", "name_en": "Uniform", "name_sw": "Sare", "income_account_id": str(INCOME_TUITION)},
    )
    assert item.status_code == 201

    structure = await client.post(
        f"{API}/fee-structures",
        headers=bursar,
        json={
            "academic_year_id": str(YEAR_2026),
            "class_id": str(F1),
            "name": "Form I 2026",
            "lines": [
                {"fee_item_id": str(TUITION), "term_id": str(TERM1), "amount_tzs": "400000"},
                {"fee_item_id": str(TUITION), "term_id": str(TERM2), "amount_tzs": "400000"},
                {"fee_item_id": str(DEVELOPMENT), "amount_tzs": "50000"},
                {"fee_item_id": item.json()["id"], "term_id": str(TERM1), "amount_tzs": "60000", "is_optional": True},
            ],
        },
    )
    assert structure.status_code == 201, structure.text
    body = structure.json()
    assert body["status"] == "DRAFT" and body["totals"] == {
        str(TERM1): "400000.00",
        str(TERM2): "400000.00",
        "yearly": "50000.00",
    }
    patched = await client.patch(
        f"{API}/fee-structures/{body['id']}",
        headers=bursar,
        json={"lines": [{"fee_item_id": str(TUITION), "term_id": str(TERM1), "amount_tzs": "420000"}]},
    )
    assert len(patched.json()["lines"]) == 1
    assert (await client.post(f"{API}/fee-structures/{body['id']}/approve", headers=bursar)).status_code == 403
    approved = await client.post(f"{API}/fee-structures/{body['id']}/approve", headers=admin)
    assert approved.json()["status"] == "APPROVED"
    frozen = await client.patch(f"{API}/fee-structures/{body['id']}", headers=bursar, json={"name": "x" * 5})
    assert frozen.status_code == 409
    duplicate = await client.post(
        f"{API}/fee-structures",
        headers=bursar,
        json={
            "academic_year_id": str(YEAR_2026),
            "class_id": str(F2),
            "name": "Second",
            "lines": [{"fee_item_id": str(TUITION), "term_id": str(TERM1), "amount_tzs": "1"}],
        },
    )
    assert duplicate.status_code == 409
    archived = await client.post(f"{API}/fee-structures/{body['id']}/archive", headers=bursar)
    assert archived.json()["status"] == "ARCHIVED"


async def test_discounts(client, bursar):
    rule = await client.post(
        f"{API}/discount-rules",
        headers=bursar,
        json={
            "code": "STAFF50",
            "name_en": "Staff child 50%",
            "name_sw": "Mtoto wa mtumishi 50%",
            "kind": "STAFF_CHILD",
            "percent": "50",
        },
    )
    assert rule.status_code == 201
    both = await client.post(
        f"{API}/discount-rules",
        headers=bursar,
        json={
            "code": "BAD",
            "name_en": "Bad rule",
            "name_sw": "Mbaya",
            "kind": "OTHER",
            "percent": "5",
            "amount_tzs": "5",
        },
    )
    assert both.status_code == 422
    given = await client.post(
        f"{API}/students/{u(6, 14)}/discounts",
        headers=bursar,
        json={
            "discount_rule_id": rule.json()["id"],
            "academic_year_id": str(YEAR_2026),
            "reason": "Mother teaches here",
        },
    )
    assert given.status_code == 201
    assert len((await client.get(f"{API}/students/{u(6, 14)}/discounts", headers=bursar)).json()) == 1


# ---------------------------------------------------------------- invoicing


async def _generate(client, headers, dispatcher, key, **body) -> dict:
    response = await client.post(f"{API}/invoices/generate", headers={**headers, "Idempotency-Key": key}, json=body)
    assert response.status_code == 202, response.text
    for call in dispatcher.take("invoices.generate"):
        await invoice_service.run_generation(**call)
    return (await client.get(f"{API}/jobs/{response.json()['id']}", headers=headers)).json()


async def test_generate_term_two_with_discount_credit_and_installments(client, db, bursar, dispatcher):
    job = await _generate(
        client,
        bursar,
        dispatcher,
        "invoice-run-term2",
        term_id=str(TERM2),
        class_ids=[str(F2)],
        due_date="2026-08-15",
        installments=[{"due_date": "2026-07-31", "percent": "60"}, {"due_date": "2026-09-30", "percent": "40"}],
    )
    assert job["status"] == "SUCCEEDED" and job["processed_items"] == 6
    page = (await client.get(f"{API}/invoices?term_id={TERM2}", headers=bursar)).json()["items"]
    by_student = {i["student_id"]: i for i in page}
    assert by_student[str(u(6, 11))]["total_tzs"] == "630000.00"  # no yearly line on Term Two
    assert by_student[str(u(6, 13))]["total_tzs"] == "585000.00"  # sibling 10% of tuition
    assert by_student[str(u(6, 16))]["balance_tzs"] == "610000.00"  # 20,000 credit applied
    detail = await invoice(client, bursar, by_student[str(u(6, 11))]["id"])
    assert [(i["seq"], i["amount_tzs"]) for i in detail["installments"]] == [(1, "378000.00"), (2, "252000.00")]
    await assert_books_balance(db)

    again = await _generate(
        client, bursar, dispatcher, "invoice-run-term2b", term_id=str(TERM2), class_ids=[str(F2)], due_date="2026-08-15"
    )
    assert again["status"] == "SUCCEEDED" and again["processed_items"] == 0  # nobody billed twice
    missing = await _generate(
        client, bursar, dispatcher, "invoice-run-f5", term_id=str(TERM2), class_ids=[str(F5)], due_date="2026-08-15"
    )
    assert missing["status"] == "FAILED"  # no approved structure for Form V: nothing is billed
    assert len((await client.get(f"{API}/invoices?term_id={TERM2}", headers=bursar)).json()["items"]) == 6


async def test_invoice_access_pdf_and_cancel(client, db, admin, bursar, dispatcher):
    paid = await client.post(f"{API}/invoices/{INV[12]}/cancel", headers=bursar, json={"reason": "Wrong class billed"})
    assert paid.status_code == 409  # has payments
    cancelled = await client.post(
        f"{API}/invoices/{INV[15]}/cancel", headers=bursar, json={"reason": "Student left before term"}
    )
    assert cancelled.status_code == 200, cancelled.text
    assert cancelled.json()["status"] == "CANCELLED"
    await assert_books_balance(db)
    pdf = await client.get(f"{API}/invoices/{INV[11]}/pdf?lang=sw", headers=bursar)
    assert pdf.status_code == 200 and pdf.content.startswith(b"%PDF")
    father = await parent_login(client, db, dispatcher, SCHOOL_A, u(2, 21), "255754000021")
    assert (await client.get(f"{API}/invoices/{INV[11]}", headers=father)).status_code == 200
    assert (await client.get(f"{API}/invoices/{INV[12]}", headers=father)).status_code == 404
    statement = (await client.get(f"{API}/students/{u(6, 11)}/statement", headers=father)).json()
    assert statement["outstanding_tzs"] == "0.00" and len(statement["payments"]) == 2
    teacher = bearer(await login(client, username="tch.salma"))
    assert (await client.get(f"{API}/invoices", headers=teacher)).status_code == 403


# ---------------------------------------------------------------- payments


async def _cash(client, headers, ref, amount, student=u(6, 12), **extra):
    return await client.post(
        f"{API}/payments",
        headers={**headers, "Idempotency-Key": f"cash-{ref}"},
        json={
            "student_id": str(student),
            "channel": "CASH",
            "external_ref": ref,
            "amount_tzs": amount,
            "payer_name": "Mwanaisha Hassan",
            "received_at": "2026-02-20T10:00:00+03:00",
            **extra,
        },
    )


async def test_cash_payment_allocates_issues_receipt_and_keeps_credit(client, db, bursar):
    response = await _cash(client, bursar, "RCT-BOOK-0002", "500000", payer_phone="0715000022")
    assert response.status_code == 201, response.text
    payment = response.json()
    assert payment["allocated_tzs"] == "480000.00" and payment["receipt"]["receipt_no"].startswith("RCT-2026-")
    assert (await invoice(client, bursar, INV[12]))["status"] == "FULLY_PAID"
    statement = (await client.get(f"{API}/students/{u(6, 12)}/statement", headers=bursar)).json()
    assert statement["credit_tzs"] == "20000.00"
    await assert_books_balance(db)

    replay = await _cash(client, bursar, "RCT-BOOK-0002", "500000", payer_phone="0715000022")
    assert replay.status_code == 201 and replay.json()["id"] == payment["id"]  # same Idempotency-Key
    duplicate = await client.post(
        f"{API}/payments",
        headers={**bursar, "Idempotency-Key": "another-key-1"},
        json={
            "student_id": str(u(6, 12)),
            "channel": "CASH",
            "external_ref": "RCT-BOOK-0002",
            "amount_tzs": "1",
            "received_at": "2026-02-20T10:00:00+03:00",
        },
    )
    assert duplicate.status_code == 409
    mobile = await client.post(
        f"{API}/payments",
        headers={**bursar, "Idempotency-Key": "another-key-2"},
        json={
            "student_id": str(u(6, 12)),
            "channel": "MPESA",
            "external_ref": "X1",
            "amount_tzs": "1",
            "received_at": "2026-02-20T10:00:00+03:00",
        },
    )
    assert mobile.status_code == 422
    receipt = await client.get(f"{API}/payments/{payment['id']}/receipt?lang=en", headers=bursar)
    assert receipt.status_code == 200 and receipt.content.startswith(b"%PDF")


async def test_receipt_sms_goes_to_consenting_guardian(client, db, bursar, dispatcher):
    await rekey_phone(db, SCHOOL_A, u(2, 22), "255715000022")
    response = await _cash(client, bursar, "RCT-BOOK-0003", "100000")
    assert response.status_code == 201
    [call] = dispatcher.take("sms.send")
    await as_school(db, SCHOOL_A)
    body = (await db.execute(select(SmsMessage.body).where(SmsMessage.id == call["sms_id"]))).scalar()
    assert "TZS 100,000" in body and response.json()["receipt"]["receipt_no"] in body and "380,000" in body


async def test_reversal_is_maker_checker(client, db, admin, bursar):
    payment = (await _cash(client, bursar, "RCT-BOOK-0004", "200000", student=u(6, 14))).json()
    request = await client.post(
        f"{API}/payments/{payment['id']}/reversal-requests", headers=bursar, json={"reason": "Cash was counterfeit"}
    )
    assert request.status_code == 201 and request.json()["status"] == "PENDING"
    again = await client.post(
        f"{API}/payments/{payment['id']}/reversal-requests", headers=bursar, json={"reason": "Second request"}
    )
    assert again.status_code == 409
    assert (
        await client.post(f"{API}/reversal-requests/{request.json()['id']}/approve", headers=bursar, json={})
    ).status_code == 403  # no approve permission
    approved = await client.post(
        f"{API}/reversal-requests/{request.json()['id']}/approve", headers=admin, json={"note": "Checked with the bank"}
    )
    assert approved.status_code == 200 and approved.json()["status"] == "APPROVED"
    assert (await client.get(f"{API}/payments/{payment['id']}", headers=bursar)).json()["status"] == "REVERSED"
    assert (await invoice(client, bursar, INV[14]))["balance_tzs"] == "380000.00"
    await assert_books_balance(db)

    own = (await _cash(client, admin, "RCT-BOOK-0005", "1000", student=u(6, 14))).json()
    own_request = await client.post(
        f"{API}/payments/{own['id']}/reversal-requests", headers=admin, json={"reason": "Typo in amount"}
    )
    self_approval = await client.post(
        f"{API}/reversal-requests/{own_request.json()['id']}/approve", headers=admin, json={}
    )
    assert self_approval.status_code == 403 and self_approval.json()["details"][0]["code"] == "maker_checker"
    pending = (await client.get(f"{API}/reversal-requests?status=PENDING", headers=admin)).json()
    assert [r["id"] for r in pending] == [own_request.json()["id"]]


async def test_bank_deposit_confirmed_by_bank_officer(client, db, bursar):
    submitted = await client.post(
        f"{API}/bank-deposits",
        headers=bursar,
        json={
            "bank_reference": "NMB-2026-55001",
            "deposit_date": "2026-02-18",
            "amount_tzs": "250000",
            "student_id": str(u(6, 15)),
            "depositor_name": "Fatuma Kombo",
        },
    )
    assert submitted.status_code == 201
    officer = bearer(await login(client, username="bank.grace"))
    waiting = (await client.get(f"{API}/bank-deposits?status=SUBMITTED", headers=officer)).json()
    assert [d["bank_reference"] for d in waiting] == ["NMB-2026-55001"]
    assert (
        await client.post(f"{API}/bank-deposits/{submitted.json()['id']}/confirm", headers=bursar, json={})
    ).status_code == 403
    confirmed = await client.post(
        f"{API}/bank-deposits/{submitted.json()['id']}/confirm", headers=officer, json={"note": "Seen on statement"}
    )
    assert confirmed.status_code == 200 and confirmed.json()["status"] == "MATCHED"
    assert (await invoice(client, bursar, INV[15]))["paid_tzs"] == "250000.00"
    await assert_books_balance(db)
    duplicate = await client.post(
        f"{API}/bank-deposits",
        headers=bursar,
        json={
            "bank_reference": "NMB-2026-55001",
            "deposit_date": "2026-02-18",
            "amount_tzs": "1",
            "student_id": str(u(6, 15)),
        },
    )
    assert duplicate.status_code == 409


# ---------------------------------------------------------------- GePG and mobile money


async def test_gepg_control_number_and_signed_payment(client, db, bursar, dispatcher, gepg_keys):
    as_gepg, our_public = gepg_keys
    requested = await client.post(f"{API}/invoices/{INV[14]}/control-number", headers=bursar)
    assert requested.status_code == 202 and requested.json()["status"] == "REQUESTED"
    assert (await client.post(f"{API}/invoices/{INV[14]}/control-number", headers=bursar)).status_code == 409
    [call] = dispatcher.take("gepg.submit")
    assert await gepg.submit(**call) == "issued"  # simulator answers at once
    control = (await invoice(client, bursar, INV[14]))["control_number"]
    assert control and len(control) == 12

    notice = as_gepg(
        "gepgPmtSpInfo",
        {
            "PymtTrxInf": {
                "TrxId": "GEPG-TRX-1",
                "PayRefId": "PSP-99000001",
                "PayCtrNum": control,
                "BillAmt": "380000.00",
                "PaidAmt": "380000.00",
                "TrxDtTm": "2026-03-01T10:15:00",
                "PyrName": "Saidi Swai",
                "PyrCellNum": "255786000024",
            }
        },
    )
    response = await client.post(f"{API}/webhooks/gepg/payment", content=notice)
    assert response.status_code == 200
    ack = response.content
    inner = ack.split(b"<gepgSignature>")[0].removeprefix(b"<Gepg>")
    signature = base64.b64decode(ack.split(b"<gepgSignature>")[1].split(b"</gepgSignature>")[0])
    our_public.verify(signature, inner, padding.PKCS1v15(), hashes.SHA256())  # ACK signed by us
    assert b"7101" in ack
    [process] = dispatcher.take("payments.process")
    await payment_service.run_processing(**process)
    assert (await invoice(client, bursar, INV[14]))["status"] == "FULLY_PAID"
    await as_school(db, SCHOOL_A)
    assert (await db.execute(select(GepgBill.status).where(GepgBill.control_number == control))).scalar() == "PAID"
    await assert_books_balance(db)

    replay = await client.post(f"{API}/webhooks/gepg/payment", content=notice)
    assert replay.status_code == 200 and dispatcher.take("payments.process") == []  # idempotent
    tampered = notice.replace(b"380000.00</PaidAmt>", b"999000.00</PaidAmt>")
    assert (await client.post(f"{API}/webhooks/gepg/payment", content=tampered)).status_code == 401
    evil = b'<!DOCTYPE x [<!ENTITY a "b">]>' + notice
    assert (await client.post(f"{API}/webhooks/gepg/payment", content=evil)).status_code == 401


def _signed(payload: dict, secret: str) -> tuple[bytes, dict]:
    body = json.dumps(payload).encode()
    return body, {
        "X-SSMS-Signature": "sha256=" + hmac.new(secret.encode(), body, hashlib.sha256).hexdigest(),
        "Content-Type": "application/json",
    }


async def test_mobile_money_callbacks(client, db, bursar, dispatcher, monkeypatch):
    secret = "m" * 40
    monkeypatch.setattr(get_settings(), "mobile_webhook_secret", secret)
    body, headers = _signed(
        {
            "transaction_id": "QLM5TEST01",
            "reference": "mfano-sec.MF-2025-0035",
            "amount": "150000",
            "msisdn": "255786000024",
            "payer_name": "Saidi Swai",
            "timestamp": "2026-03-02T08:00:00",
        },
        secret,
    )
    accepted = (await client.post(f"{API}/webhooks/mpesa", content=body, headers=headers)).json()
    assert accepted["status"] == "ACCEPTED"
    for call in dispatcher.take("payments.process"):
        await payment_service.run_processing(**call)
    assert (await invoice(client, bursar, INV[14]))["balance_tzs"] == "230000.00"
    duplicate = (await client.post(f"{API}/webhooks/mpesa", content=body, headers=headers)).json()
    assert duplicate["status"] == "DUPLICATE"
    unknown_body, unknown_headers = _signed(
        {"transaction_id": "QLM5TEST02", "reference": "mfano-sec.XX-0000-0000", "amount": "1000"}, secret
    )
    assert (await client.post(f"{API}/webhooks/airtel", content=unknown_body, headers=unknown_headers)).json() == {
        "status": "REJECTED",
        "reason": "unknown_reference",
    }
    assert (
        await client.post(f"{API}/webhooks/mpesa", content=body, headers={**headers, "X-SSMS-Signature": "sha256=00"})
    ).status_code == 401
    await assert_books_balance(db)


async def test_push_prompt_for_own_child(client, db, dispatcher):
    father = await parent_login(client, db, dispatcher, SCHOOL_A, u(2, 23), "255765000023")  # Baraka's father
    sent = await client.post(
        f"{API}/payments/push",
        headers=father,
        json={"invoice_id": str(INV[13]), "phone": "0765000023", "channel": "MPESA"},
    )
    assert sent.status_code == 202 and sent.json()["reference"] == "mfano-sec.MF-2025-0031"
    other = await client.post(
        f"{API}/payments/push",
        headers=father,
        json={"invoice_id": str(INV[12]), "phone": "0765000023", "channel": "MPESA"},
    )
    assert other.status_code == 404


# ---------------------------------------------------------------- reconciliation, reports, reminders


async def test_reconciliation(client, bursar):
    statement = b"external_ref,amount\nQKJ7H2LM9P,280000\nQKX9NOTINSYS,5000\n"
    run = await client.post(
        f"{API}/reconciliation-runs",
        headers=bursar,
        data={"run_date": "2026-01-25", "channel": "MPESA"},
        files={"file": ("mpesa.csv", statement)},
    )
    assert run.status_code == 201, run.text
    body = run.json()
    assert body["status"] == "EXCEPTIONS" and body["matched_count"] == 1 and body["exception_count"] == 1
    assert {i["status"] for i in body["items"]} == {"MATCHED", "MISSING_IN_SYSTEM"}
    again = await client.post(
        f"{API}/reconciliation-runs",
        headers=bursar,
        data={"run_date": "2026-01-25", "channel": "MPESA"},
        files={"file": ("m.csv", statement)},
    )
    assert again.status_code == 409
    item = next(i for i in body["items"] if i["status"] == "MISSING_IN_SYSTEM")
    resolved = await client.patch(
        f"{API}/reconciliation-items/{item['id']}", headers=bursar, json={"note": "Belongs to another school's paybill"}
    )
    assert resolved.json()["resolved_by"]
    balanced = await client.post(
        f"{API}/reconciliation-runs",
        headers=bursar,
        data={"run_date": "2026-01-30", "channel": "AIRTEL"},
        files={"file": ("a.csv", b"external_ref,amount\nMP260130.0912.A11,700000\n")},
    )
    assert balanced.json()["status"] == "BALANCED"


async def test_reports(client, bursar):
    aging = (await client.get(f"{API}/reports/fees/aging", headers=bursar)).json()
    assert aging["summary"]["90+"]["count"] >= 1
    defaulters = (await client.get(f"{API}/reports/fees/defaulters?class_id={F2}", headers=bursar)).json()["rows"]
    assert {r["admission_no"] for r in defaulters} >= {"MF-2025-0027", "MF-2025-0031"}
    collections = (
        await client.get(f"{API}/reports/fees/collections?from=2026-01-01&to=2026-01-31", headers=bursar)
    ).json()
    assert (
        collections["by_channel"]["GEPG"] == "400000.00" and collections["total_tzs"] == "1580000.00"
    )  # reversed M-Pesa excluded
    xlsx = await client.get(f"{API}/reports/fees/defaulters?format=xlsx", headers=bursar)
    assert xlsx.content[:2] == b"PK"


async def test_overdue_reminders_once(client, db, admin, dispatcher):
    await rekey_phone(db, SCHOOL_A, u(2, 24), "255786000024")  # Rehema Swai's father
    first = (await client.post(f"{API}/fees/reminders/run", headers=admin)).json()
    assert first["queued"] == 2  # installments 2 and 3 (the first is covered by the payment)
    second = (await client.post(f"{API}/fees/reminders/run", headers=admin)).json()
    assert second["queued"] == 0
    await as_school(db, SCHOOL_A)
    count = (await db.execute(text("SELECT count(*) FROM sms_messages WHERE template_key = 'fee_reminder'"))).scalar()
    assert count == 2
    assert await fee_reports.fanout(str(date.today())) == "2 schools"
    assert len(dispatcher.take("reminders.run")) == 2


async def test_payments_are_immutable_in_the_database(db):
    await as_school(db, SCHOOL_A)
    payment = (await db.execute(select(Payment).where(Payment.external_ref == "RCT-BOOK-0001"))).scalar_one()
    payment.amount_tzs = payment.amount_tzs + 1
    with pytest.raises(Exception, match="immutable"):
        await db.flush()


async def test_control_number_arrives_by_signed_callback(client, bursar, dispatcher, gepg_keys, monkeypatch):
    """Live mode: the request is sent and GePG answers later through /webhooks/gepg/bill."""
    as_gepg, _ = gepg_keys
    requested = (await client.post(f"{API}/invoices/{INV[13]}/control-number", headers=bursar)).json()
    dispatcher.take("gepg.submit")
    refused = as_gepg(
        "gepgBillSubResp", {"BillTrxInf": {"BillId": requested["bill_ref"], "TrxSts": "GF", "TrxStsCode": "7201"}}
    )
    assert (await client.post(f"{API}/webhooks/gepg/bill", content=refused)).status_code == 200
    assert (await invoice(client, bursar, INV[13]))["control_number"] is None
    retry = (await client.post(f"{API}/invoices/{INV[13]}/control-number", headers=bursar)).json()
    assert retry["bill_ref"].endswith("-2")  # a failed bill frees the invoice
    issued = as_gepg(
        "gepgBillSubResp",
        {
            "BillTrxInf": {
                "BillId": retry["bill_ref"],
                "TrxSts": "GS",
                "PayCntrNum": "991234567890",
                "TrxStsCode": "7101",
            }
        },
    )
    response = await client.post(f"{API}/webhooks/gepg/bill", content=issued)
    assert response.status_code == 200 and b"gepgBillSubRespAck" in response.content
    assert (await invoice(client, bursar, INV[13]))["control_number"] == "991234567890"
    assert (await client.post(f"{API}/webhooks/gepg/bill", content=issued)).status_code == 200  # replay: no change


def test_amounts_in_words():
    from decimal import Decimal

    from app.services.ledger import in_words, tzs

    assert in_words(Decimal("400000"), "sw") == "Shilingi laki nne tu"
    assert in_words(Decimal("680000"), "sw") == "Shilingi laki sita na elfu themanini tu"
    assert in_words(Decimal("1250500"), "sw") == "Shilingi milioni moja, laki mbili na elfu hamsini na mia tano tu"
    assert in_words(Decimal("12.50"), "sw") == "Shilingi kumi na mbili na senti hamsini tu"
    assert in_words(Decimal("680000"), "en") == "Six hundred and eighty thousand shillings only"
    assert (
        in_words(Decimal("1250500"), "en") == "One million, two hundred and fifty thousand, five hundred shillings only"
    )
    assert tzs(Decimal("680000.00")) == "680,000" and tzs(Decimal("12.50")) == "12.50"


async def test_parent_sees_own_children(client, db, dispatcher):
    father = await parent_login(client, db, dispatcher, SCHOOL_A, u(2, 21), "255754000021")  # John Massawe
    kids = (await client.get(f"{API}/me/children", headers=father)).json()
    assert [k["admission_no"] for k in kids] == ["MF-2025-0014"]
    assert kids[0]["outstanding_tzs"] == "0.00" and kids[0]["class_code"] == "F2"
