"""Request dependencies: current user and role guards."""

from __future__ import annotations

import uuid
from collections.abc import Callable

import jwt
from fastapi import Depends, HTTPException, Request, status
from sqlalchemy.orm import Session

from app.db import get_db
from app.models import User
from app.security.tokens import ACCESS_COOKIE, decode_access_token


def _unauthorized(message: str) -> HTTPException:
    return HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail=message)


def get_current_user(request: Request, db: Session = Depends(get_db)) -> User:
    """Resolve the signed-in user from the access cookie."""
    token = request.cookies.get(ACCESS_COOKIE)
    if not token:
        raise _unauthorized("Sign in to continue.")
    try:
        payload = decode_access_token(token)
    except jwt.ExpiredSignatureError as exc:
        raise _unauthorized("Your session expired. Sign in again.") from exc
    except jwt.InvalidTokenError as exc:
        raise _unauthorized("Your session is not valid. Sign in again.") from exc

    try:
        user_id = uuid.UUID(str(payload["sub"]))
    except (KeyError, ValueError) as exc:
        raise _unauthorized("Your session is not valid. Sign in again.") from exc

    user = db.get(User, user_id)
    if user is None or not user.is_active:
        raise _unauthorized("This account is not available. Sign in again.")
    return user


def require_roles(*roles: str) -> Callable[..., User]:
    """Dependency factory enforcing server-side role checks."""

    def guard(user: User = Depends(get_current_user)) -> User:
        if user.role not in roles:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Your role does not allow this action.",
            )
        return user

    return guard


require_admin = require_roles("admin")
