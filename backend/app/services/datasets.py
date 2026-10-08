from __future__ import annotations

import csv
import hashlib
import io
import json
from collections import Counter
from collections.abc import Mapping, Sequence
from datetime import date, datetime
from typing import Literal
from zipfile import BadZipFile

from openpyxl import load_workbook
from openpyxl.utils.exceptions import InvalidFileException
from pydantic import BaseModel, ConfigDict, Field, ValidationError

from app.phase3_schemas import DatasetColumnMapping

MAX_UPLOAD_BYTES = 10 * 1024 * 1024
MAX_DATASET_ITEMS = 5000
ALLOWED_CATEGORIES = {"normal", "edge", "adversarial", "safety"}
ALLOWED_SPLITS = {"dev", "test"}


class DatasetItemDraft(BaseModel):
    model_config = ConfigDict(extra="forbid")

    input_text: str = Field(min_length=1, max_length=20_000)
    reference_answer: str | None = Field(default=None, max_length=20_000)
    reference_context: str | None = Field(default=None, max_length=20_000)
    category: str = "normal"
    provenance: Literal["uploaded", "synthetic", "red-team", "production-sample"]
    split: Literal["dev", "test"] = "dev"
    data: dict[str, object] = Field(default_factory=dict)


def parse_upload_records(
    filename: str, content: bytes
) -> tuple[list[dict[str, object]], list[dict[str, object]]]:
    if len(content) > MAX_UPLOAD_BYTES:
        raise ValueError("Upload exceeds the 10 MiB limit")
    extension = filename.rsplit(".", maxsplit=1)[-1].lower() if "." in filename else ""
    if extension == "xlsx":
        text = ""
    else:
        try:
            text = content.decode("utf-8-sig")
        except UnicodeDecodeError as exc:
            raise ValueError("Upload must be UTF-8 encoded") from exc
    if extension == "csv":
        reader = csv.DictReader(io.StringIO(text, newline=""))
        if not reader.fieldnames:
            raise ValueError("CSV file must have a header row")
        records: list[dict[str, object]] = []
        for row_number, row in enumerate(reader, start=2):
            if None in row:
                records.append({"__row_error__": f"Row {row_number} has extra columns"})
                continue
            records.append(
                {str(key): value for key, value in row.items() if key is not None}
            )
        return records, []
    if extension == "json":
        try:
            data: object = json.loads(text)
        except json.JSONDecodeError as exc:
            raise ValueError(f"Invalid JSON at line {exc.lineno}: {exc.msg}") from exc
        if isinstance(data, dict) and isinstance(data.get("items"), list):
            data = data["items"]
        if not isinstance(data, list):
            raise ValueError("JSON upload must be an array of objects")
        json_records, json_errors = _validate_records(data)
        return json_records, json_errors
    if extension == "jsonl":
        records = []
        errors: list[dict[str, object]] = []
        for line_number, line in enumerate(text.splitlines(), start=1):
            if not line.strip():
                continue
            try:
                value: object = json.loads(line)
            except json.JSONDecodeError as exc:
                errors.append(
                    {
                        "row": line_number,
                        "message": f"Invalid JSON: {exc.msg}",
                    }
                )
                continue
            if not isinstance(value, dict):
                errors.append(
                    {"row": line_number, "message": "Each JSONL row must be an object"}
                )
                continue
            records.append({str(key): item for key, item in value.items()})
        return records, errors
    if extension == "xlsx":
        try:
            workbook = load_workbook(
                io.BytesIO(content), read_only=True, data_only=True
            )
        except (BadZipFile, InvalidFileException, OSError) as exc:
            raise ValueError("XLSX upload is not a valid workbook") from exc
        try:
            sheet = workbook.active
            if sheet is None:
                raise ValueError("XLSX workbook does not have an active sheet")
            rows = sheet.iter_rows(values_only=True)
            raw_headers = next(rows, None)
            if not raw_headers:
                raise ValueError("XLSX sheet must have a header row")
            headers = [
                str(value).strip() if value is not None else "" for value in raw_headers
            ]
            if any(not value for value in headers):
                raise ValueError("XLSX header cells must not be empty")
            if len({value.casefold() for value in headers}) != len(headers):
                raise ValueError("XLSX header cells must be unique")
            xlsx_records: list[dict[str, object]] = []
            for row_number, xlsx_row in enumerate(rows, start=2):
                if not any(value is not None for value in xlsx_row):
                    continue
                if len(xlsx_row) > len(headers) and any(
                    value is not None for value in xlsx_row[len(headers) :]
                ):
                    xlsx_records.append(
                        {"__row_error__": f"Row {row_number} has extra columns"}
                    )
                    continue
                xlsx_records.append(
                    {
                        header: _xlsx_json_value(value)
                        for header, value in zip(headers, xlsx_row, strict=False)
                    }
                )
            return xlsx_records, []
        finally:
            workbook.close()
    raise ValueError("Supported dataset uploads are .csv, .json, .jsonl, and .xlsx")


def map_upload_records(
    records: Sequence[Mapping[str, object]],
    mapping: DatasetColumnMapping,
    initial_errors: Sequence[dict[str, object]],
) -> tuple[list[DatasetItemDraft], list[dict[str, object]], int]:
    drafts: list[DatasetItemDraft] = []
    errors = list(initial_errors)
    duplicates = 0
    inputs_seen: set[str] = set()
    category_counts: Counter[str] = Counter()
    mapped_fields = {
        field
        for field in (
            mapping.input_field,
            mapping.reference_answer_field,
            mapping.reference_context_field,
            mapping.category_field,
            mapping.split_field,
        )
        if field is not None
    }

    for row_number, row in enumerate(records, start=1):
        if "__row_error__" in row:
            errors.append({"row": row_number, "message": str(row["__row_error__"])})
            continue
        missing_fields = sorted(mapped_fields.difference(row))
        if missing_fields:
            errors.append(
                {
                    "row": row_number,
                    "message": "Mapped column(s) missing: " + ", ".join(missing_fields),
                }
            )
            continue

        input_value = row.get(mapping.input_field)
        if (
            not isinstance(input_value, str | int | float)
            or not str(input_value).strip()
        ):
            errors.append(
                {"row": row_number, "message": "Input value must not be empty"}
            )
            continue
        normalized_input = " ".join(str(input_value).split()).casefold()
        if normalized_input in inputs_seen:
            duplicates += 1
            continue
        inputs_seen.add(normalized_input)

        try:
            category = _mapped_string(row, mapping.category_field) or "normal"
            explicit_split = _mapped_string(row, mapping.split_field)
            reference_answer = _mapped_string(row, mapping.reference_answer_field)
            reference_context = _mapped_string(row, mapping.reference_context_field)
        except ValueError as exc:
            errors.append({"row": row_number, "message": str(exc)})
            continue
        if category not in ALLOWED_CATEGORIES:
            errors.append(
                {"row": row_number, "message": f"Unsupported category '{category}'"}
            )
            continue
        if explicit_split and explicit_split not in ALLOWED_SPLITS:
            errors.append(
                {"row": row_number, "message": "Split must be either 'dev' or 'test'"}
            )
            continue
        category_index = category_counts[category]
        category_counts[category] += 1
        split: Literal["dev", "test"]
        if explicit_split == "dev":
            split = "dev"
        elif explicit_split == "test":
            split = "test"
        else:
            split = "test" if category_index % 5 == 0 else "dev"

        payload: dict[str, object] = {
            key: value for key, value in row.items() if key not in mapped_fields
        }
        try:
            draft = DatasetItemDraft(
                input_text=str(input_value).strip(),
                reference_answer=reference_answer,
                reference_context=reference_context,
                category=category,
                provenance="uploaded",
                split=split,
                data=payload,
            )
        except ValidationError as exc:
            errors.append(
                {
                    "row": row_number,
                    "message": "; ".join(
                        error["msg"] for error in exc.errors(include_url=False)
                    ),
                }
            )
            continue
        drafts.append(draft)
    return drafts, errors, duplicates


def generated_item_drafts(
    values: object,
    *,
    requested_count: int,
) -> tuple[list[DatasetItemDraft], int]:
    if not isinstance(values, list):
        raise ValueError("Generator response must be a JSON array")
    drafts: list[DatasetItemDraft] = []
    seen: set[str] = set()
    duplicates = 0
    errors: list[str] = []
    for position, value in enumerate(values, start=1):
        if not isinstance(value, dict):
            errors.append(f"Item {position} is not a JSON object")
            continue
        input_value = value.get("input")
        if not isinstance(input_value, str) or not input_value.strip():
            errors.append(f"Item {position} is missing a non-empty input")
            continue
        category = value.get("category", "normal")
        if not isinstance(category, str) or category not in ALLOWED_CATEGORIES:
            errors.append(f"Item {position} has an unsupported category")
            continue
        normalized_input = " ".join(input_value.split()).casefold()
        if normalized_input in seen:
            duplicates += 1
            continue
        seen.add(normalized_input)
        known_fields = {"input", "reference_answer", "reference_context", "category"}
        raw_data = {
            str(key): item for key, item in value.items() if key not in known_fields
        }
        try:
            drafts.append(
                DatasetItemDraft(
                    input_text=input_value.strip(),
                    reference_answer=_generated_string(
                        value.get("reference_answer"), "reference_answer", position
                    ),
                    reference_context=_generated_string(
                        value.get("reference_context"), "reference_context", position
                    ),
                    category=category,
                    provenance="synthetic",
                    split="test" if position % 5 == 0 else "dev",
                    data=raw_data,
                )
            )
        except (TypeError, ValidationError) as exc:
            errors.append(f"Item {position} is invalid: {exc}")
    if errors:
        raise ValueError("Generator output failed validation: " + "; ".join(errors))
    if not drafts:
        raise ValueError("Generator returned no unique valid dataset items")
    if len(drafts) > requested_count:
        drafts = drafts[:requested_count]
    return drafts, duplicates


def dataset_content_hash(drafts: Sequence[DatasetItemDraft]) -> str:
    content = [draft.model_dump(mode="json") for draft in drafts]
    canonical = json.dumps(
        content,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(canonical).hexdigest()


def _mapped_string(row: Mapping[str, object], field: str | None) -> str | None:
    if field is None:
        return None
    value = row.get(field)
    if value is None:
        return None
    if not isinstance(value, str | int | float):
        raise ValueError(f"Mapped value for '{field}' must be text or a number")
    result = str(value).strip()
    return result or None


def _validate_records(
    values: Sequence[object],
) -> tuple[list[dict[str, object]], list[dict[str, object]]]:
    records: list[dict[str, object]] = []
    errors: list[dict[str, object]] = []
    for row_number, value in enumerate(values, start=1):
        if not isinstance(value, dict):
            errors.append(
                {"row": row_number, "message": "Each JSON row must be an object"}
            )
            continue
        records.append({str(key): item for key, item in value.items()})
    return records, errors


def _generated_string(value: object, field: str, position: int) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str):
        raise TypeError(f"{field} for item {position} must be a string")
    return value


def _xlsx_json_value(value: object) -> object:
    if isinstance(value, date | datetime):
        return value.isoformat()
    if value is None or isinstance(value, str | int | float | bool):
        return value
    raise ValueError("XLSX cells must contain text, numbers, booleans, or dates")
