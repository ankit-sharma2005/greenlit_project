"""Session cookies: httpOnly, SameSite=Lax, Secure only over TLS."""

from __future__ import annotations

from fastapi import Response

from app.config import Settings
from app.security.tokens import ACCESS_COOKIE, REFRESH_COOKIE, utcnow


def is_secure_request(request_scheme: str, forwarded_proto: str | None, settings: Settings) -> bool:
    """Decide the Secure flag: explicit setting wins, otherwise trust HTTPS."""
    if settings.cookie_secure is not None:
        return settings.cookie_secure
    scheme = (forwarded_proto or request_scheme or "").split(",")[0].strip().lower()
    return scheme == "https"


def set_auth_cookies(
    response: Response,
    *,
    access_token: str,
    refresh_token: str,
    settings: Settings,
    secure: bool,
) -> None:
    """Attach the access and refresh cookies to a response."""
    response.set_cookie(
        ACCESS_COOKIE,
        access_token,
        max_age=settings.access_token_expire_minutes * 60,
        httponly=True,
        secure=secure,
        samesite="lax",
        path="/",
    )
    response.set_cookie(
        REFRESH_COOKIE,
        refresh_token,
        max_age=settings.refresh_token_expire_days * 24 * 60 * 60,
        httponly=True,
        secure=secure,
        samesite="lax",
        path="/",
    )


def clear_auth_cookies(response: Response, secure: bool) -> None:
    """Expire both session cookies."""
    for name in (ACCESS_COOKIE, REFRESH_COOKIE):
        response.set_cookie(
            name,
            "",
            max_age=0,
            expires=utcnow(),
            httponly=True,
            secure=secure,
            samesite="lax",
            path="/",
        )
