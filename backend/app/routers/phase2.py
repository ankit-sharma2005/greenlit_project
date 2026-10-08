from __future__ import annotations

import json
import time
from datetime import UTC, datetime, timedelta
from typing import Annotated
from urllib.parse import urlsplit
from uuid import UUID, uuid4

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_db
from app.deps import require_roles
from app.models import (
    AppVersion,
    AuditLog,
    ConnectorProfile,
    ConnectorTest,
    JudgeProfile,
    Project,
    ProviderConfig,
    User,
)
from app.phase2_schemas import (
    ConnectorSaveRequest,
    ConnectorTestCallRequest,
    JudgeProfileUpsert,
    ProjectCreate,
    ProviderCreate,
)
from app.services.connectors import (
    connector_content_hash,
    entry_point_types,
    execute_test_call,
    provider_out,
    validate_connector_settings,
)
from app.services.llm_gateway import LLMGateway, ProviderRequestError
from app.services.rate_limit import DailyQuotaPaused
from app.services.secrets import encrypt_secret

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
    base_url = str(payload.base_url) if payload.base_url else None
    if payload.provider_type == "github_models":
        base_url = base_url or "https://models.github.ai/inference"
        parsed_base_url = urlsplit(base_url)
        if (
            parsed_base_url.scheme != "https"
            or parsed_base_url.hostname != "models.github.ai"
            or parsed_base_url.path.rstrip("/") not in {"/inference", "/inference/v1"}
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
        base_url = base_url or "http://localhost:11434/v1"
    else:
        if base_url is None:
            raise HTTPException(
                status_code=422, detail="A base URL is required for custom providers"
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
        name=payload.name,
        provider_type=payload.provider_type,
        base_url=base_url.rstrip("/"),
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
    await db.commit()
    await db.refresh(provider)
    return provider_out(provider)


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
    try:
        models = await gateway.test_connection(provider)
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
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    return {
        "ok": True,
        "models": models,
        "latency_ms": round((time.perf_counter() - started) * 1000, 2),
    }


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
    project = Project(
        workspace_id=workspace_id,
        name=payload.name,
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
    await db.commit()
    await db.refresh(project)
    return _project_out(project)


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
    credentials = {
        key: secret.get_secret_value() for key, secret in payload.credentials.items()
    }
    try:
        result = await execute_test_call(
            entry_point_type=payload.entry_point_type,
            settings=validated,
            input_text=payload.input,
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
        payload.entry_point_type, settings, credentials
    )
    tested_at = datetime.now(UTC).replace(tzinfo=None)
    test = ConnectorTest(
        id=uuid4(),
        workspace_id=workspace_id,
        user_id=user.id,
        entry_point_type=payload.entry_point_type,
        content_hash=content_hash,
        expires_at=tested_at + timedelta(minutes=15),
        created_at=tested_at,
    )
    db.add(test)
    await db.commit()
    return {"test_call_id": test.id, **result}


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
    credentials = {
        key: secret.get_secret_value() for key, secret in payload.credentials.items()
    }
    content_hash = connector_content_hash(
        payload.entry_point_type, settings, credentials
    )
    now = datetime.now(UTC).replace(tzinfo=None)
    test = await db.scalar(
        select(ConnectorTest).where(
            ConnectorTest.id == payload.test_call_id,
            ConnectorTest.workspace_id == workspace_id,
            ConnectorTest.user_id == user.id,
            ConnectorTest.entry_point_type == payload.entry_point_type,
            ConnectorTest.content_hash == content_hash,
            ConnectorTest.expires_at > now,
        )
    )
    if test is None:
        raise HTTPException(
            status_code=409,
            detail="Run a successful test call for these exact settings before saving",
        )

    connector = ConnectorProfile(
        project_id=project_id,
        entry_point_type=payload.entry_point_type,
        settings=settings,
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
            model=payload.model,
            temperature=payload.temperature,
            rubric_prompt=payload.rubric_prompt,
            rubric_version=1,
        )
        db.add(profile)
    else:
        if profile.rubric_prompt != payload.rubric_prompt:
            profile.rubric_version += 1
        profile.provider_id = payload.provider_id
        profile.model = payload.model
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
        "created_at": project.created_at.isoformat(),
    }


def _connector_out(connector: ConnectorProfile, app_version: int) -> dict[str, object]:
    return {
        "id": connector.id,
        "entry_point_type": connector.entry_point_type,
        "settings": connector.settings,
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
