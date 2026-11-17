"""SSMS API application factory."""

import asyncio
import sys

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api import health
from app.api.router import api_router
from app.core.config import get_settings
from app.core.errors import register_error_handlers
from app.core.middleware import RequestContextMiddleware
from app.core.observability import configure_logging, init_sentry

if sys.platform == "win32":  # psycopg async cannot use the Proactor loop
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())


def create_app() -> FastAPI:
    settings = get_settings()
    configure_logging(settings.log_format or ("json" if settings.is_production else "text"))
    init_sentry(settings.sentry_dsn, settings.environment, settings.sentry_traces_sample_rate)
    app = FastAPI(
        title="SSMS API",
        version="1.0.0",
        description="Smart School Management System (Tanzania), multi-tenant. Errors always use "
        "`{error_code, message, details}`; messages follow `Accept-Language` (sw default, en).",
        docs_url=None if settings.is_production else "/docs",
        redoc_url=None,
    )
    register_error_handlers(app)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_credentials=True,
        allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE"],
        allow_headers=[
            "Authorization",
            "Content-Type",
            "Accept-Language",
            "Idempotency-Key",
            "X-Request-ID",
            "X-Academic-Year",
        ],
        expose_headers=["X-Request-ID", "Retry-After", "Content-Disposition"],
        max_age=600,
    )
    app.add_middleware(RequestContextMiddleware, hsts=settings.is_production)
    app.include_router(health.router)
    app.include_router(api_router, prefix="/api/v1")
    return app


app = create_app()
