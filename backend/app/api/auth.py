"""Authentication endpoints."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.config import Settings, get_settings
from app.db import get_db
from app.deps import get_current_user
from app.errors import error_response
from app.models import ROLE_ADMIN, ROLE_MEMBER, PasswordReset, RefreshToken, User
from app.schemas.auth import (
    AuthResponse,
    LoginRequest,
    MessageResponse,
    PasswordResetConfirm,
    PasswordResetRequest,
    PasswordResetRequested,
    ProfileUpdateRequest,
    RegisterRequest,
    UserRead,
)
from app.schemas.preferences import DEFAULT_THEME, THEMES, Preferences
from app.security.cookies import clear_auth_cookies, is_secure_request, set_auth_cookies
from app.security.passwords import hash_password, verify_password
from app.security.rate_limit import RateLimiter, get_rate_limiter
from app.security.tokens import (
    REFRESH_COOKIE,
    create_access_token,
    generate_opaque_token,
    hash_token,
    refresh_token_expiry,
    utcnow,
)
from app.services import audit
from app.services.auth import (
    create_password_reset,
    ensure_utc,
    find_refresh_token,
    issue_session,
    revoke_all_for_user,
    revoke_family,
    revoke_token,
)

router = APIRouter(prefix="/api/v1/auth", tags=["auth"])

INVALID_CREDENTIALS = "Email or password is incorrect."
SESSION_INVALID = "Your session is no longer valid. Sign in again."
INVALID_RESET = "This reset link is invalid or has expired. Request a new one."


def _secure(request: Request, settings: Settings) -> bool:
    return is_secure_request(request.url.scheme, request.headers.get("x-forwarded-proto"), settings)


def _user_read(user: User) -> UserRead:
    return UserRead.model_validate(user)


def _preferences(user: User) -> Preferences:
    """The stored preferences, with defaults for anything missing or unrecognised.

    A value written by an older build (or by hand) never reaches the browser as
    an unknown theme; it falls back to the default instead.
    """
    stored = user.preferences or {}
    theme = stored.get("theme")
    return Preferences(theme=theme if theme in THEMES else DEFAULT_THEME)


def _session_expired_response(request: Request, settings: Settings, message: str) -> Response:
    response = error_response(status.HTTP_401_UNAUTHORIZED, message)
    clear_auth_cookies(response, _secure(request, settings))
    return response


@router.post("/register", response_model=AuthResponse, status_code=status.HTTP_201_CREATED)
def register(
    payload: RegisterRequest,
    request: Request,
    response: Response,
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> AuthResponse:
    """Create an account. The first account becomes the admin."""
    email = str(payload.email).lower()
    if db.scalar(select(User.id).where(User.email == email)) is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="An account with this email already exists. Sign in instead.",
        )

    is_first_user = db.scalar(select(func.count()).select_from(User)) == 0
    user = User(
        email=email,
        name=payload.name.strip(),
        password_hash=hash_password(payload.password),
        role=ROLE_ADMIN if is_first_user else ROLE_MEMBER,
    )
    db.add(user)
    db.flush()

    access_token, refresh_token = issue_session(db, user, request, settings)
    audit.record(
        db,
        "auth.register",
        actor_id=user.id,
        target_type="user",
        target_id=str(user.id),
        metadata={"role": user.role},
        request=request,
    )
    db.commit()
    db.refresh(user)

    set_auth_cookies(
        response,
        access_token=access_token,
        refresh_token=refresh_token,
        settings=settings,
        secure=_secure(request, settings),
    )
    return AuthResponse(user=_user_read(user))


@router.post("/login", response_model=AuthResponse)
def login(
    payload: LoginRequest,
    request: Request,
    response: Response,
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
    limiter: RateLimiter = Depends(get_rate_limiter),
) -> AuthResponse:
    """Sign in and start a session."""
    email = str(payload.email).lower()
    ip_address = request.client.host if request.client else "unknown"
    rate_key = f"greenlit:login:{email}:{ip_address}"

    if not limiter.allow(
        rate_key, settings.login_rate_limit_attempts, settings.login_rate_limit_window_seconds
    ):
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="Too many sign-in attempts. Wait a few minutes and try again.",
        )

    user = db.scalar(select(User).where(User.email == email))
    if (
        user is None
        or not user.is_active
        or not verify_password(payload.password, user.password_hash)
    ):
        audit.record(
            db, "auth.sign_in_failed", target_type="email", target_id=email, request=request
        )
        db.commit()
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail=INVALID_CREDENTIALS)

    limiter.reset(rate_key)
    access_token, refresh_token = issue_session(db, user, request, settings)
    audit.record(
        db,
        "auth.sign_in",
        actor_id=user.id,
        target_type="user",
        target_id=str(user.id),
        request=request,
    )
    db.commit()

    set_auth_cookies(
        response,
        access_token=access_token,
        refresh_token=refresh_token,
        settings=settings,
        secure=_secure(request, settings),
    )
    return AuthResponse(user=_user_read(user))


@router.post("/refresh", response_model=AuthResponse)
def refresh(
    request: Request,
    response: Response,
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> AuthResponse | Response:
    """Rotate the refresh token and issue a new access token."""
    raw_token = request.cookies.get(REFRESH_COOKIE)
    if not raw_token:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Sign in to continue.")

    stored = find_refresh_token(db, raw_token)
    if stored is None:
        return _session_expired_response(request, settings, SESSION_INVALID)

    if stored.revoked_at is not None:
        # Reuse of a rotated token: assume theft and revoke the whole family.
        revoke_family(db, stored.family_id)
        audit.record(
            db,
            "auth.refresh_reuse",
            actor_id=stored.user_id,
            target_type="refresh_token",
            target_id=str(stored.id),
            request=request,
        )
        db.commit()
        return _session_expired_response(request, settings, SESSION_INVALID)

    if ensure_utc(stored.expires_at) <= utcnow():
        revoke_token(db, stored)
        db.commit()
        return _session_expired_response(request, settings, "Your session expired. Sign in again.")

    user = db.get(User, stored.user_id)
    if user is None or not user.is_active:
        revoke_token(db, stored)
        db.commit()
        return _session_expired_response(request, settings, SESSION_INVALID)

    new_raw = generate_opaque_token()
    new_token = RefreshToken(
        user_id=user.id,
        token_hash=hash_token(new_raw),
        family_id=stored.family_id,
        expires_at=refresh_token_expiry(settings),
        ip_address=stored.ip_address,
        user_agent=stored.user_agent,
    )
    db.add(new_token)
    db.flush()
    revoke_token(db, stored, replaced_by=new_token.id)
    access_token = create_access_token(user.id, user.role, settings)
    db.commit()

    set_auth_cookies(
        response,
        access_token=access_token,
        refresh_token=new_raw,
        settings=settings,
        secure=_secure(request, settings),
    )
    return AuthResponse(user=_user_read(user))


@router.post("/logout", response_model=MessageResponse)
def logout(
    request: Request,
    response: Response,
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> MessageResponse:
    """Revoke the presented refresh token and clear both cookies."""
    raw_token = request.cookies.get(REFRESH_COOKIE)
    if raw_token:
        stored = find_refresh_token(db, raw_token)
        if stored is not None:
            if stored.revoked_at is None:
                revoke_token(db, stored)
            audit.record(
                db,
                "auth.sign_out",
                actor_id=stored.user_id,
                target_type="refresh_token",
                target_id=str(stored.id),
                request=request,
            )
            db.commit()
    clear_auth_cookies(response, _secure(request, settings))
    return MessageResponse(message="Signed out.")


@router.get("/me", response_model=UserRead)
def me(user: User = Depends(get_current_user)) -> UserRead:
    """Return the signed-in user."""
    return _user_read(user)


@router.patch("/me", response_model=UserRead)
def update_me(
    payload: ProfileUpdateRequest,
    request: Request,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> UserRead:
    """Change the signed-in user's display name.

    Only the caller's own account can be touched: the target comes from the
    session, never from the request body, so there is no user id to tamper with.
    Role, email and password are not editable here.
    """
    if payload.name != user.name:
        user.name = payload.name
        audit.record(
            db,
            "user.profile_updated",
            actor_id=user.id,
            target_type="user",
            target_id=str(user.id),
            metadata={"changed": ["name"]},
            request=request,
        )
        db.commit()
        db.refresh(user)
    return _user_read(user)


@router.get("/me/preferences", response_model=Preferences)
def get_my_preferences(user: User = Depends(get_current_user)) -> Preferences:
    """Return the signed-in user's UI preferences."""
    return _preferences(user)


@router.patch("/me/preferences", response_model=Preferences)
def update_my_preferences(
    payload: Preferences,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> Preferences:
    """Replace the signed-in user's preferences.

    Scoped to the session's own account for the same reason as the profile
    update. Not audited: a theme choice is cosmetic and would only add noise to
    the trail of sign-ins and data changes.
    """
    user.preferences = {**(user.preferences or {}), "theme": payload.theme}
    db.commit()
    db.refresh(user)
    return _preferences(user)


@router.post("/password-reset/request", response_model=PasswordResetRequested)
def request_password_reset(
    payload: PasswordResetRequest,
    request: Request,
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> PasswordResetRequested:
    """Start a password reset. The answer is the same whether the email exists or not."""
    email = str(payload.email).lower()
    user = db.scalar(select(User).where(User.email == email))
    debug_token: str | None = None
    if user is not None:
        _, raw_token = create_password_reset(db, user, settings)
        audit.record(
            db,
            "auth.password_reset_requested",
            actor_id=user.id,
            target_type="user",
            target_id=str(user.id),
            request=request,
        )
        db.commit()
        if settings.is_development or settings.debug:
            # No mail provider is configured yet; developers get the token directly.
            debug_token = raw_token

    return PasswordResetRequested(
        message="If that email exists, a password reset link has been created.",
        debug_token=debug_token,
    )


@router.post("/password-reset/confirm", response_model=MessageResponse)
def confirm_password_reset(
    payload: PasswordResetConfirm,
    request: Request,
    db: Session = Depends(get_db),
) -> MessageResponse:
    """Set a new password with a single-use reset token."""
    reset = db.scalar(
        select(PasswordReset).where(PasswordReset.token_hash == hash_token(payload.token))
    )
    now = utcnow()
    if reset is None or reset.used_at is not None or ensure_utc(reset.expires_at) <= now:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=INVALID_RESET)

    user = db.get(User, reset.user_id)
    if user is None:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=INVALID_RESET)

    user.password_hash = hash_password(payload.new_password)
    reset.used_at = now
    revoke_all_for_user(db, user.id)
    audit.record(
        db,
        "auth.password_reset_completed",
        actor_id=user.id,
        target_type="user",
        target_id=str(user.id),
        request=request,
    )
    db.commit()
    return MessageResponse(message="Password updated. Sign in with the new password.")
