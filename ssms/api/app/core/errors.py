"""One error format for every failure: {"error_code", "message", "details"}."""

import logging

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from sqlalchemy.exc import DBAPIError
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.core.i18n import MESSAGES, message

log = logging.getLogger(__name__)


class AppError(Exception):
    def __init__(
        self, status_code: int, error_code: str, details: list | None = None, headers: dict | None = None, **params
    ):
        self.status_code = status_code
        self.error_code = error_code
        self.details = details or []
        self.headers = headers
        self.params = params
        super().__init__(error_code)


def not_found() -> AppError:
    return AppError(404, "NOT_FOUND")


def forbidden() -> AppError:
    return AppError(403, "FORBIDDEN")


def lang_of(request: Request) -> str:
    return getattr(request.state, "lang", "sw")


def body(request: Request, error_code: str, details: list | None = None, **params) -> dict:
    return {
        "error_code": error_code,
        "message": message(error_code, lang_of(request), **params),
        "details": details or [],
    }


# PostgreSQL SQLSTATE -> (HTTP status, error_code)
_SQLSTATE = {
    "23505": (409, "DUPLICATE"),
    "23P01": (409, "TIMETABLE_CLASH"),
    "23503": (422, "INVALID_REFERENCE"),
    "23514": (422, "RULE_VIOLATION"),
    "23502": (422, "VALIDATION_ERROR"),
    "22P02": (422, "VALIDATION_ERROR"),
    "22001": (422, "VALIDATION_ERROR"),
    "42501": (404, "NOT_FOUND"),  # RLS / privilege: never reveal other schools' data
    "SS422": (422, "INCOMPLETE_GRADES_BLOCK"),
    "P0001": (409, "NOT_ALLOWED"),
    "P0002": (404, "NOT_FOUND"),
}

_HTTP_CODES = {
    401: "NOT_AUTHENTICATED",
    403: "FORBIDDEN",
    404: "NOT_FOUND",
    405: "NOT_ALLOWED",
    413: "FILE_TOO_LARGE",
    429: "RATE_LIMITED",
}

_FIELD_CODES = {
    "missing": "required",
    "string_too_long": "too_long",
    "value_error": "invalid_value",
}


def validation_details(errors: list[dict], lang: str, skip: int = 0) -> list[dict]:
    """Pydantic errors -> [{field, code, message}]. `skip` drops leading location parts such as "body"."""
    details = []
    for e in errors:
        field = ".".join(str(p) for p in e.get("loc", [])[skip:]) or "body"
        code = _FIELD_CODES.get(e.get("type", ""), "invalid_value")
        err = (e.get("ctx") or {}).get("error")  # validators raise ValueError("<message code>")
        if err is not None and str(err) in MESSAGES:
            code = str(err)
        details.append({"field": field, "code": code, "message": message(code, lang)})
    return details


def register_error_handlers(app: FastAPI) -> None:
    @app.exception_handler(AppError)
    async def _app_error(request: Request, exc: AppError):
        return JSONResponse(
            body(request, exc.error_code, exc.details, **exc.params), status_code=exc.status_code, headers=exc.headers
        )

    @app.exception_handler(RequestValidationError)
    async def _validation(request: Request, exc: RequestValidationError):
        details = validation_details(exc.errors(), lang_of(request), skip=1)
        return JSONResponse(body(request, "VALIDATION_ERROR", details), status_code=422)

    @app.exception_handler(StarletteHTTPException)
    async def _http_error(request: Request, exc: StarletteHTTPException):
        code = _HTTP_CODES.get(exc.status_code, "INTERNAL_ERROR" if exc.status_code >= 500 else "VALIDATION_ERROR")
        return JSONResponse(body(request, code), status_code=exc.status_code, headers=exc.headers)

    @app.exception_handler(Exception)
    async def _unexpected(request: Request, exc: Exception):
        log.exception("unhandled error", exc_info=exc)
        return JSONResponse(body(request, "INTERNAL_ERROR"), status_code=500)

    @app.exception_handler(DBAPIError)
    async def _db_error(request: Request, exc: DBAPIError):
        sqlstate = getattr(exc.orig, "sqlstate", None)
        if sqlstate not in _SQLSTATE:
            log.exception("unexpected database error", exc_info=exc)
            return JSONResponse(body(request, "INTERNAL_ERROR"), status_code=500)
        status, code = _SQLSTATE[sqlstate]
        diag = getattr(exc.orig, "diag", None)
        detail = {"constraint": getattr(diag, "constraint_name", None)}
        if sqlstate in ("P0001", "23514", "SS422"):
            detail["reason"] = getattr(diag, "message_primary", None)
        return JSONResponse(body(request, code, [detail], detail=detail.get("reason") or ""), status_code=status)
