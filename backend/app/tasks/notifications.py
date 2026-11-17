import logging

import httpx

from app.core.config import get_settings
from app.tasks.celery_app import celery_app

log = logging.getLogger(__name__)


@celery_app.task(bind=True, autoretry_for=(httpx.HTTPError,), retry_backoff=30, max_retries=3)
def send_sms(self, phone: str, message: str) -> str:
    """Send one SMS through the configured bulk-SMS provider (retried 3 times on network errors)."""
    settings = get_settings()
    if settings.sms_provider == "console":
        log.info("SMS to %s: %s", phone, message)
        return "logged"
    response = httpx.post(
        settings.sms_api_url,
        headers={"Authorization": f"Bearer {settings.sms_api_key}"},
        json={"source_addr": settings.sms_sender_id, "message": message,
              "recipients": [{"recipient_id": 1, "dest_addr": phone}]},
        timeout=15,
    )
    response.raise_for_status()
    return "sent"
