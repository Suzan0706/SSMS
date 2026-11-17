from typing import Annotated

from fastapi import APIRouter, Depends, Request, status
from fastapi.security import OAuth2PasswordRequestForm

from app.deps import CurrentUser, DbSession, client_ip
from app.schemas.auth import MeOut, PasswordChangeIn, RefreshIn, TokenPair
from app.services import auth as svc
from app.services.common import RequestMeta

router = APIRouter(prefix="/auth", tags=["Authentication"])


def request_meta(request: Request) -> RequestMeta:
    return RequestMeta(ip=client_ip(request), user_agent=request.headers.get("user-agent"),
                       request_id=request.state.request_id)


Meta = Annotated[RequestMeta, Depends(request_meta)]


@router.post("/login", response_model=TokenPair)
def login(form: Annotated[OAuth2PasswordRequestForm, Depends()], db: DbSession, meta: Meta):
    """Username (or email) + password. 401 on bad credentials, 423 while locked."""
    return svc.login(db, form.username, form.password, meta)


@router.post("/refresh", response_model=TokenPair)
def refresh(body: RefreshIn, db: DbSession, meta: Meta):
    """Rotate the refresh token. Re-using an old token revokes the whole session chain."""
    return svc.refresh(db, body.refresh_token, meta)


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT)
def logout(body: RefreshIn, user: CurrentUser, db: DbSession, meta: Meta):
    svc.logout(db, body.refresh_token, user, meta)


@router.get("/me", response_model=MeOut)
def me(user: CurrentUser):
    return user


@router.post("/change-password", status_code=status.HTTP_204_NO_CONTENT)
def change_password(body: PasswordChangeIn, user: CurrentUser, db: DbSession, meta: Meta):
    svc.change_password(db, user, body.current_password, body.new_password, meta)
