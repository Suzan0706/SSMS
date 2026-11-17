"""Request context (pure ASGI, no body buffering): request id, language, security headers, access log, metrics."""

import logging
import re
import time

from starlette.datastructures import Headers, MutableHeaders
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from app.core.i18n import pick_language
from app.core.ids import uuid7
from app.core.observability import observe

log = logging.getLogger("ssms.access")
_REQUEST_ID = re.compile(r"^[A-Za-z0-9-]{8,64}$")
_DOC_PATHS = ("/docs", "/redoc", "/openapi.json")


class RequestContextMiddleware:
    def __init__(self, app: ASGIApp, hsts: bool = False):
        self.app = app
        self.hsts = hsts

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        headers = Headers(scope=scope)
        incoming = headers.get("x-request-id", "")
        request_id = incoming if _REQUEST_ID.match(incoming) else str(uuid7())
        state = scope.setdefault("state", {})
        state["request_id"] = request_id
        state["lang"] = pick_language(headers.get("accept-language"))
        state["lang_explicit"] = "accept-language" in headers  # else the user's preference applies
        started = time.perf_counter()
        status = 500
        is_docs = scope["path"].startswith(_DOC_PATHS)

        async def send_with_headers(message: Message) -> None:
            nonlocal status
            if message["type"] == "http.response.start":
                status = message["status"]
                out = MutableHeaders(scope=message)
                out["X-Request-ID"] = request_id
                out["X-Content-Type-Options"] = "nosniff"
                out["X-Frame-Options"] = "DENY"
                out["Referrer-Policy"] = "no-referrer"
                if not is_docs:
                    out["Content-Security-Policy"] = "default-src 'none'; frame-ancestors 'none'"
                    out.setdefault("Cache-Control", "no-store")  # responses carry personal data
                if self.hsts:
                    out["Strict-Transport-Security"] = "max-age=31536000; includeSubDomains"
            await send(message)

        try:
            await self.app(scope, receive, send_with_headers)
        finally:
            elapsed = time.perf_counter() - started
            observe(scope, status, elapsed)
            log.info("%s %s %s %.1fms rid=%s", scope["method"], scope["path"], status, elapsed * 1000, request_id)
