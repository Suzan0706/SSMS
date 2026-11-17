"""Metrics endpoint, JSON log format and the Sentry scrubber (NFR-13)."""

import json
import logging

from app.core.config import get_settings
from app.core.observability import JsonFormatter, _scrub
from tests.helpers import u

API = "/api/v1"


async def test_metrics_use_route_templates_and_can_require_a_token(client, monkeypatch):
    await client.get(f"{API}/students/{u(6, 11)}")  # 401 without a token, still counted
    body = (await client.get("/metrics")).text
    assert 'route="/students/{student_id}"' in body and "ssms_http_request_seconds_bucket" in body
    assert str(u(6, 11)) not in body  # never the raw path
    monkeypatch.setattr(get_settings(), "metrics_token", "m" * 32)
    assert (await client.get("/metrics")).status_code == 401
    assert (await client.get("/metrics", headers={"Authorization": f"Bearer {'m' * 32}"})).status_code == 200


def test_json_log_lines():
    record = logging.LogRecord("ssms.access", logging.INFO, __file__, 1, "GET %s 200", ("/health/live",), None)
    line = json.loads(JsonFormatter().format(record))
    assert line["level"] == "INFO" and line["message"] == "GET /health/live 200" and line["logger"] == "ssms.access"


def test_sentry_events_lose_personal_data():
    event = {
        "request": {
            "headers": {"Authorization": "Bearer x", "X-SSMS-Signature": "sha256=y", "Accept": "application/json"},
            "data": {"phone": "0754000000"},
            "cookies": {"ssms_rt": "z"},
            "query_string": "q=Amani",
        },
        "user": {"id": "1"},
    }
    out = _scrub(event, {})
    assert out["request"]["headers"] == {
        "Authorization": "[removed]",
        "X-SSMS-Signature": "[removed]",
        "Accept": "application/json",
    }
    assert "data" not in out["request"] and "cookies" not in out["request"] and "query_string" not in out["request"]
    assert "user" not in out
