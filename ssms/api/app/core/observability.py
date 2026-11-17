"""Observability (NFR-13): Prometheus metrics, optional Sentry error reporting, JSON logs.

Metrics are labelled by route template (never by raw path, so ids do not explode the series) and by status code.
With several uvicorn workers set PROMETHEUS_MULTIPROC_DIR (an empty, writable directory) so /metrics adds up every
worker. /metrics is served by the API process only on its internal port: the web container's Nginx does not proxy
it, and SSMS_METRICS_TOKEN can require a bearer token as well. Sentry is off unless SSMS_SENTRY_DSN is set; it never
sends request bodies, cookies or authorization headers (personal data stays in the school's systems).
"""

import json
import logging
import os

from prometheus_client import CONTENT_TYPE_LATEST, CollectorRegistry, Counter, Histogram, generate_latest, multiprocess

REQUESTS = Counter("ssms_http_requests_total", "HTTP requests", ["method", "route", "status"])
LATENCY = Histogram(
    "ssms_http_request_seconds",
    "HTTP request duration",
    ["method", "route"],
    buckets=(0.025, 0.05, 0.1, 0.2, 0.3, 0.5, 0.8, 1.0, 2.0, 5.0, 10.0),
)
SKIP = ("/metrics", "/health/live", "/health/ready")


def observe(scope: dict, status: int, seconds: float) -> None:
    if scope["path"] in SKIP:
        return
    route = getattr(scope.get("route"), "path", None) or "unmatched"
    REQUESTS.labels(scope["method"], route, str(status)).inc()
    LATENCY.labels(scope["method"], route).observe(seconds)


def metrics_payload() -> tuple[bytes, str]:
    if os.environ.get("PROMETHEUS_MULTIPROC_DIR"):
        registry = CollectorRegistry()
        multiprocess.MultiProcessCollector(registry)
        return generate_latest(registry), CONTENT_TYPE_LATEST
    return generate_latest(), CONTENT_TYPE_LATEST


SENSITIVE_HEADERS = {"authorization", "cookie", "x-ssms-signature", "x-device-key", "idempotency-key"}


def _scrub(event: dict, _hint: dict) -> dict:
    request = event.get("request") or {}
    request.pop("data", None)
    request.pop("cookies", None)
    request.pop("query_string", None)
    headers = request.get("headers") or {}
    for name in list(headers):
        if name.lower() in SENSITIVE_HEADERS:
            headers[name] = "[removed]"
    event.pop("user", None)
    return event


def init_sentry(dsn: str, environment: str, traces_sample_rate: float) -> bool:
    if not dsn:
        return False
    import sentry_sdk  # noqa: PLC0415 - only loaded when error reporting is switched on

    sentry_sdk.init(
        dsn=dsn,
        environment=environment,
        traces_sample_rate=traces_sample_rate,
        send_default_pii=False,
        max_request_body_size="never",
        before_send=_scrub,
    )
    return True


class JsonFormatter(logging.Formatter):
    """One JSON object per line: time, level, logger, message (and the exception, if any)."""

    def format(self, record: logging.LogRecord) -> str:
        entry = {
            "ts": self.formatTime(record, "%Y-%m-%dT%H:%M:%S%z"),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }
        if record.exc_info:
            entry["exc"] = self.formatException(record.exc_info)
        return json.dumps(entry, ensure_ascii=False)


def configure_logging(fmt: str) -> None:
    handler = logging.StreamHandler()
    handler.setFormatter(
        JsonFormatter() if fmt == "json" else logging.Formatter("%(asctime)s %(levelname)s %(name)s %(message)s")
    )
    root = logging.getLogger()
    root.handlers[:] = [handler]
    root.setLevel(logging.INFO)
