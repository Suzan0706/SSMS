"""Request dependencies: DB session, current user, role checks, audit context."""
import ipaddress
from typing import Annotated

import jwt
from fastapi import Depends, Request
from fastapi.security import OAuth2PasswordBearer
from sqlalchemy.orm import Session

from app.core.errors import AppError, forbidden
from app.core.security import decode_access_token
from app.db import get_db, set_audit_context
from app.models import User
from app.models.enums import Role
from app.services.storage import LocalStorage, Storage

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/api/v1/auth/login")

DbSession = Annotated[Session, Depends(get_db)]


def client_ip(request: Request) -> str | None:
    """Real client address (Uvicorn runs with --proxy-headers behind Nginx); None if not a valid IP,
    because it is stored in INET columns."""
    host = request.client.host if request.client else None
    try:
        return str(ipaddress.ip_address(host)) if host else None
    except ValueError:
        return None


def get_current_user(request: Request, db: DbSession, token: str = Depends(oauth2_scheme)) -> User:
    unauthorised = AppError(401, "NOT_AUTHENTICATED", "Please log in again", "Tafadhali ingia tena",
                            headers={"WWW-Authenticate": "Bearer"})
    try:
        payload = decode_access_token(token)
    except jwt.PyJWTError:
        raise unauthorised
    user = db.get(User, int(payload["sub"]))
    if user is None or not user.is_active:
        raise unauthorised
    set_audit_context(db, user_id=user.user_id, user_role=user.role.value,
                      client_ip=client_ip(request), request_id=request.state.request_id)
    return user


CurrentUser = Annotated[User, Depends(get_current_user)]


def require_roles(*roles: Role):
    """Dependency factory: allow only the given roles."""
    def checker(user: CurrentUser) -> User:
        if user.role not in roles:
            raise forbidden()
        return user
    return checker


def get_storage() -> Storage:
    return LocalStorage()
