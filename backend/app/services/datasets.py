"""Dataset upload service: parsing, column detection, hashing and versioning.

Nothing here commits: rows are added to the caller's transaction and the API layer
(or test) performs the commit, matching the audit helper's convention.

Errors are raised as :class:`DatasetError` with a machine-readable ``code`` that the
API layer maps to an HTTP status (``duplicate_name`` -> 409, the rest -> 400/422).
"""

from __future__ import annotations

import csv
import hashlib
import io
import json
import uuid
from collections.abc import Mapping, Sequence
from typing import Any

from openpyxl import load_workbook
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models import (
    Dataset,
    DatasetColumnMapping,
    DatasetItem,
    DatasetVersion,
    utcnow,
)

FILE_FORMATS = ("csv", "json", "jsonl", "xlsx")

# Detection candidates per role, checked in this order. The first pass matches a
# column name exactly (case-insensitive); the second pass accepts a column whose
# name contains one of the candidates, over columns not claimed by an earlier role.
ROLE_CANDIDATES: dict[str, tuple[str, ...]] = {
    "input": ("input", "question", "prompt", "query", "user_input", "user_message"),
    "output": ("output", "answer", "response", "prediction", "completion", "result"),
    "id": ("id", "case_id", "row_id", "example_id"),
    "retrieved_context": (
        "retrieved_context",
        "context",
        "contexts",
        "sources",
        "documents",
        "chunks",
    ),
    "latency_ms": ("latency_ms", "latency", "duration_ms"),
    "tokens_in": ("tokens_in", "prompt_tokens", "input_tokens"),
    "tokens_out": ("tokens_out", "completion_tokens", "output_tokens"),
}

# Override dict key accepted per role: the schema field name, or the bare role name.
_ROLE_FIELDS: dict[str, tuple[str, str]] = {
    "input": ("input_column", "input"),
    "output": ("output_column", "output"),
    "id": ("id_column", "id"),
    "retrieved_context": ("retrieved_context_column", "retrieved_context"),
    "latency_ms": ("latency_ms_column", "latency_ms"),
    "tokens_in": ("tokens_in_column", "tokens_in"),
    "tokens_out": ("tokens_out_column", "tokens_out"),
}


class DatasetError(Exception):
    """Upload failed; ``code`` is mapped to an HTTP status by the API layer."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


def content_hash(raw_content: bytes) -> str:
    """SHA-256 hex digest of the uploaded bytes."""
    return hashlib.sha256(raw_content).hexdigest()


def detect_file_format(filename: str) -> str:
    """Map a filename extension to a supported format."""
    extension = filename.rsplit(".", 1)[-1].lower() if "." in filename else ""
    if extension in FILE_FORMATS:
        return extension
    raise DatasetError(
        "unsupported_format",
        f"Cannot detect the file format of '{filename}'. "
        f"Supported extensions: {', '.join('.' + fmt for fmt in FILE_FORMATS)}.",
    )


def _normalize(name: object) -> str:
    return str(name).strip().lower()


def detect_columns(columns: Sequence[str]) -> dict[str, str | None]:
    """Best-guess mapping of roles to file columns; missing roles are None."""
    normalized = {_normalize(column): column for column in columns}
    result: dict[str, str | None] = {}
    for role in ROLE_CANDIDATES:
        result[role] = None
    claimed: set[str] = set()

    # Pass 1: exact (case-insensitive) candidate names, in role priority order.
    for role, candidates in ROLE_CANDIDATES.items():
        for candidate in candidates:
            original = normalized.get(candidate)
            if original is not None and original not in claimed:
                result[role] = original
                claimed.add(original)
                break

    # Pass 2: substring match over columns no role claimed yet.
    for role, candidates in ROLE_CANDIDATES.items():
        if result[role] is not None:
            continue
        for key, original in normalized.items():
            if original in claimed:
                continue
            if any(candidate in key for candidate in candidates):
                result[role] = original
                claimed.add(original)
                break

    return result


def _parse_csv(raw_content: bytes) -> tuple[list[str], list[dict[str, Any]]]:
    try:
        text = raw_content.decode("utf-8-sig")
    except UnicodeDecodeError as exc:
        raise DatasetError("parse_error", f"The CSV file is not valid UTF-8: {exc}") from exc
    reader = csv.DictReader(io.StringIO(text))
    if not reader.fieldnames:
        raise DatasetError("parse_error", "The CSV file has no header row.")
    columns = [str(name).strip() for name in reader.fieldnames]
    rows: list[dict[str, Any]] = []
    for row in reader:
        rows.append({str(key): value for key, value in row.items() if key is not None})
    return columns, rows


def _extract_json_rows(payload: Any, source: str) -> list[dict[str, Any]]:
    if isinstance(payload, dict):
        for key in ("items", "data", "rows"):
            if isinstance(payload.get(key), list):
                payload = payload[key]
                break
    if not isinstance(payload, list):
        raise DatasetError(
            "parse_error",
            f"{source} must be a list of objects "
            "(or an object with an 'items', 'data' or 'rows' list).",
        )
    rows: list[dict[str, Any]] = []
    for index, entry in enumerate(payload):
        if not isinstance(entry, dict):
            raise DatasetError("parse_error", f"Row {index} of the {source} is not an object.")
        rows.append(entry)
    return rows


def _parse_json(raw_content: bytes) -> tuple[list[str], list[dict[str, Any]]]:
    try:
        payload = json.loads(raw_content)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise DatasetError("parse_error", f"Invalid JSON: {exc}") from exc
    rows = _extract_json_rows(payload, "JSON file")
    columns = list(dict.fromkeys(key for row in rows for key in row))
    return columns, rows


def _parse_jsonl(raw_content: bytes) -> tuple[list[str], list[dict[str, Any]]]:
    try:
        text = raw_content.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise DatasetError("parse_error", f"The JSONL file is not valid UTF-8: {exc}") from exc
    rows: list[dict[str, Any]] = []
    columns: list[str] = []
    for line_no, line in enumerate(text.splitlines(), start=1):
        stripped = line.strip()
        if not stripped:
            continue
        try:
            entry = json.loads(stripped)
        except json.JSONDecodeError as exc:
            raise DatasetError("parse_error", f"Line {line_no} is not valid JSON: {exc}") from exc
        if not isinstance(entry, dict):
            raise DatasetError("parse_error", f"Line {line_no} is not a JSON object.")
        rows.append(entry)
        for key in entry:
            if key not in columns:
                columns.append(key)
    if not rows:
        raise DatasetError("parse_error", "The JSONL file has no data rows.")
    return columns, rows


def _parse_xlsx(raw_content: bytes) -> tuple[list[str], list[dict[str, Any]]]:
    try:
        workbook = load_workbook(io.BytesIO(raw_content), read_only=True, data_only=True)
    except Exception as exc:  # openpyxl raises several types for corrupt files
        raise DatasetError("parse_error", f"Could not read the XLSX file: {exc}") from exc
    try:
        sheet = workbook.worksheets[0]
        row_iter = sheet.iter_rows(values_only=True)
        try:
            header = next(row_iter)
        except StopIteration as exc:
            raise DatasetError("parse_error", "The XLSX sheet is empty.") from exc
        columns = [str(cell).strip() if cell is not None else "" for cell in header]
        if not any(columns):
            raise DatasetError("parse_error", "The XLSX first row has no column headers.")
        rows: list[dict[str, Any]] = []
        for values in row_iter:
            if all(value is None for value in values):
                continue
            rows.append(
                {
                    columns[index]: values[index]
                    for index in range(min(len(columns), len(values)))
                    if columns[index]
                }
            )
    finally:
        workbook.close()
    kept = [column for column in columns if column]
    return kept, rows


def parse_rows(file_format: str, raw_content: bytes) -> tuple[list[str], list[dict[str, Any]]]:
    """Parse an uploaded file into ``(columns, rows)``."""
    if not raw_content:
        raise DatasetError("parse_error", "The uploaded file is empty.")
    if file_format == "csv":
        return _parse_csv(raw_content)
    if file_format == "json":
        return _parse_json(raw_content)
    if file_format == "jsonl":
        return _parse_jsonl(raw_content)
    if file_format == "xlsx":
        return _parse_xlsx(raw_content)
    raise DatasetError(
        "unsupported_format",
        f"Unsupported file format '{file_format}'. Supported: {', '.join(FILE_FORMATS)}.",
    )


def _resolve_mapping(
    columns: Sequence[str],
    detected: dict[str, str | None],
    overrides: Mapping[str, str],
) -> tuple[dict[str, str | None], bool]:
    """Merge detection with user overrides and validate every resolved column."""
    mapping: dict[str, str | None] = dict(detected)
    available = set(columns)
    overridden: set[str] = set()
    for role, (field_name, bare_name) in _ROLE_FIELDS.items():
        value = overrides.get(field_name, overrides.get(bare_name))
        if value:
            overridden.add(role)
            mapping[role] = value

    # Explicit overrides are user intent: naming a column that does not exist is an error.
    for role in overridden:
        column = mapping[role]
        if column is not None and column not in available:
            raise DatasetError(
                "missing_columns",
                f"Column '{column}' does not exist in the file. "
                f"Available columns: {', '.join(sorted(available))}.",
            )

    # Inherited columns absent from a new file are dropped; the required-role
    # check below then fails for input/output, while optional roles vanish quietly.
    for role, column in mapping.items():
        if role in overridden or column is None or column in available:
            continue
        mapping[role] = None

    missing = [role for role in ("input", "output") if not mapping.get(role)]
    if missing:
        raise DatasetError(
            "missing_columns",
            f"Could not detect the required column(s): {', '.join(missing)}. "
            f"Available columns: {', '.join(sorted(available))}. "
            "Map them explicitly to continue.",
        )
    return mapping, not bool(overrides)


def _build_mapping_row(
    dataset_id: uuid.UUID, mapping: dict[str, str | None], detected: bool
) -> DatasetColumnMapping:
    return DatasetColumnMapping(
        dataset_id=dataset_id,
        input_column=mapping["input"] or "",
        output_column=mapping["output"] or "",
        id_column=mapping["id"],
        retrieved_context_column=mapping["retrieved_context"],
        latency_ms_column=mapping["latency_ms"],
        tokens_in_column=mapping["tokens_in"],
        tokens_out_column=mapping["tokens_out"],
        detected=detected,
    )


def create_dataset(
    db: Session,
    *,
    owner_id: uuid.UUID,
    name: str,
    source_filename: str,
    raw_content: bytes,
    file_format: str | None = None,
    column_overrides: Mapping[str, str] | None = None,
) -> Dataset:
    """Store an uploaded dataset with its first version and items; caller commits."""
    fmt = (file_format or detect_file_format(source_filename)).lower()
    if fmt not in FILE_FORMATS:
        raise DatasetError(
            "unsupported_format",
            f"Unsupported file format '{fmt}'. Supported: {', '.join(FILE_FORMATS)}.",
        )

    existing = db.scalar(select(Dataset).where(Dataset.owner_id == owner_id, Dataset.name == name))
    if existing is not None:
        raise DatasetError(
            "duplicate_name",
            f'A dataset named "{name}" already exists. Pick another name.',
        )

    columns, rows = parse_rows(fmt, raw_content)
    if not rows:
        raise DatasetError("parse_error", "The file has no data rows.")
    mapping, detected = _resolve_mapping(
        columns, detect_columns(columns), dict(column_overrides or {})
    )

    dataset = Dataset(
        owner_id=owner_id,
        name=name,
        source_filename=source_filename,
        file_format=fmt,
        raw_content=raw_content,
        content_hash=content_hash(raw_content),
    )
    db.add(dataset)
    db.flush()

    db.add(_build_mapping_row(dataset.id, mapping, detected))
    version = DatasetVersion(
        dataset_id=dataset.id,
        version_no=1,
        content_hash=dataset.content_hash,
        row_count=len(rows),
        columns_snapshot={"columns": columns},
    )
    db.add(version)
    db.flush()
    db.add_all(
        DatasetItem(dataset_version_id=version.id, row_index=index, data=row)
        for index, row in enumerate(rows)
    )
    db.flush()
    return dataset


def add_dataset_version(
    db: Session,
    dataset: Dataset,
    raw_content: bytes,
) -> DatasetVersion:
    """Append a new immutable version to an existing dataset; caller commits.

    The new file must contain the dataset's canonical mapped columns; a re-upload
    with different columns belongs to a new dataset.
    """
    columns, rows = parse_rows(dataset.file_format, raw_content)
    if not rows:
        raise DatasetError("parse_error", "The file has no data rows.")

    mapping_row = dataset.columns
    existing: dict[str, str | None] = {
        "input": getattr(mapping_row, "input_column", None),
        "output": getattr(mapping_row, "output_column", None),
        "id": getattr(mapping_row, "id_column", None),
        "retrieved_context": getattr(mapping_row, "retrieved_context_column", None),
        "latency_ms": getattr(mapping_row, "latency_ms_column", None),
        "tokens_in": getattr(mapping_row, "tokens_in_column", None),
        "tokens_out": getattr(mapping_row, "tokens_out_column", None),
    }
    _mapping, _detected = _resolve_mapping(columns, existing, {})

    next_no = (
        db.scalar(
            select(func.max(DatasetVersion.version_no)).where(
                DatasetVersion.dataset_id == dataset.id
            )
        )
        or 0
    ) + 1
    digest = content_hash(raw_content)
    version = DatasetVersion(
        dataset_id=dataset.id,
        version_no=next_no,
        content_hash=digest,
        row_count=len(rows),
        columns_snapshot={"columns": columns},
    )
    db.add(version)
    db.flush()
    db.add_all(
        DatasetItem(dataset_version_id=version.id, row_index=index, data=row)
        for index, row in enumerate(rows)
    )
    dataset.raw_content = raw_content
    dataset.content_hash = digest
    db.flush()
    return version


def approve_dataset_version(
    db: Session,
    dataset: Dataset,
    version_no: int,
    approver_id: uuid.UUID,
) -> DatasetVersion:
    """Mark one of a dataset's versions approved; caller commits.

    Approval is one-way: an already-approved version raises ``already_approved``
    rather than silently moving the approver or timestamp.
    """
    version = db.scalar(
        select(DatasetVersion).where(
            DatasetVersion.dataset_id == dataset.id,
            DatasetVersion.version_no == version_no,
        )
    )
    if version is None:
        raise DatasetError(
            "version_not_found",
            f"Version {version_no} does not exist for this dataset.",
        )
    if version.approved_at is not None:
        raise DatasetError(
            "already_approved",
            f"Version {version_no} is already approved.",
        )
    version.approved_by = approver_id
    version.approved_at = utcnow()
    db.flush()
    return version
