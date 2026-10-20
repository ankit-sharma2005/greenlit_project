from __future__ import annotations

import json
import logging
from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import async_session_maker
from app.models import (
    AppVersion,
    ConnectorProfile,
    DatasetItem,
    EvalRun,
    EvalRunItem,
    User,
    WorkspaceMembership,
)
from app.services.connectors import execute_test_call, validate_connector_settings
from app.services.llm_gateway import LLMGateway
from app.services.metrics import score_run_item
from app.services.rate_limit import DailyQuotaPaused
from app.services.secrets import decrypt_secret

logger = logging.getLogger(__name__)
gateway = LLMGateway()
TERMINAL_RUN_STATUSES = {"completed", "failed", "cancelled"}


async def execute_eval_run_async(run_id: str, *, task_id: str) -> dict[str, object]:
    run_uuid = UUID(run_id)
    async with async_session_maker() as db:
        run = await db.get(EvalRun, run_uuid)
        if run is None:
            return {"status": "missing"}
        if run.status in TERMINAL_RUN_STATUSES or run.status == "paused":
            return {"status": run.status}
        if (
            run.status == "running"
            and run.celery_task_id is not None
            and run.celery_task_id != task_id
        ):
            return {"status": "already-running"}
        run.status = "running"
        run.celery_task_id = task_id
        run.pause_reason = None
        if run.started_at is None:
            run.started_at = _now()
        await db.commit()

    while True:
        async with async_session_maker() as db:
            run = await db.get(EvalRun, run_uuid)
            if run is None:
                return {"status": "missing"}
            if run.status in TERMINAL_RUN_STATUSES:
                return {"status": run.status}
            if run.pause_requested or run.status == "paused":
                run.status = "paused"
                await db.commit()
                return {"status": "paused"}
            item = await db.scalar(
                select(EvalRunItem)
                .where(
                    EvalRunItem.run_id == run_uuid,
                    EvalRunItem.status.in_(("pending", "running")),
                )
                .order_by(EvalRunItem.created_at, EvalRunItem.id)
                .limit(1)
                .with_for_update(skip_locked=True)
            )
            if item is None:
                running_count = int(
                    await db.scalar(
                        select(func.count())
                        .select_from(EvalRunItem)
                        .where(
                            EvalRunItem.run_id == run_uuid,
                            EvalRunItem.status == "running",
                        )
                    )
                    or 0
                )
                if running_count:
                    await db.commit()
                    return {"status": "running"}
                run.completed_items = int(
                    await db.scalar(
                        select(func.count())
                        .select_from(EvalRunItem)
                        .where(
                            EvalRunItem.run_id == run_uuid,
                            EvalRunItem.status == "completed",
                        )
                    )
                    or 0
                )
                run.failed_items = int(
                    await db.scalar(
                        select(func.count())
                        .select_from(EvalRunItem)
                        .where(
                            EvalRunItem.run_id == run_uuid,
                            EvalRunItem.status == "failed",
                        )
                    )
                    or 0
                )
                run.status = "completed"
                run.finished_at = _now()
                run.celery_task_id = None
                await db.commit()
                return {
                    "status": "completed",
                    "completed_items": run.completed_items,
                    "failed_items": run.failed_items,
                }
            item.status = "running"
            item.attempts += 1
            item.error = None
            await db.commit()
            run_item_id = item.id
            dataset_item_id = item.dataset_item_id

        try:
            result = await _execute_one_item(run_uuid, run_item_id, dataset_item_id)
            trace = result.get("trace")
            if isinstance(trace, dict):
                await score_run_item(
                    run_uuid,
                    run_item_id,
                    dataset_item_id,
                    trace,
                )
        except DailyQuotaPaused:
            async with async_session_maker() as db:
                item = await db.get(EvalRunItem, run_item_id)
                run = await db.get(EvalRun, run_uuid)
                if item is not None and item.status == "running":
                    item.status = "pending"
                if run is not None and run.status not in TERMINAL_RUN_STATUSES:
                    run.status = "paused"
                    run.pause_requested = True
                    run.pause_reason = "quota"
                    run.celery_task_id = None
                await db.commit()
            return {"status": "paused", "reason": "quota"}
        except Exception as exc:
            logger.warning(
                "Evaluation item failed",
                extra={
                    "run_id": str(run_uuid),
                    "run_item_id": str(run_item_id),
                    "exception_type": type(exc).__name__,
                },
            )
            async with async_session_maker() as db:
                item = await db.get(EvalRunItem, run_item_id)
                if item is not None:
                    item.status = "failed"
                    item.error = _safe_error(exc)
                    item.completed_at = _now()
                await _refresh_run_counts(db, run_uuid)
                await db.commit()
            continue

        async with async_session_maker() as db:
            item = await db.get(EvalRunItem, run_item_id)
            run = await db.get(EvalRun, run_uuid)
            if item is not None and item.status == "running":
                trace = result.get("trace")
                item.trace = trace if isinstance(trace, dict) else {}
                output = item.trace.get("output")
                item.output = (
                    output
                    if isinstance(output, str)
                    else json.dumps(output, ensure_ascii=False)
                    if output is not None
                    else None
                )
                item.status = "completed"
                item.completed_at = _now()
            if run is not None:
                await _refresh_run_counts(db, run_uuid)
                if run.status == "running" and not run.pause_requested:
                    run.celery_task_id = task_id
            await db.commit()


async def _execute_one_item(
    run_id: UUID, run_item_id: UUID, dataset_item_id: UUID
) -> dict[str, object]:
    async with async_session_maker() as db:
        run = await db.get(EvalRun, run_id)
        item = await db.get(DatasetItem, dataset_item_id)
        run_item = await db.get(EvalRunItem, run_item_id)
        if run is None or item is None or run_item is None:
            raise LookupError("Evaluation run item no longer exists")
        app_version = await db.get(AppVersion, run.app_version_id)
        if app_version is None or app_version.connector_profile_id is None:
            raise LookupError("The selected app version has no connector")
        connector = await db.get(ConnectorProfile, app_version.connector_profile_id)
        if connector is None:
            raise LookupError("The selected connector no longer exists")
        user = await db.get(User, run.created_by)
        if user is None:
            raise LookupError("The run creator no longer exists")
        membership = await db.scalar(
            select(WorkspaceMembership).where(
                WorkspaceMembership.workspace_id == run.workspace_id,
                WorkspaceMembership.user_id == user.id,
            )
        )
        if membership is None:
            raise LookupError("The run creator no longer has workspace access")
        connector_settings = dict(connector.settings)
        legacy_provider_id = connector_settings.pop("provider_id", None)
        legacy_model = connector_settings.pop("model", None)
        connector_settings.pop("_display_name", None)
        try:
            validated_settings, _ = validate_connector_settings(
                connector.entry_point_type, connector_settings
            )
        except ValueError as exc:
            raise ValueError(
                "The saved connector is not available for evaluation"
            ) from exc
        credentials: dict[str, str] = {}
        if connector.encrypted_credentials:
            decrypted = json.loads(decrypt_secret(connector.encrypted_credentials))
            if not isinstance(decrypted, dict) or not all(
                isinstance(key, str) and isinstance(value, str)
                for key, value in decrypted.items()
            ):
                raise ValueError("Saved connector credentials are invalid")
            credentials = decrypted
        return await execute_test_call(
            entry_point_type=connector.entry_point_type,
            settings=validated_settings,
            provider_id=connector.provider_id
            or (UUID(str(legacy_provider_id)) if legacy_provider_id else None),
            model=connector.model or (str(legacy_model) if legacy_model else None),
            input_text=item.input_text,
            conversation_history=None,
            credentials=credentials,
            workspace_id=run.workspace_id,
            user_role=membership.role,
            db=db,
            gateway=gateway,
        )


async def _refresh_run_counts(db: AsyncSession, run_id: UUID) -> None:
    run = await db.get(EvalRun, run_id)
    if run is None:
        return
    run.completed_items = int(
        await db.scalar(
            select(func.count())
            .select_from(EvalRunItem)
            .where(
                EvalRunItem.run_id == run_id,
                EvalRunItem.status == "completed",
            )
        )
        or 0
    )
    run.failed_items = int(
        await db.scalar(
            select(func.count())
            .select_from(EvalRunItem)
            .where(EvalRunItem.run_id == run_id, EvalRunItem.status == "failed")
        )
        or 0
    )


def _safe_error(exc: Exception) -> str:
    return f"{type(exc).__name__}: connector execution failed"


def _now() -> datetime:
    return datetime.now(UTC).replace(tzinfo=None)
