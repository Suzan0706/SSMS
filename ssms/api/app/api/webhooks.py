"""Provider callbacks: no JWT. GePG messages are RSA-signed XML; mobile money is HMAC-signed JSON.
Nginx adds an IP allow-list per provider (design 15-security §15.6). Every handler is idempotent."""

import hmac
import json
import logging
from typing import Literal

from fastapi import APIRouter, Request, Response

from app.api.deps import client_ip
from app.core.config import get_settings
from app.core.ratelimit import enforce
from app.services import gepg, mobile, sms

log = logging.getLogger(__name__)
router = APIRouter(prefix="/webhooks", tags=["webhooks"])
XML = "application/xml"


async def _body(request: Request) -> bytes:
    await enforce(f"webhook:{client_ip(request)}", get_settings().webhook_requests_per_minute, 60)
    return await request.body()


@router.post("/gepg/bill", response_class=Response, summary="Control-number response (signed XML)")
async def gepg_bill(request: Request):
    try:
        fields = gepg.parse(await _body(request), "gepgBillSubResp")
    except gepg.SignatureError:
        log.error("GePG bill callback refused (signature) from %s", client_ip(request))
        return Response(status_code=401)
    await gepg.bill_response(fields)
    return Response(gepg.ack("gepgBillSubRespAck"), media_type=XML)


@router.post("/gepg/payment", response_class=Response, summary="Payment notification (signed XML)")
async def gepg_payment(request: Request):
    try:
        fields = gepg.parse(await _body(request), "gepgPmtSpInfo")
    except gepg.SignatureError:
        log.error("GePG payment callback refused (signature) from %s", client_ip(request))
        return Response(status_code=401)
    await gepg.payment_notification(fields)
    return Response(gepg.ack("gepgPmtSpInfoAck"), media_type=XML)


@router.post(
    "/sms/{provider}",
    status_code=204,
    summary="SMS delivery reports (?token=<SSMS_SMS_WEBHOOK_SECRET>); formats VERIFY with Beem/NextSMS",
)
async def sms_reports(provider: Literal["beem", "nextsms", "console"], token: str, request: Request):
    secret = get_settings().sms_webhook_secret
    if not secret or not hmac.compare_digest(token.encode(), secret.encode()):
        log.error("SMS delivery report refused (token) from %s", client_ip(request))
        return Response(status_code=401)
    try:
        reports = sms.parse_reports(json.loads(await _body(request)))
    except ValueError:
        return Response(status_code=204)
    await sms.apply_reports(provider, reports)
    return Response(status_code=204)


@router.post("/{provider}", summary="Mobile-money payment (JSON, X-SSMS-Signature: sha256=<HMAC>)")
async def mobile_money(provider: Literal["mpesa", "tigopesa", "airtel", "halopesa"], request: Request):
    body = await _body(request)
    if not mobile.signature_ok(body, request.headers.get("x-ssms-signature")):
        log.error("mobile-money callback refused (signature) from %s", client_ip(request))
        return Response(status_code=401)
    try:
        return await mobile.callback(provider, body)
    except ValueError:
        return {"status": "REJECTED", "reason": "malformed"}
