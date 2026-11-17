"""/auth: password login, parent OTP login, refresh (rotating httpOnly cookie), logout, me, change password."""

from fastapi import APIRouter, Depends, Request, Response, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import Principal, current_principal, request_context
from app.core.config import get_settings
from app.core.errors import lang_of
from app.core.i18n import message
from app.db.session import get_session
from app.models import School, User
from app.schemas.auth import (
    ChangePasswordIn,
    LoginIn,
    MeOut,
    OtpRequestOut,
    OtpVerifyIn,
    PhoneIn,
    SchoolBrief,
    SchoolChoice,
    SchoolSelectionOut,
    SelectSchoolIn,
    TokenOut,
    UserBrief,
)
from app.services import auth
from app.tasks.dispatch import get_dispatcher

router = APIRouter(prefix="/auth", tags=["auth"])
COOKIE_PATH = "/api/v1/auth"
AUTH_ERRORS = {
    401: {"description": "INVALID_CREDENTIALS / INVALID_TOKEN / OTP_INVALID"},
    423: {"description": "ACCOUNT_LOCKED"},
    429: {"description": "RATE_LIMITED"},
}


def _user_agent(request: Request) -> str | None:
    return request.headers.get("user-agent")


def _me(user: User, school: School, roles, permissions) -> dict:
    return {
        "user": UserBrief(
            id=user.id,
            full_name=user.full_name,
            username=user.username,
            language=user.preferred_language,
            must_change_password=user.must_change_password,
        ),
        "school": SchoolBrief.model_validate(school),
        "roles": sorted(roles),
        "permissions": sorted(permissions),
    }


def _signed_in(response: Response, result: auth.SignIn) -> TokenOut:
    settings = get_settings()
    response.set_cookie(
        settings.refresh_cookie_name,
        result.refresh_token,
        max_age=result.refresh_max_age,
        path=COOKIE_PATH,
        httponly=True,
        secure=settings.cookie_secure,
        samesite="strict",
    )
    return TokenOut(
        access_token=result.access_token,
        expires_in=settings.access_token_minutes * 60,
        **_me(result.user, result.school, result.roles, result.permissions),
    )


def _clear_cookie(response: Response) -> None:
    settings = get_settings()
    response.delete_cookie(
        settings.refresh_cookie_name, path=COOKIE_PATH, httponly=True, secure=settings.cookie_secure, samesite="strict"
    )


@router.post(
    "/login",
    response_model=TokenOut,
    responses=AUTH_ERRORS,
    summary="Staff / student login with school code, username and password",
)
async def login(body: LoginIn, request: Request, response: Response, session: AsyncSession = Depends(get_session)):
    result = await auth.login(
        session, request_context(request), body.school_code, body.username, body.password, _user_agent(request)
    )
    return _signed_in(response, result)


@router.post(
    "/otp/request",
    response_model=OtpRequestOut,
    responses={429: AUTH_ERRORS[429]},
    summary="Parent login step 1: send a 6-digit code by SMS (same answer for unknown phones)",
)
async def otp_request(body: PhoneIn, request: Request, session: AsyncSession = Depends(get_session)):
    for call in await auth.request_otp(session, request_context(request), body.phone, _user_agent(request)):
        get_dispatcher().send("sms.send", **call)
    return OtpRequestOut(message=message("OTP_SENT", lang_of(request)))


@router.post(
    "/otp/verify",
    response_model=TokenOut | SchoolSelectionOut,
    responses=AUTH_ERRORS,
    summary="Parent login step 2: tokens, or a school choice when the phone is registered in several schools",
)
async def otp_verify(
    body: OtpVerifyIn, request: Request, response: Response, session: AsyncSession = Depends(get_session)
):
    result = await auth.verify_otp(session, request_context(request), body.phone, body.code, _user_agent(request))
    if isinstance(result, auth.SchoolSelection):
        return SchoolSelectionOut(
            choose=[SchoolChoice(school_id=s, name=n) for s, n in result.choices],
            selection_token=result.selection_token,
            expires_in=get_settings().selection_token_minutes * 60,
        )
    return _signed_in(response, result)


@router.post(
    "/select-school",
    response_model=TokenOut,
    responses=AUTH_ERRORS,
    summary="Parent login step 3 (several schools only): pick one school",
)
async def select_school(
    body: SelectSchoolIn, request: Request, response: Response, session: AsyncSession = Depends(get_session)
):
    result = await auth.select_school(
        session, request_context(request), body.selection_token, body.school_id, _user_agent(request)
    )
    return _signed_in(response, result)


@router.post(
    "/refresh",
    response_model=TokenOut,
    responses=AUTH_ERRORS,
    summary="New access token from the refresh cookie; the cookie is rotated",
)
async def refresh(request: Request, response: Response, session: AsyncSession = Depends(get_session)):
    raw = request.cookies.get(get_settings().refresh_cookie_name)
    result = await auth.refresh(session, request_context(request), raw, _user_agent(request))
    return _signed_in(response, result)


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT, summary="Revoke this device's session")
async def logout(request: Request, response: Response, session: AsyncSession = Depends(get_session)):
    await auth.logout(
        session, request_context(request), request.cookies.get(get_settings().refresh_cookie_name), _user_agent(request)
    )
    _clear_cookie(response)
    response.status_code = status.HTTP_204_NO_CONTENT
    return response


@router.get("/me", response_model=MeOut, summary="Profile, roles, permissions, language and school")
async def me(principal: Principal = Depends(current_principal), session: AsyncSession = Depends(get_session)):
    user = (await session.execute(select(User).where(User.id == principal.user_id))).scalar_one()
    school = (await session.execute(select(School).where(School.id == principal.school_id))).scalar_one()
    return _me(user, school, principal.roles, principal.permissions)


@router.post(
    "/change-password",
    status_code=status.HTTP_204_NO_CONTENT,
    responses={401: AUTH_ERRORS[401], 422: {"description": "WEAK_PASSWORD"}},
    summary="Change own password (also clears a temporary password); other sessions are signed out",
)
async def change_password(
    body: ChangePasswordIn,
    request: Request,
    response: Response,
    principal: Principal = Depends(current_principal),
    session: AsyncSession = Depends(get_session),
):
    await auth.change_password(
        session,
        principal.user_id,
        body.current_password,
        body.new_password,
        request.cookies.get(get_settings().refresh_cookie_name),
        _user_agent(request),
    )
    response.status_code = status.HTTP_204_NO_CONTENT
    return response
