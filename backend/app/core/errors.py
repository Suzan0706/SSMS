"""Bilingual API errors and mapping of PostgreSQL errors to HTTP status codes."""
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from sqlalchemy.exc import DBAPIError


class AppError(Exception):
    def __init__(
        self,
        status_code: int,
        code: str,
        message_en: str,
        message_sw: str,
        extra: dict | None = None,
        headers: dict | None = None,
    ):
        self.status_code = status_code
        self.code = code
        self.message_en = message_en
        self.message_sw = message_sw
        self.extra = extra or {}
        self.headers = headers

    def body(self) -> dict:
        return {"detail": {"code": self.code, "message_en": self.message_en,
                           "message_sw": self.message_sw, **self.extra}}


def not_found(entity: str) -> AppError:
    return AppError(404, "NOT_FOUND", f"{entity} not found", f"{entity} haikupatikana")


def forbidden() -> AppError:
    return AppError(403, "FORBIDDEN", "You do not have permission for this action",
                    "Huna ruhusa ya kufanya kitendo hiki")


def rule_violation(message_en: str, message_sw: str, status_code: int = 422, **extra) -> AppError:
    return AppError(status_code, "RULE_VIOLATION", message_en, message_sw, extra)


# SQLSTATE -> (HTTP status, code, English, Kiswahili)
_DB_ERRORS = {
    "23505": (409, "DUPLICATE", "A record with these details already exists",
              "Taarifa hizi tayari zipo"),
    "23P01": (409, "CLASH", "This conflicts with an existing booking",
              "Hii inagongana na ratiba iliyopo"),
    "23503": (409, "INVALID_REFERENCE", "A referenced record does not exist or is still in use",
              "Taarifa inayorejelewa haipo au bado inatumika"),
    "23514": (422, "CHECK_FAILED", "A value is outside the allowed range or format",
              "Thamani haiko katika kiwango au muundo unaoruhusiwa"),
    "22000": (422, "INVALID_DATA", "Invalid data", "Data si sahihi"),
    "22P02": (422, "INVALID_DATA", "Invalid data", "Data si sahihi"),
    "P0001": (409, "RULE_VIOLATION", "This change is not allowed",
              "Mabadiliko haya hayaruhusiwi"),
}


def register_error_handlers(app: FastAPI) -> None:
    @app.exception_handler(AppError)
    async def _app_error(_: Request, exc: AppError) -> JSONResponse:
        return JSONResponse(exc.body(), status_code=exc.status_code, headers=exc.headers)

    @app.exception_handler(DBAPIError)
    async def _db_error(_: Request, exc: DBAPIError) -> JSONResponse:
        sqlstate = getattr(exc.orig, "sqlstate", None)
        if sqlstate not in _DB_ERRORS:
            raise exc
        status, code, en, sw = _DB_ERRORS[sqlstate]
        diag = getattr(exc.orig, "diag", None)
        constraint = getattr(diag, "constraint_name", None)
        db_message = getattr(diag, "message_primary", None)
        detail = {"code": code, "message_en": en, "message_sw": sw, "constraint": constraint}
        if sqlstate == "P0001":
            detail["reason"] = db_message
        return JSONResponse({"detail": detail}, status_code=status)
