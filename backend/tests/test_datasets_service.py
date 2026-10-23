"""Unit tests for the dataset upload service: parsing, detection, versioning."""

from __future__ import annotations

import hashlib
import io
import json
import uuid

import pytest
from openpyxl import Workbook
from sqlalchemy.orm import Session, sessionmaker

from app.models import DatasetColumnMapping, DatasetItem, DatasetVersion, User
from app.schemas.datasets import DatasetRead
from app.services.datasets import (
    DatasetError,
    add_dataset_version,
    approve_dataset_version,
    content_hash,
    create_dataset,
    detect_columns,
    detect_file_format,
    parse_rows,
)


def _make_user(session: Session) -> User:
    user = User(
        email=f"{uuid.uuid4().hex[:12]}@example.com",
        name="Test User",
        password_hash="x",
    )
    session.add(user)
    session.commit()
    return user


CSV_BYTES = (
    b"id,question,answer,latency_ms\n"
    b"1,What is GreenLit?,A testing framework.,120\n"
    b"2,Is it free?,Yes.,80\n"
)


def test_detect_file_format_from_extension() -> None:
    assert detect_file_format("data.csv") == "csv"
    assert detect_file_format("data.JSON") == "json"
    assert detect_file_format("data.jsonl") == "jsonl"
    assert detect_file_format("report.xlsx") == "xlsx"


def test_detect_file_format_unknown_extension() -> None:
    with pytest.raises(DatasetError) as excinfo:
        detect_file_format("data.pdf")
    assert excinfo.value.code == "unsupported_format"


def test_detect_columns_exact_match_wins() -> None:
    mapping = detect_columns(["id", "Question", "answer", "latency_ms", "prompt_tokens"])
    assert mapping["input"] == "Question"
    assert mapping["output"] == "answer"
    assert mapping["id"] == "id"
    assert mapping["latency_ms"] == "latency_ms"
    assert mapping["tokens_in"] == "prompt_tokens"


def test_detect_columns_substring_fallback() -> None:
    mapping = detect_columns(["user_query", "final_answer", "supporting_context"])
    assert mapping["input"] == "user_query"
    assert mapping["output"] == "final_answer"
    assert mapping["retrieved_context"] == "supporting_context"


def test_detect_columns_missing_roles_are_none() -> None:
    mapping = detect_columns(["foo", "bar"])
    assert mapping["input"] is None
    assert mapping["output"] is None


def test_parse_rows_csv() -> None:
    columns, rows = parse_rows("csv", CSV_BYTES)
    assert columns == ["id", "question", "answer", "latency_ms"]
    assert len(rows) == 2
    assert rows[0]["question"] == "What is GreenLit?"


def test_parse_rows_json_list_and_wrapped() -> None:
    columns, rows = parse_rows("json", json.dumps([{"question": "q1", "answer": "a1"}]).encode())
    assert columns == ["question", "answer"]
    assert rows == [{"question": "q1", "answer": "a1"}]

    wrapped = json.dumps({"items": [{"question": "q2", "answer": "a2"}]}).encode()
    _, wrapped_rows = parse_rows("json", wrapped)
    assert wrapped_rows == [{"question": "q2", "answer": "a2"}]


def test_parse_rows_jsonl() -> None:
    payload = b'{"question": "q1", "answer": "a1"}\n\n{"question": "q2", "answer": "a2"}\n'
    columns, rows = parse_rows("jsonl", payload)
    assert columns == ["question", "answer"]
    assert len(rows) == 2


def test_parse_rows_xlsx() -> None:
    workbook = Workbook()
    sheet = workbook.active
    sheet.append(["question", "answer"])
    sheet.append(["q1", "a1"])
    sheet.append(["q2", "a2"])
    buffer = io.BytesIO()
    workbook.save(buffer)

    columns, rows = parse_rows("xlsx", buffer.getvalue())
    assert columns == ["question", "answer"]
    assert rows == [{"question": "q1", "answer": "a1"}, {"question": "q2", "answer": "a2"}]


def test_parse_rows_rejects_empty_and_invalid() -> None:
    with pytest.raises(DatasetError) as empty:
        parse_rows("csv", b"")
    assert empty.value.code == "parse_error"

    with pytest.raises(DatasetError) as bad_json:
        parse_rows("json", b"{not json")
    assert bad_json.value.code == "parse_error"

    with pytest.raises(DatasetError) as bad_format:
        parse_rows("parquet", b"x")
    assert bad_format.value.code == "unsupported_format"


def test_content_hash_matches_hashlib() -> None:
    assert content_hash(CSV_BYTES) == hashlib.sha256(CSV_BYTES).hexdigest()


def test_create_dataset_happy_path(session_factory: sessionmaker[Session]) -> None:
    session = session_factory()
    user = _make_user(session)

    dataset = create_dataset(
        session,
        owner_id=user.id,
        name="Golden set",
        source_filename="golden.csv",
        raw_content=CSV_BYTES,
    )
    session.commit()

    assert dataset.file_format == "csv"
    assert dataset.content_hash == hashlib.sha256(CSV_BYTES).hexdigest()
    assert dataset.raw_content == CSV_BYTES

    mapping = dataset.columns
    assert isinstance(mapping, DatasetColumnMapping)
    assert mapping.input_column == "question"
    assert mapping.output_column == "answer"
    assert mapping.id_column == "id"
    assert mapping.latency_ms_column == "latency_ms"
    assert mapping.detected is True

    assert len(dataset.versions) == 1
    version = dataset.versions[0]
    assert version.version_no == 1
    assert version.row_count == 2
    assert version.columns_snapshot == {"columns": ["id", "question", "answer", "latency_ms"]}

    items = session.query(DatasetItem).filter_by(dataset_version_id=version.id).all()
    assert [item.row_index for item in items] == [0, 1]
    assert items[0].data["answer"] == "A testing framework."

    # The read schema never exposes the stored bytes.
    read = DatasetRead.model_validate(dataset)
    assert "raw_content" not in read.model_dump()


def test_create_dataset_with_overrides(session_factory: sessionmaker[Session]) -> None:
    session = session_factory()
    user = _make_user(session)
    payload = b"qry,resp\nhello,world\n"

    dataset = create_dataset(
        session,
        owner_id=user.id,
        name="Mapped",
        source_filename="mapped.csv",
        raw_content=payload,
        column_overrides={"input_column": "qry", "output_column": "resp"},
    )
    session.commit()

    assert dataset.columns is not None
    assert dataset.columns.input_column == "qry"
    assert dataset.columns.output_column == "resp"
    assert dataset.columns.detected is False


def test_create_dataset_override_missing_column(session_factory: sessionmaker[Session]) -> None:
    session = session_factory()
    user = _make_user(session)

    with pytest.raises(DatasetError) as excinfo:
        create_dataset(
            session,
            owner_id=user.id,
            name="Bad mapping",
            source_filename="bad.csv",
            raw_content=CSV_BYTES,
            column_overrides={"input_column": "nope"},
        )
    assert excinfo.value.code == "missing_columns"


def test_create_dataset_duplicate_name(session_factory: sessionmaker[Session]) -> None:
    session = session_factory()
    user = _make_user(session)
    create_dataset(
        session,
        owner_id=user.id,
        name="Twin",
        source_filename="a.csv",
        raw_content=CSV_BYTES,
    )
    session.commit()

    with pytest.raises(DatasetError) as excinfo:
        create_dataset(
            session,
            owner_id=user.id,
            name="Twin",
            source_filename="b.csv",
            raw_content=CSV_BYTES,
        )
    assert excinfo.value.code == "duplicate_name"


def test_create_dataset_same_name_other_owner_allowed(
    session_factory: sessionmaker[Session],
) -> None:
    session = session_factory()
    owner_a = _make_user(session)
    owner_b = _make_user(session)
    create_dataset(
        session,
        owner_id=owner_a.id,
        name="Shared name",
        source_filename="a.csv",
        raw_content=CSV_BYTES,
    )
    other = create_dataset(
        session,
        owner_id=owner_b.id,
        name="Shared name",
        source_filename="b.csv",
        raw_content=CSV_BYTES,
    )
    session.commit()
    assert other.id is not None


def test_create_dataset_undetectable_columns(session_factory: sessionmaker[Session]) -> None:
    session = session_factory()
    user = _make_user(session)

    with pytest.raises(DatasetError) as excinfo:
        create_dataset(
            session,
            owner_id=user.id,
            name="No columns",
            source_filename="x.csv",
            raw_content=b"foo,bar\n1,2\n",
        )
    assert excinfo.value.code == "missing_columns"


def test_add_dataset_version(session_factory: sessionmaker[Session]) -> None:
    session = session_factory()
    user = _make_user(session)
    dataset = create_dataset(
        session,
        owner_id=user.id,
        name="Evolving",
        source_filename="v1.csv",
        raw_content=CSV_BYTES,
    )
    session.commit()

    v2_bytes = b"question,answer\nNew question,New answer\n"
    version = add_dataset_version(session, dataset, v2_bytes)
    session.commit()

    assert version.version_no == 2
    assert version.row_count == 1
    assert version.content_hash == hashlib.sha256(v2_bytes).hexdigest()

    all_versions = session.query(DatasetVersion).filter_by(dataset_id=dataset.id).all()
    assert sorted(v.version_no for v in all_versions) == [1, 2]
    v2_items = session.query(DatasetItem).filter_by(dataset_version_id=version.id).all()
    assert len(v2_items) == 1
    assert dataset.content_hash == hashlib.sha256(v2_bytes).hexdigest()

    # Version 1 and its items are untouched.
    v1 = session.query(DatasetVersion).filter_by(dataset_id=dataset.id, version_no=1).one()
    v1_items = session.query(DatasetItem).filter_by(dataset_version_id=v1.id).all()
    assert len(v1_items) == 2


def test_add_dataset_version_missing_required_columns_fails(
    session_factory: sessionmaker[Session],
) -> None:
    session = session_factory()
    user = _make_user(session)
    dataset = create_dataset(
        session,
        owner_id=user.id,
        name="Strict",
        source_filename="v1.csv",
        raw_content=CSV_BYTES,
    )
    session.commit()

    # Optional columns may disappear from v2; required ones may not.
    optional = add_dataset_version(session, dataset, b"question,answer\nq,a\n")
    session.commit()
    assert optional.version_no == 2
    assert optional.row_count == 1

    with pytest.raises(DatasetError) as excinfo:
        add_dataset_version(session, dataset, b"foo,bar\n1,2\n")
    assert excinfo.value.code == "missing_columns"


def test_approve_dataset_version(session_factory: sessionmaker[Session]) -> None:
    session = session_factory()
    user = _make_user(session)
    dataset = create_dataset(
        session,
        owner_id=user.id,
        name="Approvable",
        source_filename="v1.csv",
        raw_content=CSV_BYTES,
    )
    session.commit()

    version = approve_dataset_version(session, dataset, 1, approver_id=user.id)
    session.commit()
    assert version.approved_by == user.id
    assert version.approved_at is not None

    # Approval is one-way.
    with pytest.raises(DatasetError) as excinfo:
        approve_dataset_version(session, dataset, 1, approver_id=user.id)
    assert excinfo.value.code == "already_approved"


def test_approve_unknown_version(session_factory: sessionmaker[Session]) -> None:
    session = session_factory()
    user = _make_user(session)
    dataset = create_dataset(
        session,
        owner_id=user.id,
        name="No such version",
        source_filename="v1.csv",
        raw_content=CSV_BYTES,
    )
    session.commit()

    with pytest.raises(DatasetError) as excinfo:
        approve_dataset_version(session, dataset, 7, approver_id=user.id)
    assert excinfo.value.code == "version_not_found"
