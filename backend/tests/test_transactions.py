from decimal import Decimal

import pytest
from sqlalchemy import func, select, text
from sqlalchemy.exc import DBAPIError

from app.integrations import gepg
from app.models import Transaction
from tests.conftest import login

API = "/api/v1"

# Seed: invoice 2 (student 2, Zawadi) totals 680,000 with a 200,000 cash payment (trans 3).


def test_manual_payment_updates_balance(client, as_bursar):
    r = client.post(f"{API}/transactions", headers=as_bursar, json={
        "student_id": 2, "invoice_id": 2, "amount_tzs": "100000", "payment_method": "MPESA",
        "reference_no": "RKT55XQ1ZP", "payer_name": "Mwanaisha Hassan", "payer_phone": "0715 000 011"})
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["transaction"]["trans_no"].startswith("TXN-")
    assert body["transaction"]["payer_phone"] == "255715000011"
    assert Decimal(body["invoice"]["balance_tzs"]) == Decimal("380000")
    assert body["invoice"]["payment_status"] == "PARTIALLY_PAID"


def test_same_reference_cannot_be_posted_twice(client, as_bursar):
    r = client.post(f"{API}/transactions", headers=as_bursar, json={
        "student_id": 1, "invoice_id": 1, "amount_tzs": "1000", "payment_method": "MPESA",
        "reference_no": "QKJ7H2LM9P"})                      # already in the seed
    assert r.status_code == 409
    assert r.json()["detail"]["constraint"] == "uq_trans_reference"


def test_payment_against_another_students_invoice_is_rejected(client, as_bursar):
    r = client.post(f"{API}/transactions", headers=as_bursar, json={
        "student_id": 1, "invoice_id": 2, "amount_tzs": "5000", "payment_method": "CASH"})
    assert r.status_code == 422


def test_non_cash_payment_needs_reference(client, as_bursar):
    r = client.post(f"{API}/transactions", headers=as_bursar, json={
        "student_id": 2, "invoice_id": 2, "amount_tzs": "5000", "payment_method": "BANK"})
    assert r.status_code == 422


def test_reversal_restores_balance_once(client, as_admin, db):
    r = client.post(f"{API}/transactions/3/reverse", headers=as_admin, json={"reason": "Cash counted twice"})
    assert r.status_code == 201, r.text
    assert r.json()["trans_type"] == "REVERSAL" and r.json()["reverses_trans_id"] == 3
    balance = db.execute(text("SELECT balance_tzs FROM v_invoice_balances WHERE invoice_id = 2")).scalar_one()
    assert balance == Decimal("680000")
    again = client.post(f"{API}/transactions/3/reverse", headers=as_admin, json={"reason": "Second attempt"})
    assert again.status_code == 409


def test_bursar_cannot_reverse(client, as_bursar):
    assert client.post(f"{API}/transactions/3/reverse", headers=as_bursar,
                       json={"reason": "Not allowed"}).status_code == 403


def test_ledger_rows_cannot_be_edited_or_deleted(db):
    with pytest.raises(DBAPIError, match="immutable"):
        with db.begin_nested():
            db.execute(text("UPDATE transactions SET amount_tzs = 1 WHERE trans_id = 1"))
    with pytest.raises(DBAPIError, match="append-only"):
        with db.begin_nested():
            db.execute(text("DELETE FROM transactions WHERE trans_id = 1"))


GEPG_XML = b"""<Gepg><gepgPmtSpInfo><PymtTrxInf><TrxId>9912345</TrxId><SpCode>SP101</SpCode>
<PayRefId>INV-2026-000002</PayRefId><BillId>2</BillId><PayCtrNum>994120000002</PayCtrNum>
<BillAmt>680000</BillAmt><PaidAmt>50000</PaidAmt><CCy>TZS</CCy><TrxDtTm>2026-03-02T10:15:00</TrxDtTm>
<UsdPayChnl>MPESA</UsdPayChnl><PyrCellNum>0715000011</PyrCellNum><PyrName>Mwanaisha Hassan</PyrName>
<PspReceiptNumber>PSP-88812</PspReceiptNumber></PymtTrxInf></gepgPmtSpInfo>
<gepgSignature>c2lnbmF0dXJl</gepgSignature></Gepg>"""


def test_gepg_callback_is_idempotent(client, db, monkeypatch):
    monkeypatch.setattr(gepg, "verify_signature", lambda signed, signature: None)
    for _ in range(2):                                    # GePG retries the same notification
        r = client.post(f"{API}/payments/gepg/callback", content=GEPG_XML,
                        headers={"Content-Type": "application/xml"})
        assert r.status_code == 200
        assert b"<TrxStsCode>7101</TrxStsCode>" in r.content
    rows = db.scalar(select(func.count()).select_from(Transaction).where(Transaction.reference_no == "PSP-88812"))
    assert rows == 1
    trans = db.scalar(select(Transaction).where(Transaction.reference_no == "PSP-88812"))
    assert trans.source == "GEPG" and trans.payer_phone == "255715000011" and trans.recorded_by is None


def test_gepg_callback_with_bad_signature_is_401(client, monkeypatch):
    def reject(signed, signature):
        raise gepg.SignatureError("bad")
    monkeypatch.setattr(gepg, "verify_signature", reject)
    r = client.post(f"{API}/payments/gepg/callback", content=GEPG_XML)
    assert r.status_code == 401


def test_parent_statement_only_for_own_child(client):
    headers = login(client, "p.hassan")
    r = client.get(f"{API}/students/2/statement", headers=headers)
    assert r.status_code == 200
    assert Decimal(r.json()["total_balance_tzs"]) == Decimal("480000")
    assert client.get(f"{API}/students/1/statement", headers=headers).status_code == 404
