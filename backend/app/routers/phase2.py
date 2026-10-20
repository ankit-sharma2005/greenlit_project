from __future__ import annotations

import json
import time
from typing import Annotated
from urllib.parse import urlsplit
from uuid import UUID, uuid4

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import delete, func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_db
from app.deps import require_roles
from app.models import (
    AppVersion,
    AuditLog,
    ConnectorProfile,
    Dataset,
    DatasetItem,
    DatasetVersion,
    EvalRun,
    EvalRunItem,
    JudgeProfile,
    Project,
    ProjectBaseline,
    ProjectVerdictCriteria,
    ProviderConfig,
    User,
)
from app.phase2_schemas import (
    ConnectorRename,
    ConnectorSaveRequest,
    ConnectorTestCallRequest,
    JudgeProfileUpsert,
    ProjectCreate,
    ProjectUpdate,
    ProviderCreate,
    ProviderRename,
)
from app.services.connectors import (
    connector_content_hash,
    entry_point_types,
    execute_test_call,
    provider_out,
    validate_connector_settings,
)
from app.services.llm_gateway import (
    LLMGateway,
    ProviderRequestError,
    normalize_provider_base_url,
)
from app.services.rate_limit import DailyQuotaPaused
from app.services.secrets import decrypt_secret, encrypt_secret
from app.services.test_authorization import (
    fingerprint,
    issue_test_token,
    verify_test_token,
)

router = APIRouter(tags=["providers", "projects", "connectors"])
gateway = LLMGateway()

Member = Annotated[
    User,
    Depends(require_roles("owner", "admin", "engineer", "reviewer", "viewer")),
]
Editor = Annotated[User, Depends(require_roles("owner", "admin"))]
Engineer = Annotated[User, Depends(require_roles("owner", "admin", "engineer"))]
ProjectWriter = Annotated[User, Depends(require_roles("owner", "admin"))]


@router.get("/entry-point-types")
async def list_entry_point_types() -> list[dict[str, object]]:
    return entry_point_types()


@router.get("/workspaces/{workspace_id}/providers")
async def list_providers(
    workspace_id: UUID,
    _: Member,
    db: Annotated[AsyncSession, Depends(get_db)],
) -> list[dict[str, object]]:
    providers = await db.scalars(
        select(ProviderConfig)
        .where(ProviderConfig.workspace_id == workspace_id)
        .order_by(ProviderConfig.created_at)
    )
    return [provider_out(provider) for provider in providers]


@router.post(
    "/workspaces/{workspace_id}/providers", status_code=status.HTTP_201_CREATED
)
async def create_provider(
    workspace_id: UUID,
    payload: ProviderCreate,
    user: Editor,
    db: Annotated[AsyncSession, Depends(get_db)],
) -> dict[str, object]:
    base_url = _provider_base_url(payload)
    test_hash = _provider_test_hash(payload, base_url)
    if not payload.test_token or not verify_test_token(
        payload.test_token, "provider", workspace_id, user.id, test_hash
    ):
        raise HTTPException(
            status_code=409,
            detail="Test this exact provider configuration successfully before saving",
        )

    name_key = _name_key(payload.name)
    existing_name = await _provider_named(workspace_id, name_key, db)
    if existing_name is not None:
        if (
            existing_name.duplicate_of is None
            and existing_name.name == payload.name.strip()
            and _provider_matches(existing_name, payload, base_url)
        ):
            return provider_out(existing_name)
        raise HTTPException(
            status_code=409,
            detail="A provider with this name already exists in this workspace.",
        )

    existing_ids = set(
        await db.scalars(
            select(ProviderConfig.id).where(ProviderConfig.workspace_id == workspace_id)
        )
    )
    if any(
        provider_id not in existing_ids for provider_id in payload.fallback_provider_ids
    ):
        raise HTTPException(
            status_code=422,
            detail="Fallback providers must belong to this workspace",
        )
    if len(set(payload.fallback_provider_ids)) != len(payload.fallback_provider_ids):
        raise HTTPException(
            status_code=422, detail="Fallback provider IDs must be unique"
        )

    api_key = payload.api_key.get_secret_value() if payload.api_key else None
    provider = ProviderConfig(
        workspace_id=workspace_id,
        name=payload.name.strip(),
        name_key=name_key,
        provider_type=payload.provider_type,
        base_url=base_url,
        test_model=_configured_model(payload),
        api_key_encrypted=encrypt_secret(api_key) if api_key else None,
        rpm=payload.rpm,
        rpd=payload.rpd,
        max_input_tokens=payload.max_input_tokens,
        max_output_tokens=payload.max_output_tokens,
        fallback_provider_ids=[str(value) for value in payload.fallback_provider_ids],
    )
    db.add(provider)
    db.add(
        AuditLog(
            user_id=user.id,
            workspace_id=workspace_id,
            action="provider_created",
            details={"provider_type": provider.provider_type, "name": provider.name},
        )
    )
    try:
        await db.commit()
    except IntegrityError as exc:
        await db.rollback()
        existing_name = await _provider_named(workspace_id, name_key, db)
        if (
            existing_name is not None
            and existing_name.duplicate_of is None
            and existing_name.name == payload.name.strip()
            and _provider_matches(existing_name, payload, base_url)
        ):
            return provider_out(existing_name)
        raise HTTPException(
            status_code=409,
            detail="A provider with this name already exists in this workspace.",
        ) from exc
    await db.refresh(provider)
    return provider_out(provider)


@router.post("/workspaces/{workspace_id}/providers/test-connection")
async def test_provider_configuration(
    workspace_id: UUID,
    payload: ProviderCreate,
    user: Editor,
) -> dict[str, object]:
    provider = _transient_provider(payload)
    started = time.perf_counter()
    result = await _test_provider(provider, _configured_model(payload))
    base_url = provider.base_url
    test_hash = _provider_test_hash(payload, base_url)
    return {
        "ok": True,
        **result,
        "test_token": issue_test_token("provider", workspace_id, user.id, test_hash),
        "latency_ms": round((time.perf_counter() - started) * 1000, 2),
    }


@router.post("/workspaces/{workspace_id}/providers/{provider_id}/test-connection")
async def test_provider_connection(
    workspace_id: UUID,
    provider_id: UUID,
    _: Editor,
    db: Annotated[AsyncSession, Depends(get_db)],
) -> dict[str, object]:
    provider = await db.scalar(
        select(ProviderConfig).where(
            ProviderConfig.id == provider_id,
            ProviderConfig.workspace_id == workspace_id,
        )
    )
    if provider is None:
        raise HTTPException(status_code=404, detail="Provider not found")
    started = time.perf_counter()
    result = await _test_provider(provider, provider.test_model)
    return {
        "ok": True,
        **result,
        "latency_ms": round((time.perf_counter() - started) * 1000, 2),
    }


@router.patch("/workspaces/{workspace_id}/providers/{provider_id}")
async def rename_provider(
    workspace_id: UUID,
    provider_id: UUID,
    payload: ProviderRename,
    user: Editor,
    db: Annotated[AsyncSession, Depends(get_db)],
) -> dict[str, object]:
    provider = await db.scalar(
        select(ProviderConfig).where(
            ProviderConfig.id == provider_id,
            ProviderConfig.workspace_id == workspace_id,
        )
    )
    if provider is None:
        raise HTTPException(status_code=404, detail="Provider not found")
    new_key = _name_key(payload.name)
    duplicate = await _provider_named(workspace_id, new_key, db)
    if duplicate is not None and duplicate.id != provider.id:
        raise HTTPException(
            status_code=409,
            detail="A provider with this name already exists in this workspace.",
        )
    provider.name = payload.name.strip()
    provider.name_key = new_key
    provider.original_name = None
    provider.duplicate_of = None
    db.add(
        AuditLog(
            user_id=user.id,
            workspace_id=workspace_id,
            action="provider_renamed",
            details={"provider_id": str(provider.id), "name": provider.name},
        )
    )
    try:
        await db.commit()
    except IntegrityError as exc:
        await db.rollback()
        raise HTTPException(
            status_code=409,
            detail="A provider with this name already exists in this workspace.",
        ) from exc
    await db.refresh(provider)
    return provider_out(provider)


@router.delete("/workspaces/{workspace_id}/providers/{provider_id}")
async def delete_provider(
    workspace_id: UUID,
    provider_id: UUID,
    user: Editor,
    db: Annotated[AsyncSession, Depends(get_db)],
) -> dict[str, bool]:
    provider = await db.scalar(
        select(ProviderConfig).where(
            ProviderConfig.id == provider_id,
            ProviderConfig.workspace_id == workspace_id,
        )
    )
    if provider is None:
        raise HTTPException(status_code=404, detail="Provider not found")
    profiles = await db.scalars(
        select(JudgeProfile).where(JudgeProfile.provider_id == provider_id)
    )
    connectors = await db.scalars(select(ConnectorProfile))
    fallback_users = await db.scalars(select(ProviderConfig))
    is_referenced = (
        next(iter(profiles), None) is not None
        or any(
            str(provider_id) in provider_row.fallback_provider_ids
            for provider_row in fallback_users
            if provider_row.id != provider_id
        )
        or any(
            connector.provider_id == provider_id
            or _provider_referenced(connector.settings, provider_id)
            for connector in connectors
        )
    )
    if is_referenced:
        raise HTTPException(
            status_code=409,
            detail=(
                "This provider is used by a saved connector, judge profile, "
                "or fallback chain."
            ),
        )
    db.add(
        AuditLog(
            user_id=user.id,
            workspace_id=workspace_id,
            action="provider_deleted",
            details={"provider_id": str(provider_id), "name": provider.name},
        )
    )
    await db.delete(provider)
    await db.commit()
    return {"ok": True}


@router.get("/workspaces/{workspace_id}/projects")
async def list_projects(
    workspace_id: UUID,
    _: Member,
    db: Annotated[AsyncSession, Depends(get_db)],
) -> list[dict[str, object]]:
    projects = await db.scalars(
        select(Project)
        .where(Project.workspace_id == workspace_id)
        .order_by(Project.created_at)
    )
    return [_project_out(project) for project in projects]


@router.post("/workspaces/{workspace_id}/projects", status_code=status.HTTP_201_CREATED)
async def create_project(
    workspace_id: UUID,
    payload: ProjectCreate,
    user: ProjectWriter,
    db: Annotated[AsyncSession, Depends(get_db)],
) -> dict[str, object]:
    name_key = _name_key(payload.name)
    existing = await _project_named(workspace_id, name_key, db)
    if existing is not None:
        if (
            existing.duplicate_of is None
            and existing.name == payload.name.strip()
            and existing.description == payload.description
        ):
            return _project_out(existing)
        raise HTTPException(
            status_code=409,
            detail="A project with this name already exists in this workspace.",
        )
    project = Project(
        workspace_id=workspace_id,
        name=payload.name.strip(),
        name_key=name_key,
        description=payload.description,
    )
    db.add(project)
    await db.flush()
    db.add(
        AppVersion(
            project_id=project.id,
            version=1,
            config_snapshot={},
        )
    )
    db.add(
        AuditLog(
            user_id=user.id,
            workspace_id=workspace_id,
            action="project_created",
            details={"project_name": project.name},
        )
    )
    try:
        await db.commit()
    except IntegrityError as exc:
        await db.rollback()
        existing = await _project_named(workspace_id, name_key, db)
        if (
            existing is not None
            and existing.name == payload.name.strip()
            and existing.description == payload.description
        ):
            return _project_out(existing)
        raise HTTPException(
            status_code=409,
            detail="A project with this name already exists in this workspace.",
        ) from exc
    await db.refresh(project)
    return _project_out(project)


@router.patch("/workspaces/{workspace_id}/projects/{project_id}")
async def update_project(
    workspace_id: UUID,
    project_id: UUID,
    payload: ProjectUpdate,
    user: ProjectWriter,
    db: Annotated[AsyncSession, Depends(get_db)],
) -> dict[str, object]:
    project = await _get_project(db, workspace_id, project_id)
    name_key = _name_key(payload.name)
    duplicate = await _project_named(workspace_id, name_key, db)
    if duplicate is not None and duplicate.id != project.id:
        raise HTTPException(
            status_code=409,
            detail="A project with this name already exists in this workspace.",
        )
    project.name = payload.name.strip()
    project.name_key = name_key
    project.original_name = None
    project.duplicate_of = None
    project.description = payload.description
    db.add(
        AuditLog(
            user_id=user.id,
            workspace_id=workspace_id,
            action="project_updated",
            details={"project_id": str(project.id), "name": project.name},
        )
    )
    try:
        await db.commit()
    except IntegrityError as exc:
        await db.rollback()
        raise HTTPException(
            status_code=409,
            detail="A project with this name already exists in this workspace.",
        ) from exc
    await db.refresh(project)
    return _project_out(project)


@router.delete("/workspaces/{workspace_id}/projects/{project_id}")
async def delete_project(
    workspace_id: UUID,
    project_id: UUID,
    user: ProjectWriter,
    db: Annotated[AsyncSession, Depends(get_db)],
) -> dict[str, bool]:
    project = await _get_project(db, workspace_id, project_id)
    await db.execute(
        delete(ProjectBaseline).where(ProjectBaseline.project_id == project_id)
    )
    run_ids = select(EvalRun.id).where(EvalRun.project_id == project_id)
    await db.execute(delete(EvalRunItem).where(EvalRunItem.run_id.in_(run_ids)))
    await db.execute(delete(EvalRun).where(EvalRun.project_id == project_id))
    dataset_ids = select(Dataset.id).where(Dataset.project_id == project_id)
    version_ids = select(DatasetVersion.id).where(
        DatasetVersion.dataset_id.in_(dataset_ids)
    )
    await db.execute(
        delete(DatasetItem).where(DatasetItem.dataset_version_id.in_(version_ids))
    )
    await db.execute(
        delete(DatasetVersion).where(DatasetVersion.dataset_id.in_(dataset_ids))
    )
    await db.execute(delete(Dataset).where(Dataset.project_id == project_id))
    await db.execute(delete(JudgeProfile).where(JudgeProfile.project_id == project_id))
    await db.execute(
        delete(ProjectVerdictCriteria).where(
            ProjectVerdictCriteria.project_id == project_id
        )
    )
    await db.execute(delete(AppVersion).where(AppVersion.project_id == project_id))
    await db.execute(
        delete(ConnectorProfile).where(ConnectorProfile.project_id == project_id)
    )
    db.add(
        AuditLog(
            user_id=user.id,
            workspace_id=workspace_id,
            action="project_deleted",
            details={"project_id": str(project_id), "name": project.name},
        )
    )
    await db.delete(project)
    await db.commit()
    return {"ok": True}


@router.get("/workspaces/{workspace_id}/projects/{project_id}/app-versions")
async def list_app_versions(
    workspace_id: UUID,
    project_id: UUID,
    _: Member,
    db: Annotated[AsyncSession, Depends(get_db)],
) -> list[dict[str, object]]:
    await _get_project(db, workspace_id, project_id)
    versions = await db.scalars(
        select(AppVersion)
        .where(AppVersion.project_id == project_id)
        .order_by(AppVersion.version)
    )
    return [
        {
            "id": version.id,
            "version": version.version,
            "connector_profile_id": version.connector_profile_id,
            "content_hash": version.content_hash,
            "access_level": version.access_level,
            "config_snapshot": version.config_snapshot,
            "created_at": version.created_at.isoformat(),
        }
        for version in versions
    ]


@router.get("/workspaces/{workspace_id}/projects/{project_id}/connectors")
async def list_connectors(
    workspace_id: UUID,
    project_id: UUID,
    _: Member,
    db: Annotated[AsyncSession, Depends(get_db)],
) -> list[dict[str, object]]:
    await _get_project(db, workspace_id, project_id)
    records = await db.execute(
        select(ConnectorProfile, AppVersion.version)
        .join(AppVersion, AppVersion.connector_profile_id == ConnectorProfile.id)
        .where(ConnectorProfile.project_id == project_id)
        .order_by(AppVersion.version)
    )
    return [_connector_out(connector, version) for connector, version in records.all()]


@router.post("/workspaces/{workspace_id}/connectors/test-call")
async def test_connector_call(
    workspace_id: UUID,
    payload: ConnectorTestCallRequest,
    user: Engineer,
    db: Annotated[AsyncSession, Depends(get_db)],
) -> dict[str, object]:
    try:
        validated, settings = validate_connector_settings(
            payload.entry_point_type, payload.settings
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    provider_id, model = await _connector_provider_values(
        db, workspace_id, payload.provider_id, payload.model
    )
    credentials = {
        key: secret.get_secret_value() for key, secret in payload.credentials.items()
    }
    try:
        result = await execute_test_call(
            entry_point_type=payload.entry_point_type,
            settings=validated,
            provider_id=provider_id,
            model=model,
            input_text=payload.input,
            conversation_history=None,
            credentials=credentials,
            workspace_id=workspace_id,
            user_role=await _workspace_role(db, workspace_id, user.id),
            db=db,
            gateway=gateway,
        )
    except DailyQuotaPaused as exc:
        raise HTTPException(
            status_code=429,
            detail={
                "message": "Provider daily quota reached; connector test is paused",
                "retry_after_seconds": exc.retry_after_seconds,
            },
            headers={"Retry-After": str(exc.retry_after_seconds)},
        ) from exc
    except ProviderRequestError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    content_hash = connector_content_hash(
        payload.entry_point_type,
        settings,
        credentials,
        provider_id=provider_id,
        model=model,
    )
    test_hash = fingerprint({"content_hash": content_hash})
    return {
        "test_call_id": issue_test_token("connector", workspace_id, user.id, test_hash),
        **result,
    }


@router.post(
    "/workspaces/{workspace_id}/projects/{project_id}/connectors",
    status_code=status.HTTP_201_CREATED,
)
async def save_connector(
    workspace_id: UUID,
    project_id: UUID,
    payload: ConnectorSaveRequest,
    user: ProjectWriter,
    db: Annotated[AsyncSession, Depends(get_db)],
) -> dict[str, object]:
    await _get_project(db, workspace_id, project_id)
    try:
        _, settings = validate_connector_settings(
            payload.entry_point_type, payload.settings
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    provider_id, model = await _connector_provider_values(
        db, workspace_id, payload.provider_id, payload.model
    )
    credentials = {
        key: secret.get_secret_value() for key, secret in payload.credentials.items()
    }
    content_hash = connector_content_hash(
        payload.entry_point_type,
        settings,
        credentials,
        provider_id=provider_id,
        model=model,
    )
    test_hash = fingerprint({"content_hash": content_hash})
    if not verify_test_token(
        payload.test_call_id, "connector", workspace_id, user.id, test_hash
    ):
        raise HTTPException(
            status_code=409,
            detail="Run a successful test call for these exact settings before saving",
        )

    display_name = payload.name.strip() or payload.entry_point_type
    name_key = _name_key(display_name)
    existing_name = await db.scalar(
        select(ConnectorProfile).where(
            ConnectorProfile.project_id == project_id,
            ConnectorProfile.name_key == name_key,
        )
    )
    existing = await db.scalar(
        select(ConnectorProfile).where(
            ConnectorProfile.project_id == project_id,
            ConnectorProfile.content_hash == content_hash,
        )
    )
    if existing_name is not None and existing_name.content_hash != content_hash:
        raise HTTPException(
            status_code=409,
            detail="A connector with this name already exists in this project.",
        )
    if existing is not None:
        version = await db.scalar(
            select(AppVersion.version)
            .where(AppVersion.connector_profile_id == existing.id)
            .order_by(AppVersion.version.desc())
        )
        if version is not None:
            return _connector_out(existing, version)

    connector = ConnectorProfile(
        project_id=project_id,
        provider_id=provider_id,
        model=model,
        display_name=display_name,
        name_key=name_key,
        entry_point_type=payload.entry_point_type,
        settings=dict(settings),
        encrypted_credentials=(
            encrypt_secret(json.dumps(credentials, sort_keys=True))
            if credentials
            else None
        ),
        content_hash=content_hash,
        access_level=_access_level(payload.entry_point_type),
    )
    db.add(connector)
    await db.flush()
    latest_version = await db.scalar(
        select(func.max(AppVersion.version)).where(AppVersion.project_id == project_id)
    )
    version_number = (latest_version or 0) + 1
    db.add(
        AppVersion(
            project_id=project_id,
            connector_profile_id=connector.id,
            version=version_number,
            content_hash=content_hash,
            config_snapshot={
                "entry_point_type": payload.entry_point_type,
                "settings": settings,
                "provider_id": str(provider_id) if provider_id else None,
                "model": model,
            },
            access_level=connector.access_level,
        )
    )
    db.add(
        AuditLog(
            user_id=user.id,
            workspace_id=workspace_id,
            action="connector_saved",
            details={
                "project_id": str(project_id),
                "entry_point_type": payload.entry_point_type,
                "app_version": version_number,
            },
        )
    )
    await db.commit()
    await db.refresh(connector)
    return _connector_out(connector, version_number)


@router.patch(
    "/workspaces/{workspace_id}/projects/{project_id}/connectors/{connector_id}"
)
async def rename_connector(
    workspace_id: UUID,
    project_id: UUID,
    connector_id: UUID,
    payload: ConnectorRename,
    user: ProjectWriter,
    db: Annotated[AsyncSession, Depends(get_db)],
) -> dict[str, object]:
    await _get_project(db, workspace_id, project_id)
    connector = await db.scalar(
        select(ConnectorProfile).where(
            ConnectorProfile.id == connector_id,
            ConnectorProfile.project_id == project_id,
        )
    )
    if connector is None:
        raise HTTPException(status_code=404, detail="Connector not found")
    duplicate = await db.scalar(
        select(ConnectorProfile).where(
            ConnectorProfile.project_id == project_id,
            ConnectorProfile.name_key == _name_key(payload.name),
            ConnectorProfile.id != connector_id,
        )
    )
    if duplicate is not None:
        raise HTTPException(
            status_code=409,
            detail="A connector with this name already exists in this project.",
        )
    connector.display_name = payload.name.strip()
    connector.name_key = _name_key(payload.name)
    version = await db.scalar(
        select(AppVersion.version)
        .where(AppVersion.connector_profile_id == connector.id)
        .order_by(AppVersion.version.desc())
    )
    if version is None:
        raise HTTPException(status_code=409, detail="Connector version was not found")
    db.add(
        AuditLog(
            user_id=user.id,
            workspace_id=workspace_id,
            action="connector_renamed",
            details={"project_id": str(project_id), "connector_id": str(connector_id)},
        )
    )
    await db.commit()
    await db.refresh(connector)
    return _connector_out(connector, version)


@router.delete(
    "/workspaces/{workspace_id}/projects/{project_id}/connectors/{connector_id}"
)
async def delete_connector(
    workspace_id: UUID,
    project_id: UUID,
    connector_id: UUID,
    user: ProjectWriter,
    db: Annotated[AsyncSession, Depends(get_db)],
) -> dict[str, bool]:
    await _get_project(db, workspace_id, project_id)
    connector = await db.scalar(
        select(ConnectorProfile).where(
            ConnectorProfile.id == connector_id,
            ConnectorProfile.project_id == project_id,
        )
    )
    if connector is None:
        raise HTTPException(status_code=404, detail="Connector not found")
    version_ids = select(AppVersion.id).where(
        AppVersion.connector_profile_id == connector_id
    )
    if await db.scalar(
        select(EvalRun.id).where(EvalRun.app_version_id.in_(version_ids))
    ):
        raise HTTPException(
            status_code=409,
            detail="This connector is used by an evaluation run and cannot be deleted.",
        )
    await db.execute(
        delete(AppVersion).where(AppVersion.connector_profile_id == connector_id)
    )
    db.add(
        AuditLog(
            user_id=user.id,
            workspace_id=workspace_id,
            action="connector_deleted",
            details={"project_id": str(project_id), "connector_id": str(connector_id)},
        )
    )
    await db.delete(connector)
    await db.commit()
    return {"ok": True}


@router.get("/workspaces/{workspace_id}/projects/{project_id}/judge-profiles")
async def list_judge_profiles(
    workspace_id: UUID,
    project_id: UUID,
    _: Member,
    db: Annotated[AsyncSession, Depends(get_db)],
) -> list[dict[str, object]]:
    await _get_project(db, workspace_id, project_id)
    profiles = await db.scalars(
        select(JudgeProfile)
        .where(JudgeProfile.project_id == project_id)
        .order_by(JudgeProfile.role)
    )
    return [_judge_out(profile) for profile in profiles]


@router.put("/workspaces/{workspace_id}/projects/{project_id}/judge-profiles/{role}")
async def upsert_judge_profile(
    workspace_id: UUID,
    project_id: UUID,
    role: str,
    payload: JudgeProfileUpsert,
    user: ProjectWriter,
    db: Annotated[AsyncSession, Depends(get_db)],
) -> dict[str, object]:
    if role != payload.role:
        raise HTTPException(status_code=422, detail="Path role does not match payload")
    await _get_project(db, workspace_id, project_id)
    provider = await db.scalar(
        select(ProviderConfig).where(
            ProviderConfig.id == payload.provider_id,
            ProviderConfig.workspace_id == workspace_id,
        )
    )
    if provider is None:
        raise HTTPException(status_code=422, detail="Provider not found in workspace")
    model = payload.model or provider.test_model
    if not model:
        raise HTTPException(
            status_code=422,
            detail="Set a provider default model or specify a judge model.",
        )
    profile = await db.scalar(
        select(JudgeProfile).where(
            JudgeProfile.project_id == project_id,
            JudgeProfile.role == payload.role,
        )
    )
    if profile is None:
        profile = JudgeProfile(
            project_id=project_id,
            role=payload.role,
            provider_id=payload.provider_id,
            model=model,
            temperature=payload.temperature,
            rubric_prompt=payload.rubric_prompt,
            rubric_version=1,
        )
        db.add(profile)
    else:
        if profile.rubric_prompt != payload.rubric_prompt:
            profile.rubric_version += 1
        profile.provider_id = payload.provider_id
        profile.model = model
        profile.temperature = payload.temperature
        profile.rubric_prompt = payload.rubric_prompt
    db.add(
        AuditLog(
            user_id=user.id,
            workspace_id=workspace_id,
            action="judge_profile_updated",
            details={"project_id": str(project_id), "role": role},
        )
    )
    await db.commit()
    await db.refresh(profile)
    return _judge_out(profile)


def _project_out(project: Project) -> dict[str, object]:
    return {
        "id": project.id,
        "name": project.name,
        "description": project.description,
        "original_name": project.original_name,
        "duplicate_of": str(project.duplicate_of) if project.duplicate_of else None,
        "is_duplicate": project.duplicate_of is not None,
        "created_at": project.created_at.isoformat(),
    }


def _connector_out(connector: ConnectorProfile, app_version: int) -> dict[str, object]:
    settings = dict(connector.settings)
    settings.pop("_display_name", None)
    settings.pop("provider_id", None)
    settings.pop("model", None)
    return {
        "id": connector.id,
        "name": connector.display_name,
        "entry_point_type": connector.entry_point_type,
        "provider_id": str(connector.provider_id) if connector.provider_id else None,
        "model": connector.model,
        "settings": settings,
        "content_hash": connector.content_hash,
        "access_level": connector.access_level,
        "app_version": app_version,
        "created_at": connector.created_at.isoformat(),
        "has_credentials": connector.encrypted_credentials is not None,
    }


def _judge_out(profile: JudgeProfile) -> dict[str, object]:
    return {
        "id": profile.id,
        "role": profile.role,
        "provider_id": profile.provider_id,
        "model": profile.model,
        "temperature": profile.temperature,
        "rubric_prompt": profile.rubric_prompt,
        "rubric_version": profile.rubric_version,
    }


def _access_level(entry_point_type: str) -> str:
    if entry_point_type in {
        "PYTHON_FUNCTION",
        "PYTHON_SDK_TRACED",
        "PROMPT_APP",
        "BUILTIN_RAG_APP",
        "BUILTIN_AGENT_APP",
        "GIT_REPO",
        "PROXY_MODE",
    }:
        return "white-box"
    return "black-box"


async def _get_project(
    db: AsyncSession, workspace_id: UUID, project_id: UUID
) -> Project:
    project = await db.scalar(
        select(Project).where(
            Project.id == project_id,
            Project.workspace_id == workspace_id,
        )
    )
    if project is None:
        raise HTTPException(status_code=404, detail="Project not found")
    return project


async def _connector_provider_values(
    db: AsyncSession,
    workspace_id: UUID,
    provider_id: UUID | None,
    model: str | None,
) -> tuple[UUID | None, str | None]:
    if provider_id is None:
        return None, model
    provider = await db.scalar(
        select(ProviderConfig).where(
            ProviderConfig.id == provider_id,
            ProviderConfig.workspace_id == workspace_id,
        )
    )
    if provider is None:
        raise HTTPException(
            status_code=422,
            detail="The selected provider does not belong to this workspace.",
        )
    return provider_id, model or provider.test_model


async def _workspace_role(db: AsyncSession, workspace_id: UUID, user_id: UUID) -> str:
    from app.models import WorkspaceMembership

    membership = await db.scalar(
        select(WorkspaceMembership).where(
            WorkspaceMembership.workspace_id == workspace_id,
            WorkspaceMembership.user_id == user_id,
        )
    )
    if membership is None:
        raise HTTPException(status_code=403, detail="Workspace access denied")
    return membership.role


def _name_key(name: str) -> str:
    return name.strip().casefold()


async def _project_named(
    workspace_id: UUID, name_key: str, db: AsyncSession
) -> Project | None:
    projects = await db.scalars(
        select(Project).where(Project.workspace_id == workspace_id)
    )
    return next(
        (project for project in projects if project.name_key == name_key),
        None,
    )


async def _provider_named(
    workspace_id: UUID, name_key: str, db: AsyncSession
) -> ProviderConfig | None:
    providers = await db.scalars(
        select(ProviderConfig).where(ProviderConfig.workspace_id == workspace_id)
    )
    return next(
        (provider for provider in providers if provider.name_key == name_key),
        None,
    )


def _provider_base_url(payload: ProviderCreate) -> str:
    if (
        payload.default_model
        and payload.test_model
        and payload.default_model != payload.test_model
    ):
        raise HTTPException(
            status_code=422,
            detail="Specify either default_model or legacy test_model, not both.",
        )
    base_url = str(payload.base_url) if payload.base_url else None
    if payload.provider_type == "github_models":
        base_url = base_url or "https://models.github.ai/inference"
        parsed = urlsplit(base_url)
        if (
            parsed.scheme != "https"
            or parsed.hostname != "models.github.ai"
            or parsed.path.rstrip("/") not in {"/inference", "/inference/v1"}
        ):
            raise HTTPException(
                status_code=422,
                detail="GitHub Models must use https://models.github.ai/inference",
            )
        if payload.api_key is None or not payload.api_key.get_secret_value():
            raise HTTPException(
                status_code=422, detail="GitHub Models requires an API token"
            )
    elif payload.provider_type == "ollama":
        base_url = base_url or "http://host.docker.internal:11434/v1"
        base_url = normalize_provider_base_url(payload.provider_type, base_url)
    elif base_url is None:
        raise HTTPException(
            status_code=422, detail="A base URL is required for custom providers"
        )
    return base_url.rstrip("/")


def _provider_test_hash(payload: ProviderCreate, base_url: str) -> str:
    return fingerprint(
        {
            "name": _name_key(payload.name),
            "provider_type": payload.provider_type,
            "base_url": base_url,
            "default_model": _configured_model(payload),
            "api_key": payload.api_key.get_secret_value() if payload.api_key else None,
            "rpm": payload.rpm,
            "rpd": payload.rpd,
            "max_input_tokens": payload.max_input_tokens,
            "max_output_tokens": payload.max_output_tokens,
            "fallback_provider_ids": sorted(
                str(value) for value in payload.fallback_provider_ids
            ),
        }
    )


def _transient_provider(payload: ProviderCreate) -> ProviderConfig:
    base_url = _provider_base_url(payload)
    api_key = payload.api_key.get_secret_value() if payload.api_key else None
    return ProviderConfig(
        id=uuid4(),
        workspace_id=UUID(int=0),
        name=payload.name.strip(),
        name_key=_name_key(payload.name),
        provider_type=payload.provider_type,
        base_url=base_url,
        test_model=_configured_model(payload),
        api_key_encrypted=encrypt_secret(api_key) if api_key else None,
        rpm=payload.rpm,
        rpd=payload.rpd,
        max_input_tokens=payload.max_input_tokens,
        max_output_tokens=payload.max_output_tokens,
        fallback_provider_ids=[str(value) for value in payload.fallback_provider_ids],
    )


def _provider_matches(
    provider: ProviderConfig, payload: ProviderCreate, base_url: str
) -> bool:
    stored_key = (
        decrypt_secret(provider.api_key_encrypted)
        if provider.api_key_encrypted
        else None
    )
    supplied_key = payload.api_key.get_secret_value() if payload.api_key else None
    return (
        provider.name == payload.name.strip()
        and provider.provider_type == payload.provider_type
        and provider.base_url == base_url
        and provider.test_model == _configured_model(payload)
        and stored_key == supplied_key
        and provider.rpm == payload.rpm
        and provider.rpd == payload.rpd
        and provider.max_input_tokens == payload.max_input_tokens
        and provider.max_output_tokens == payload.max_output_tokens
        and provider.fallback_provider_ids
        == sorted(str(value) for value in payload.fallback_provider_ids)
    )


def _configured_model(payload: ProviderCreate) -> str | None:
    return (
        payload.default_model
        or payload.test_model
        or ("hermes3:8b" if payload.provider_type == "ollama" else None)
    )


async def _test_provider(
    provider: ProviderConfig, model: str | None
) -> dict[str, object]:
    try:
        return await gateway.test_connection(provider, model=model)
    except DailyQuotaPaused as exc:
        raise HTTPException(
            status_code=429,
            detail={
                "message": "Provider daily quota reached; connection test is paused",
                "retry_after_seconds": exc.retry_after_seconds,
            },
            headers={"Retry-After": str(exc.retry_after_seconds)},
        ) from exc
    except ProviderRequestError as exc:
        detail: dict[str, object] = {"message": str(exc)}
        if exc.upstream_status_code is not None:
            detail["upstream_status_code"] = exc.upstream_status_code
        if exc.upstream_body is not None:
            detail["upstream_body"] = exc.upstream_body
        raise HTTPException(status_code=502, detail=detail) from exc


def _provider_referenced(value: object, provider_id: UUID) -> bool:
    if isinstance(value, dict):
        return any(_provider_referenced(item, provider_id) for item in value.values())
    if isinstance(value, list):
        return any(_provider_referenced(item, provider_id) for item in value)
    return value == str(provider_id)
