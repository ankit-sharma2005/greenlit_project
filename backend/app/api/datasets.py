"""Dataset endpoints: upload, listing, detail and versions (M4a)."""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, UploadFile
from pydantic import ValidationError
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.db import get_db
from app.deps import get_current_user
from app.models import Dataset, DatasetItem, DatasetVersion, Provider, User
from app.schemas.datasets import (
    ColumnOverrides,
    DatasetItemListResponse,
    DatasetItemRead,
    DatasetListResponse,
    DatasetRead,
    DatasetVersionRead,
    GenerationRequest,
)
from app.services.audit import record
from app.services.datasets import (
    DatasetError,
    add_dataset_version,
    approve_dataset_version,
    create_dataset,
)
from app.services.generation import (
    ChatFn,
    GenerationError,
    create_generated_version,
    generate_test_cases,
    get_chat_fn,
)

router = APIRouter(prefix="/api/v1/datasets", tags=["datasets"])

MAX_UPLOAD_BYTES = 10 * 1024 * 1024


_ERROR_STATUS_BY_CODE = {
    "duplicate_name": 409,
    "already_approved": 409,
    "version_not_found": 404,
}


def _dataset_error(exc: DatasetError) -> HTTPException:
    status = _ERROR_STATUS_BY_CODE.get(exc.code, 400)
    return HTTPException(status_code=status, detail=exc.message)


def _owned_dataset(db: Session, dataset_id: uuid.UUID, user: User) -> Dataset:
    """404 for datasets that are missing or belong to someone else."""
    dataset = db.get(Dataset, dataset_id)
    if dataset is None or dataset.owner_id != user.id:
        raise HTTPException(status_code=404, detail="Dataset not found.")
    return dataset


def _parse_overrides(raw: str | None) -> dict[str, str] | None:
    if raw is None or not raw.strip():
        return None
    try:
        overrides = ColumnOverrides.model_validate_json(raw)
    except ValidationError:
        raise HTTPException(
            status_code=422,
            detail="column_overrides must be a JSON object of column names.",
        ) from None
    dumped: dict[str, str] = overrides.model_dump(exclude_none=True)
    return dumped


@router.post("", response_model=DatasetRead, status_code=201)
def upload_dataset(
    name: str = Form(..., min_length=1, max_length=120),
    column_overrides: str | None = Form(default=None),
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> DatasetRead:
    """Upload a dataset file (csv/json/jsonl/xlsx); creates version 1 with its items."""
    if not file.filename:
        raise HTTPException(status_code=400, detail="No file was attached.")
    raw_content = file.file.read(MAX_UPLOAD_BYTES + 1)
    if len(raw_content) > MAX_UPLOAD_BYTES:
        raise HTTPException(
            status_code=413,
            detail="That file is larger than 10 MB. Trim it or split it into several datasets.",
        )
    overrides = _parse_overrides(column_overrides)
    try:
        dataset = create_dataset(
            db,
            owner_id=user.id,
            name=name,
            source_filename=file.filename,
            raw_content=raw_content,
            column_overrides=overrides,
        )
        record(
            db,
            "dataset.upload",
            actor_id=user.id,
            target_type="dataset",
            target_id=str(dataset.id),
            metadata={"name": dataset.name, "file_format": dataset.file_format},
        )
        db.commit()
    except DatasetError as exc:
        db.rollback()
        raise _dataset_error(exc) from exc
    return DatasetRead.model_validate(dataset)


@router.get("", response_model=DatasetListResponse)
def list_datasets(
    limit: int = Query(default=20, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> DatasetListResponse:
    """The signed-in user's datasets, newest first."""
    owned = Dataset.owner_id == user.id
    total = db.scalar(select(func.count()).select_from(Dataset).where(owned)) or 0
    datasets = db.scalars(
        select(Dataset).where(owned).order_by(Dataset.created_at.desc()).limit(limit).offset(offset)
    ).all()
    return DatasetListResponse(
        items=[DatasetRead.model_validate(dataset) for dataset in datasets],
        total=total,
        limit=limit,
        offset=offset,
    )


@router.get("/{dataset_id}", response_model=DatasetRead)
def get_dataset(
    dataset_id: uuid.UUID,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> DatasetRead:
    """Fetch one of your datasets, including its mapping and versions."""
    return DatasetRead.model_validate(_owned_dataset(db, dataset_id, user))


@router.get("/{dataset_id}/versions", response_model=list[DatasetVersionRead])
def list_dataset_versions(
    dataset_id: uuid.UUID,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> list[DatasetVersionRead]:
    """Version history for one of your datasets, oldest first."""
    dataset = _owned_dataset(db, dataset_id, user)
    versions = db.scalars(
        select(DatasetVersion)
        .where(DatasetVersion.dataset_id == dataset.id)
        .order_by(DatasetVersion.version_no)
    ).all()
    return [DatasetVersionRead.model_validate(version) for version in versions]


@router.post("/{dataset_id}/versions", response_model=DatasetVersionRead, status_code=201)
def upload_dataset_version(
    dataset_id: uuid.UUID,
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> DatasetVersionRead:
    """Append a new version by re-uploading the file (same required columns as v1)."""
    dataset = _owned_dataset(db, dataset_id, user)
    if not file.filename:
        raise HTTPException(status_code=400, detail="No file was attached.")
    raw_content = file.file.read(MAX_UPLOAD_BYTES + 1)
    if len(raw_content) > MAX_UPLOAD_BYTES:
        raise HTTPException(
            status_code=413,
            detail="That file is larger than 10 MB. Trim it or split it into several datasets.",
        )
    try:
        version = add_dataset_version(db, dataset, raw_content)
        record(
            db,
            "dataset.version_added",
            actor_id=user.id,
            target_type="dataset",
            target_id=str(dataset.id),
            metadata={"version_no": version.version_no, "row_count": version.row_count},
        )
        db.commit()
    except DatasetError as exc:
        db.rollback()
        raise _dataset_error(exc) from exc
    return DatasetVersionRead.model_validate(version)


@router.post(
    "/{dataset_id}/versions/{version_no}/approve",
    response_model=DatasetVersionRead,
)
def approve_version(
    dataset_id: uuid.UUID,
    version_no: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> DatasetVersionRead:
    """Approve a version (once); runs may only use approved versions."""
    dataset = _owned_dataset(db, dataset_id, user)
    try:
        version = approve_dataset_version(db, dataset, version_no, approver_id=user.id)
        record(
            db,
            "dataset.approved",
            actor_id=user.id,
            target_type="dataset",
            target_id=str(dataset.id),
            metadata={"version_no": version.version_no},
        )
        db.commit()
    except DatasetError as exc:
        db.rollback()
        raise _dataset_error(exc) from exc
    return DatasetVersionRead.model_validate(version)


@router.delete("/{dataset_id}", status_code=204, response_model=None)
def delete_dataset(
    dataset_id: uuid.UUID,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> None:
    """Delete one of your datasets; its mapping, versions and items cascade away."""
    dataset = _owned_dataset(db, dataset_id, user)
    record(
        db,
        "dataset.delete",
        actor_id=user.id,
        target_type="dataset",
        target_id=str(dataset.id),
        metadata={"name": dataset.name},
    )
    db.delete(dataset)
    db.commit()


@router.post("/{dataset_id}/generate", response_model=DatasetVersionRead, status_code=201)
def generate_version(
    dataset_id: uuid.UUID,
    payload: GenerationRequest,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
    chat: ChatFn = Depends(get_chat_fn),
) -> DatasetVersionRead:
    """Generate N test cases into a new draft version; approve it to make it usable."""
    dataset = _owned_dataset(db, dataset_id, user)
    provider = db.get(Provider, payload.provider_id)
    if provider is None:
        raise HTTPException(status_code=404, detail="Provider not found.")
    try:
        cases = generate_test_cases(
            provider,
            count=payload.count,
            source_text=payload.source_text,
            chat=chat,
        )
        version = create_generated_version(db, dataset, cases)
        record(
            db,
            "dataset.generated",
            actor_id=user.id,
            target_type="dataset",
            target_id=str(dataset.id),
            metadata={"version_no": version.version_no, "count": version.row_count},
        )
        db.commit()
    except GenerationError as exc:
        db.rollback()
        raise HTTPException(status_code=502, detail=exc.message) from exc
    return DatasetVersionRead.model_validate(version)


@router.get(
    "/{dataset_id}/versions/{version_no}/items",
    response_model=DatasetItemListResponse,
)
def list_version_items(
    dataset_id: uuid.UUID,
    version_no: int,
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> DatasetItemListResponse:
    """Preview a version's items (the generated-test preview, oldest row first)."""
    dataset = _owned_dataset(db, dataset_id, user)
    version = db.scalar(
        select(DatasetVersion).where(
            DatasetVersion.dataset_id == dataset.id,
            DatasetVersion.version_no == version_no,
        )
    )
    if version is None:
        raise HTTPException(
            status_code=404,
            detail=f"Version {version_no} does not exist for this dataset.",
        )
    owned = DatasetItem.dataset_version_id == version.id
    total = db.scalar(select(func.count()).select_from(DatasetItem).where(owned)) or 0
    items = db.scalars(
        select(DatasetItem).where(owned).order_by(DatasetItem.row_index).limit(limit).offset(offset)
    ).all()
    return DatasetItemListResponse(
        items=[DatasetItemRead.model_validate(item) for item in items],
        total=total,
        limit=limit,
        offset=offset,
    )
