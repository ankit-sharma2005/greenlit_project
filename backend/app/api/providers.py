"""Provider CRUD and test-connection endpoints."""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db import get_db
from app.deps import get_current_user
from app.models import Provider
from app.schemas.providers import (
    ProviderCreate,
    ProviderRead,
    ProviderTestResult,
    ProviderUpdate,
)
from app.services.providers import test_provider_connection

router = APIRouter(prefix="/api/v1/providers", tags=["providers"])


def _require_admin(user: object) -> object:
    """Only admin can manage providers."""
    if getattr(user, "role", "") != "admin":
        raise HTTPException(status_code=403, detail="Admin required")
    return user


def _require_user(user: object) -> object:
    """Any authenticated user can access provider endpoints."""
    if getattr(user, "role", "") not in ("admin", "member", "reviewer"):
        raise HTTPException(status_code=403, detail="Authentication required")
    return user


@router.post("", response_model=ProviderRead, status_code=201)
def create_provider(
    payload: ProviderCreate,
    request: Request,
    db: Session = Depends(get_db),
    user: object = Depends(_require_admin),
) -> ProviderRead:
    """Create a new provider. Duplicate names are rejected."""
    from sqlalchemy import func

    existing = db.scalar(select(Provider).where(func.lower(Provider.name) == payload.name.lower()))
    if existing:
        raise HTTPException(
            status_code=409, detail="Provider '" + payload.name + "' already exists."
        )
    from app.security.keys import encrypt_key

    encrypted_key = encrypt_key(payload.api_key) if payload.api_key else None
    provider = Provider(
        name=payload.name,
        kind=payload.kind,
        model_name=payload.model_name,
        base_url=payload.base_url,
        api_key_encrypted=encrypted_key,
        timeout_seconds=payload.timeout_seconds,
        max_retries=payload.max_retries,
        backoff_factor=payload.backoff_factor,
        rate_limit_per_minute=payload.rate_limit_per_minute,
        tokens_per_minute=payload.tokens_per_minute,
        is_active=payload.is_active,
        provider_config=payload.metadata,
        connector=payload.connector,
    )
    db.add(provider)
    db.commit()
    db.refresh(provider)
    return ProviderRead.model_validate(provider)


@router.get("", response_model=list[ProviderRead])
def list_providers(
    db: Session = Depends(get_db),
    user: object = Depends(get_current_user),
) -> list[ProviderRead]:
    """List all providers (visible to all authenticated users)."""
    providers = db.scalars(select(Provider).where(Provider.is_active)).all()
    return [ProviderRead.model_validate(p) for p in providers]


@router.get("/{provider_id}", response_model=ProviderRead)
def get_provider(
    provider_id: uuid.UUID,
    db: Session = Depends(get_db),
    user: object = Depends(get_current_user),
) -> ProviderRead:
    """Get a single provider by ID."""
    provider = db.scalar(select(Provider).where(Provider.id == provider_id))
    if provider is None:
        raise HTTPException(status_code=404, detail="Provider not found")
    return ProviderRead.model_validate(provider)


@router.patch("/{provider_id}", response_model=ProviderRead)
def update_provider(
    provider_id: uuid.UUID,
    payload: ProviderUpdate,
    request: Request,
    db: Session = Depends(get_db),
    user: object = Depends(_require_admin),
) -> ProviderRead:
    """Update a provider. Only admins."""
    provider = db.scalar(select(Provider).where(Provider.id == provider_id))
    if provider is None:
        raise HTTPException(status_code=404, detail="Provider not found")
    if payload.name is not None and payload.name != provider.name:
        from sqlalchemy import func

        existing = db.scalar(
            select(Provider).where(
                func.lower(Provider.name) == payload.name.lower(),
                Provider.id != provider_id,
            )
        )
        if existing:
            raise HTTPException(
                status_code=409, detail=f"Provider '{payload.name}' already exists."
            )
    if payload.api_key is not None:
        from app.security.keys import encrypt_key

        provider.api_key_encrypted = encrypt_key(payload.api_key)
    for field, value in payload.model_dump(exclude_unset=True).items():
        setattr(provider, field, value)
    db.commit()
    db.refresh(provider)
    return ProviderRead.model_validate(provider)


@router.delete("/{provider_id}", status_code=204, response_model=None)
def delete_provider(
    provider_id: uuid.UUID,
    request: Request,
    db: Session = Depends(get_db),
    user: object = Depends(_require_admin),
) -> None:
    """Delete a provider. Only admins. Hard delete."""
    provider = db.scalar(select(Provider).where(Provider.id == provider_id))
    if provider is None:
        raise HTTPException(status_code=404, detail="Provider not found")
    db.delete(provider)
    db.commit()


@router.post("/{provider_id}/test", response_model=ProviderTestResult)
def test_provider_connection_endpoint(
    provider_id: uuid.UUID,
    request: Request,
    db: Session = Depends(get_db),
    user: object = Depends(get_current_user),
) -> ProviderTestResult:
    """Test a provider's connection and return health status."""
    provider = db.scalar(select(Provider).where(Provider.id == provider_id))
    if provider is None:
        raise HTTPException(status_code=404, detail="Provider not found")
    result = test_provider_connection(provider)
    return ProviderTestResult.model_validate(result)
