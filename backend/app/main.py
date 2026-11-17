"""FastAPI application. Interactive docs: /docs (Swagger UI) and /redoc."""
import uuid

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware

from app.core.config import get_settings
from app.core.errors import register_error_handlers
from app.routers import auth, courses, enrolments, instructors, schedules, students, transactions

API_PREFIX = "/api/v1"


def create_app() -> FastAPI:
    settings = get_settings()
    app = FastAPI(
        title="School Management System API",
        description="Mfumo wa Usimamizi wa Shule — students, courses, instructors, schedules, "
                    "enrolment and transactions (TZS, GePG, mobile money).",
        version="1.0.0",
        docs_url="/docs",
        openapi_url=f"{API_PREFIX}/openapi.json",
    )
    app.add_middleware(CORSMiddleware, allow_origins=settings.cors_origins, allow_credentials=True,
                       allow_methods=["*"], allow_headers=["*"])

    @app.middleware("http")
    async def request_id_and_headers(request: Request, call_next):
        incoming = request.headers.get("X-Request-ID", "")
        try:
            request.state.request_id = str(uuid.UUID(incoming))
        except ValueError:
            request.state.request_id = str(uuid.uuid4())
        response = await call_next(request)
        response.headers["X-Request-ID"] = request.state.request_id
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Referrer-Policy"] = "no-referrer"
        return response

    register_error_handlers(app)
    for module in (auth, students, courses, instructors, schedules, enrolments, transactions):
        app.include_router(module.router, prefix=API_PREFIX)

    @app.get("/health", tags=["Health"])
    def health():
        return {"status": "ok"}

    return app


app = create_app()
