import hmac

from fastapi import APIRouter, Header, Response
from sqlalchemy import text

from app.core.config import get_settings
from app.core.errors import AppError
from app.core.observability import metrics_payload
from app.db.session import provider

router = APIRouter(tags=["health"])


@router.get("/health/live", summary="Process is up")
async def live() -> dict:
    return {"status": "ok"}


@router.get("/health/ready", summary="Database reachable")
async def ready() -> dict:
    async with provider.app() as session:
        await session.execute(text("SELECT 1"))
    return {"status": "ok"}


@router.get("/metrics", include_in_schema=False)
async def metrics(authorization: str | None = Header(default=None)) -> Response:
    """Prometheus scrape target; internal only (not proxied by Nginx), optionally token-protected."""
    token = get_settings().metrics_token
    if token and not hmac.compare_digest((authorization or "").encode(), f"Bearer {token}".encode()):
        raise AppError(401, "NOT_AUTHENTICATED")
    body, content_type = metrics_payload()
    return Response(body, media_type=content_type)
