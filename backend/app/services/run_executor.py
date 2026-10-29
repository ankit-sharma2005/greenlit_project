"""Run executor: the worker body of M6 (spec 8.1).

``execute_run`` takes a queued run, executes every dataset case through the
run's connector, stores each item's trace, then scores the run with the M5
engine and stores the verdict. It is deliberately independent of Celery: the
task in :mod:`app.tasks` calls it with the real session factory and the Redis
progress reporter, while tests inject a fake sender, an in-memory reporter and
their own session factory.

Guarantees (spec 8.1):

* runs execute outside HTTP requests, here in the worker, never in a route;
* every external call carries the timeout from the run's settings snapshot;
* one failing item never fails the run: the error is stored on the item and
  scoring continues over what actually came back;
* cancelling (state ``cancelling``) stops new items, keeps the finished ones
  and labels the results partial;
* the verdict comes from the same decision engine the preview uses, so the
  explanation is in plain words with suggested fixes.
"""

from __future__ import annotations

import logging
import threading
import time
import uuid
from collections.abc import Callable, Mapping, Sequence
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from app.config import get_settings
from app.db import SessionLocal
from app.models import (
    DatasetVersion,
    JudgeProfile,
    Provider,
    Run,
    RunItem,
    RunItemState,
    RunState,
    utcnow,
)
from app.safety.metrics import not_instrumented_safety
from app.safety.runner import probe_safety
from app.security.rate_limit import get_rate_limiter
from app.services.connectors import ConnectorError, HttpConnector, PromptAppConnector, Trace
from app.services.decision import JudgeStatus
from app.services.evaluation import CaseData, EvaluationError, evaluate_preview
from app.services.judge import (
    ANSWER_QUALITY,
    DEFAULT_ANSWER_QUALITY_THRESHOLD,
    JUDGE_RUBRIC_VERSION,
    JudgeChat,
    JudgeInput,
    JudgeVerdict,
    answer_quality,
    judge_item,
    judge_metadata,
    judge_status,
    make_judge_chat,
    prompt_template_hash,
)
from app.services.judge_profiles import effective_model
from app.services.llm_gateway import LLMGateway
from app.services.metrics import MetricResult, not_instrumented
from app.services.run_progress import ProgressReporter, RunProgress, get_progress
from app.services.run_repository import (
    add_metric_result,
    create_run_item,
    list_run_items,
    update_run,
    update_run_item,
)

logger = logging.getLogger("greenlit.run_executor")

# input_text -> trace; the factory also receives the run's settings snapshot.
Sender = Callable[[str], Trace]
SenderFactory = Callable[[Mapping[str, Any], Callable[[], Session]], Sender]

_DEFAULT_BODY_TEMPLATE = '{"question": {{input}}}'
_LATENCY_LIMIT_MS = 5000

NO_JUDGE_REASON = (
    "This run had no judge profile, so answer quality was not scored. "
    "Choose one in Settings > Judge to have the answers graded."
)


class RunExecutionError(Exception):
    """Run-level failure: the run cannot proceed (stored on the run itself)."""

    def __init__(self, message: str) -> None:
        super().__init__(message)
        self.message = message


@dataclass
class _Case:
    """One dataset row prepared for execution (plain values, safe across threads)."""

    row_index: int
    input_text: str
    expected_answer: str | None = None
    reference_context: list[str] | str | None = None
    # Precomputed values, used by the upload_outputs entry point only:
    output: str | None = None
    retrieved_context: list[str] | str | None = None
    latency_ms: int | None = None
    tokens_in: int | None = None
    tokens_out: int | None = None
    error: str | None = None


def entry_point(snapshot: Mapping[str, Any]) -> str:
    """Which connector this run uses; older snapshots stored ``connector_type``."""
    value = snapshot.get("entry_point") or snapshot.get("connector_type") or "http_endpoint"
    return str(value)


def build_sender(snapshot: Mapping[str, Any], session_factory: Callable[[], Session]) -> Sender:
    """Build the per-run callable that sends one input through the connector.

    Uses only values from the run's settings snapshot, so a queued run always
    executes with the settings it was created with (including its timeout).
    """
    entry = entry_point(snapshot)
    if entry == "http_endpoint":
        url = str(snapshot.get("url") or "").strip()
        if not url:
            raise RunExecutionError(
                "This run has no target URL. Start the test again from the New Test page."
            )
        headers = {
            str(key): str(value) for key, value in dict(snapshot.get("headers") or {}).items()
        }
        timeout_seconds = int(
            snapshot.get("timeout_seconds") or get_settings().default_timeout_seconds
        )
        method = str(snapshot.get("method") or "POST")
        raw_answer_path = snapshot.get("answer_path")
        answer_path = str(raw_answer_path) if raw_answer_path else None
        body_template = str(snapshot.get("body_template") or _DEFAULT_BODY_TEMPLATE)
        allow_private = bool(snapshot.get("allow_private_targets", False))
        connector = HttpConnector(allow_private=allow_private)

        def send_http(input_text: str) -> Trace:
            return connector.render_and_send(
                url=url,
                body_template=body_template,
                input_text=input_text,
                headers=headers,
                timeout_seconds=timeout_seconds,
                method=method,
                answer_path=answer_path,
            )

        return send_http
    if entry == "prompt_app":
        return _prompt_app_sender(snapshot, session_factory)
    raise RunExecutionError(f"The entry point '{entry}' is coming soon and cannot run tests yet.")


def _prompt_app_sender(
    snapshot: Mapping[str, Any], session_factory: Callable[[], Session]
) -> Sender:
    """Prompt-app sender: the saved provider through the rate-limited gateway."""
    raw_provider = snapshot.get("provider_id")
    if not raw_provider:
        raise RunExecutionError(
            "This run has no model provider. Pick one in Settings > Providers, "
            "then start the test again."
        )
    try:
        provider_uuid = uuid.UUID(str(raw_provider))
    except ValueError as exc:
        raise RunExecutionError("The provider saved on this run is not a valid id.") from exc
    with session_factory() as session:
        provider = session.get(Provider, provider_uuid)
    if provider is None:
        raise RunExecutionError(
            "The provider saved on this run no longer exists. "
            "Pick another one in Settings > Providers."
        )

    gateway = LLMGateway(rate_limiter=get_rate_limiter())
    model_name = str(snapshot.get("model") or provider.model_name)
    system_prompt_value = snapshot.get("system_prompt")
    system_prompt = str(system_prompt_value) if system_prompt_value else None
    body_template = str(snapshot.get("body_template") or "{{input}}")
    raw_temperature = snapshot.get("temperature")
    temperature = float(raw_temperature) if raw_temperature is not None else 0.2

    def chat(
        messages: list[dict[str, str]],
        model: str | None = None,
        params: dict[str, Any] | None = None,
    ) -> str:
        # LLMGateway applies the provider's timeout, retries and request rate limit.
        value = (params or {}).get("temperature", temperature)
        return gateway.chat(provider, messages, float(value), model=model or model_name)

    connector = PromptAppConnector(chat=chat)

    def send_prompt(input_text: str) -> Trace:
        return connector.render_and_send(
            prompt=body_template,
            input_text=input_text,
            model=model_name,
            system_prompt=system_prompt,
            temperature=temperature,
        )

    return send_prompt


_EXPECTED_KEYS = (
    "expected_answer",
    "expected",
    "reference_answer",
    "gold_answer",
    "ground_truth",
    "answer",
)
_REFERENCE_CONTEXT_KEYS = ("reference_context", "expected_context", "gold_context")


def _text(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _text_list(value: Any) -> list[str] | str | None:
    if value is None:
        return None
    if isinstance(value, list):
        return [str(entry) for entry in value]
    return _text(value)


def _int(value: Any) -> int | None:
    if value is None or value == "":
        return None
    try:
        return int(float(value))
    except (TypeError, ValueError):
        return None


def _first_present(data: Mapping[str, Any], keys: tuple[str, ...]) -> Any:
    for key in keys:
        if key in data and data[key] not in (None, ""):
            return data[key]
    return None


def _expected_from_row(data: Mapping[str, Any], output_column: str) -> str | None:
    """Golden answer for a precomputed row: any expected-ish key but the output column."""
    excluded = output_column.strip().lower()
    for key in _EXPECTED_KEYS:
        if key == excluded:
            continue
        value = _text(data.get(key))
        if value is not None:
            return value
    return None


def _resolve_version(session: Session, run: Run) -> DatasetVersion:
    """The run's dataset version; always an approved one (spec 8.1)."""
    version: DatasetVersion | None = None
    if run.dataset_version_id is not None:
        version = session.get(DatasetVersion, run.dataset_version_id)
        if version is None:
            raise RunExecutionError("The dataset version this run points at no longer exists.")
    elif run.dataset_id is not None:
        versions = session.scalars(
            select(DatasetVersion)
            .where(DatasetVersion.dataset_id == run.dataset_id)
            .order_by(DatasetVersion.version_no.desc())
        ).all()
        approved = [candidate for candidate in versions if candidate.approved_at is not None]
        if not approved:
            raise RunExecutionError(
                "This dataset has no approved version. "
                "Approve a version in Settings > Datasets first."
            )
        version = approved[0]
    else:
        raise RunExecutionError(
            "This run has no dataset. Choose a dataset before starting the run."
        )
    if version.approved_at is None:
        raise RunExecutionError(
            "The dataset version for this run is not approved. "
            "Approve it in Settings > Datasets first."
        )
    return version


def _load_cases(
    session: Session, run: Run, entry: str
) -> tuple[list[_Case], list[tuple[int, str, dict[str, str]]]]:
    """Approved dataset rows -> execution cases, using the saved column mapping."""
    version = _resolve_version(session, run)
    mapping = version.dataset.columns
    if mapping is None:
        raise RunExecutionError(
            "This dataset has no column mapping. Re-upload it in Settings > Datasets."
        )
    rows = sorted(version.items, key=lambda row: row.row_index)
    input_column = mapping.input_column.strip().lower()
    output_column = mapping.output_column.strip().lower()
    context_column = (
        mapping.retrieved_context_column.strip().lower()
        if mapping.retrieved_context_column
        else None
    )
    _latency_column = (
        mapping.latency_ms_column.strip().lower() if mapping.latency_ms_column else None
    )
    _tokens_in_column = (
        mapping.tokens_in_column.strip().lower() if mapping.tokens_in_column else None
    )
    _tokens_out_column = (
        mapping.tokens_out_column.strip().lower() if mapping.tokens_out_column else None
    )

    # Collect (row_index, input_text, item_data) tuples. For upload_outputs
    # the outputs come from the uploaded file, matched to these items later;
    # for every other entry point the dataset item's own columns are used.
    item_tuples: list[tuple[int, str, dict[str, str]]] = []
    for row in rows:
        data = {
            str(key).strip().lower(): str(value).strip() for key, value in (row.data or {}).items()
        }
        input_text = _text(data.get(input_column))
        if input_text is None:
            continue
        # The index must be the same one the cases get below: run items are
        # 1-based, while a dataset version stores 0-based row indices. Keying
        # matches by ``row.row_index`` shifted every upload match by one row and
        # left the last item unmatched.
        item_tuples.append((len(item_tuples) + 1, input_text, data))

    cases: list[_Case] = []
    for _row_index, input_text, data in item_tuples:
        # The dataset item carries the input, the expected (golden) answer and
        # optionally the reference context the app should have retrieved.
        # For upload_outputs the actual outputs come from the uploaded file,
        # matched to these cases later in execute_run.
        cases.append(
            _Case(
                row_index=len(cases) + 1,
                input_text=input_text,
                expected_answer=_text(data.get(output_column)),
                reference_context=(
                    _text_list(data.get(context_column)) if context_column else None
                ),
            )
        )
    if not cases:
        raise RunExecutionError("The approved dataset version has no rows with an input.")
    return cases, item_tuples


def _precomputed_trace(case: _Case) -> Trace:
    """The same trace contract as a live call, for upload_outputs runs."""
    return Trace(
        output=case.output or "",
        retrieved_context=(
            case.retrieved_context if case.retrieved_context is not None else "not instrumented"
        ),
        tool_calls="not instrumented",
        latency_ms=int(case.latency_ms or 0),
        tokens_in=case.tokens_in,
        tokens_out=case.tokens_out,
        error=case.error,
        raw={"source": "upload_outputs"},
    )


@dataclass
class JudgeRunResult:
    """What the judge phase produced: provenance and per-item verdicts, or why not.

    ``metadata`` is None when the judge did not run (no profile, a deleted
    profile, or a cancelled run) and ``skipped_reason`` explains that in plain
    words, so the verdict card can say "judge skipped" instead of staying silent.
    """

    metadata: dict[str, Any] | None = None
    skipped_reason: str | None = None
    verdicts: dict[uuid.UUID, JudgeVerdict] = field(default_factory=dict)
    status: JudgeStatus = field(default_factory=JudgeStatus)
    metric: MetricResult | None = None


def judge_run(
    factory: Callable[[], Session],
    snapshot: Mapping[str, Any],
    cases: Sequence[_Case],
    *,
    run_id: uuid.UUID,
    chat: JudgeChat | None = None,
) -> JudgeRunResult:
    """Score every answered case with the run's saved judge (spec 8.2).

    Three choices are worth knowing:

    * a case whose call failed never reaches the judge: there is no answer to
      grade, and errors are what ``error_rate`` measures;
    * a judge that cannot be reached is not a run failure: the caller turns it
      into the decision engine's rule 3 (REVIEW);
    * nothing is written here. The caller stores the provenance and the
      per-item rows in the transaction that stores the verdict.

    The provider row is read in its own short session and the model calls then
    run with no session open, so a slow judge never holds a transaction.
    """
    raw = snapshot.get("judge_profile_id")
    if not raw:
        return JudgeRunResult(skipped_reason=NO_JUDGE_REASON)
    try:
        profile_id = uuid.UUID(str(raw))
    except ValueError:
        return _judge_skipped("The judge profile saved on this run is not a valid id.", cases)

    with factory() as session:
        profile = session.get(JudgeProfile, profile_id)
        if profile is None:
            return _judge_skipped(
                "The judge profile saved on this run no longer exists. "
                "Pick one in Settings > Judge and run again.",
                cases,
            )
        provider = session.get(Provider, profile.provider_id) if profile.provider_id else None
        if provider is None:
            return _judge_skipped(
                "The judge's provider no longer exists. "
                "Pick another provider in Settings > Judge and run again.",
                cases,
            )
        model = effective_model(profile, provider)
        max_tokens = profile.max_tokens
        max_cases = profile.max_cases
        metadata = judge_metadata(provider, model)
        metadata.update(
            {
                "judge_profile_id": str(profile.id),
                "judge_profile_name": profile.name,
                "judge_provider_name": provider.name,
                "judge_rubric_version": profile.rubric_version,
                "judge_max_tokens": max_tokens,
                "judge_max_cases": max_cases,
            }
        )
        rows = [
            (
                item.id,
                item.row_index,
                item.input_text,
                item.output,
                _judge_context(item.retrieved_context),
            )
            for item in list_run_items(session, run_id)
        ]

    chat_fn = chat if chat is not None else make_judge_chat(get_rate_limiter())
    cases_by_row = {case.row_index: case for case in cases}
    # Only answered cases are candidates: a failed call has nothing to grade.
    answered = [row for row in rows if row[3] and row[3].strip()]
    capped = max(0, len(answered) - max_cases) if max_cases is not None else 0
    if capped:
        answered = answered[:max_cases]
    verdicts: dict[uuid.UUID, JudgeVerdict] = {}
    for item_id, row_index, input_text, output, context in answered:
        original = cases_by_row.get(row_index)
        verdicts[item_id] = judge_item(
            JudgeInput(
                question=input_text,
                app_answer=output,
                expected_answer=original.expected_answer if original is not None else None,
                retrieved_context=context,
            ),
            provider=provider,
            model=model,
            chat=chat_fn,
            max_tokens=max_tokens,
        )

    status = judge_status(list(verdicts.values()))
    metadata.update(
        {
            "judge_rubric_version": JUDGE_RUBRIC_VERSION,
            "judge_graded_items": len(verdicts),
            "judge_unavailable_items": status.unavailable_items,
            "judge_low_confidence_items": status.low_confidence_items,
            # "judged N of M cases": M counts every answer the run produced, so a
            # capped run says so instead of looking like it covered everything.
            "judge_case_total": len(verdicts) + capped,
            "judge_capped_items": capped,
        }
    )
    return JudgeRunResult(
        metadata=metadata,
        verdicts=verdicts,
        status=status,
        metric=answer_quality(list(verdicts.values()), skipped=capped),
    )


def _judge_skipped(reason: str, cases: Sequence[_Case]) -> JudgeRunResult:
    """A judge that was configured but could not run: rule 3, never a silent score."""
    return JudgeRunResult(
        skipped_reason=reason,
        # Not instrumented, so it is excluded from the weighted score instead of
        # counting as zero; every case counts as unavailable, which is what makes
        # the decision engine answer REVIEW.
        status=JudgeStatus(unavailable_items=len(cases)),
        metric=not_instrumented(ANSWER_QUALITY, reason),
    )


def _judge_context(value: Sequence[str] | str | None) -> str | None:
    """Retrieved context as one string for the judge, or None when absent."""
    if value is None:
        return None
    if isinstance(value, str):
        text = value.strip()
        return None if text.lower() == "not instrumented" else text or None
    joined = "\n".join(str(part) for part in value).strip()
    return joined or None


def execute_run(
    run_id: uuid.UUID | str,
    *,
    session_factory: sessionmaker[Session] | None = None,
    sender_factory: SenderFactory | None = None,
    progress: ProgressReporter | None = None,
    parallelism: int | None = None,
    judge_chat: JudgeChat | None = None,
) -> dict[str, Any]:
    """Execute one run to completion and return a JSON-able report.

    Never raises for a per-item or configuration problem: those are stored on
    the run (``failed``) or on the item (``failed``). Unexpected infrastructure
    errors mark the run failed and re-raise so the worker log shows them.

    ``judge_chat`` swaps the judge's model call, exactly like ``sender_factory``
    swaps the app's: tests inject a fake judge and exercise the real scoring,
    provenance and decision path.
    """
    factory: Callable[[], Session] = session_factory or SessionLocal
    reporter: ProgressReporter = progress if progress is not None else get_progress()
    workers = (
        parallelism
        if parallelism is not None and parallelism > 0
        else get_settings().default_run_parallelism
    )
    rid = run_id if isinstance(run_id, uuid.UUID) else uuid.UUID(str(run_id))

    # Every DB write and counter update runs under this lock: in tests the
    # session factory is one shared SQLite connection, and progress counters
    # must not interleave either. Network calls themselves run outside it.
    lock = threading.Lock()

    sender: Sender | None = None
    cases: list[_Case] = []
    work: list[tuple[uuid.UUID, _Case]] = []
    entry = "http_endpoint"
    started_at: str | None = None
    snapshot: dict[str, Any] = {}

    # ---- phase 1: claim the run and prepare the work ---------------------
    try:
        with factory() as session:
            run = session.get(Run, rid)
            if run is None:
                raise RunExecutionError(f"Run {rid} not found.")
            if run.state != RunState.QUEUED:
                return _report(
                    rid,
                    status="skipped",
                    state=run.state,
                    reason=f"The run is already {run.state}.",
                )
            snapshot = dict(run.settings_snapshot or {})
            entry = entry_point(snapshot)
            # Configuration checks live here (not only in build_sender) so an
            # injected sender factory cannot bypass them.
            if entry not in ("http_endpoint", "prompt_app", "upload_outputs"):
                raise RunExecutionError(
                    f"The entry point '{entry}' is coming soon and cannot run tests yet."
                )
            if entry == "http_endpoint" and not str(snapshot.get("url") or "").strip():
                raise RunExecutionError(
                    "This run has no target URL. Start the test again from the New Test page."
                )
            cases, item_tuples = _load_cases(session, run, entry)
            if entry != "upload_outputs":
                choose_sender: SenderFactory = sender_factory or build_sender
                sender = choose_sender(snapshot, factory)
            else:
                # Match uploaded rows to dataset items by id, then by input text.
                csv_content = str(snapshot.get("csv") or "").strip()
                if not csv_content:
                    raise RunExecutionError(
                        "This upload-outputs run has no file content. Start the test again."
                    )
                from app.services.connectors import (
                    UploadOutputsConnector,
                    match_uploaded_rows,
                )

                overrides = snapshot.get("column_overrides") or None
                _file_format, uploaded_rows, columns = UploadOutputsConnector.parse_file(
                    csv_content, overrides
                )
                matched = match_uploaded_rows(item_tuples, uploaded_rows, columns)
                unmatched_count = 0
                for case in cases:
                    fields = matched.get(case.row_index)
                    if fields is None:
                        case.error = (
                            f"No matching output in the uploaded file for row {case.row_index}."
                        )
                        unmatched_count += 1
                        continue
                    case.output = fields["output"] or ""
                    case.retrieved_context = fields["retrieved_context"]
                    case.latency_ms = fields["latency_ms"]
                    case.tokens_in = fields["tokens_in"]
                    case.tokens_out = fields["tokens_out"]
                if unmatched_count:
                    message = (
                        f"Run {rid}: {unmatched_count} of {len(cases)} "
                        "dataset items had no matching output in the uploaded file."
                    )
                    logger.info(message)
            update_run(session, run, state=RunState.RUNNING, started_at=utcnow())
            started_at = run.started_at.isoformat() if run.started_at else None
            existing = {item.row_index: item for item in list_run_items(session, rid)}
            for case in cases:
                item = existing.get(case.row_index)
                if item is None:
                    item = create_run_item(
                        session, run, row_index=case.row_index, input_text=case.input_text
                    )
                work.append((item.id, case))
            session.commit()
    except RunExecutionError as exc:
        return _fail(factory, reporter, rid, exc.message)
    except Exception:
        _fail(
            factory,
            reporter,
            rid,
            "The worker hit an unexpected error while preparing the run.",
        )
        raise

    total = len(work)
    counts = {"done": 0, "completed": 0, "failed": 0, "cancelled": 0}

    def snapshot_progress(stage: str) -> RunProgress:
        """Build the payload to publish; the caller must hold the lock."""
        return RunProgress(
            items_done=counts["done"],
            items_total=total,
            items_failed=counts["failed"],
            items_cancelled=counts["cancelled"],
            stage=stage,
            started_at=started_at,
            updated_at=utcnow().isoformat(),
        )

    reporter.publish(
        rid,
        RunProgress(
            items_total=total,
            stage="running",
            started_at=started_at,
            updated_at=utcnow().isoformat(),
        ),
    )

    def is_stopping() -> bool:
        with lock, factory() as session:
            state = session.scalar(select(Run.state).where(Run.id == rid))
        return state in (RunState.CANCELLING.value, RunState.CANCELLED.value)

    def execute_item(item_id: uuid.UUID, case: _Case) -> None:
        # Cancel check first: a cancelling run takes on no new cases.
        if is_stopping():
            with lock:
                with factory() as session:
                    item = session.get(RunItem, item_id)
                    if item is not None:
                        update_run_item(session, item, state=RunItemState.CANCELLED)
                    session.commit()
                counts["cancelled"] += 1
                counts["done"] += 1
                payload = snapshot_progress("running")
            reporter.publish(rid, payload)
            return

        with lock, factory() as session:
            item = session.get(RunItem, item_id)
            if item is not None:
                update_run_item(session, item, state=RunItemState.RUNNING)
            session.commit()

        call_started = time.monotonic()
        trace: Trace | None = None
        error: str | None = None
        error_code: str | None = None
        timed_out = False
        try:
            # upload_outputs: answers come from the file, nothing is called.
            trace = _precomputed_trace(case) if sender is None else sender(case.input_text)
            error = trace.error
        except ConnectorError as exc:
            error = exc.message
            error_code = exc.code
            timed_out = exc.code == "timeout"
        except Exception as exc:  # a single bad case never fails the run (spec 8.1)
            error = str(exc) or exc.__class__.__name__
            error_code = "unexpected_error"
        elapsed_ms = int((time.monotonic() - call_started) * 1000)
        state = RunItemState.FAILED if error else RunItemState.COMPLETED

        with lock:
            with factory() as session:
                item = session.get(RunItem, item_id)
                if item is not None:
                    update_run_item(
                        session,
                        item,
                        state=state,
                        output=trace.output if trace is not None else None,
                        retrieved_context=(trace.retrieved_context if trace is not None else None),
                        latency_ms=trace.latency_ms if trace is not None else elapsed_ms,
                        tokens_in=trace.tokens_in if trace is not None else None,
                        tokens_out=trace.tokens_out if trace is not None else None,
                        error=error,
                        trace={
                            "connector": entry,
                            "timed_out": timed_out,
                            "error_code": error_code,
                            "elapsed_ms": elapsed_ms,
                            "raw": trace.raw if trace is not None else None,
                        },
                    )
                    session.commit()
            counts["done"] += 1
            if state == RunItemState.COMPLETED:
                counts["completed"] += 1
            else:
                counts["failed"] += 1
            payload = snapshot_progress("running")
        reporter.publish(rid, payload)

    # ---- phase 2: execute the items -------------------------------------
    try:
        with ThreadPoolExecutor(max_workers=max(1, min(workers, total))) as pool:
            futures = [pool.submit(execute_item, item_id, case) for item_id, case in work]
            for future in futures:
                future.result()
    except Exception:
        _fail(
            factory,
            reporter,
            rid,
            "The worker hit an unexpected error while running the cases.",
        )
        raise

    # ---- phase 2b: built-in safety probes (spec 8.3) ---------------------
    # Only when the Safety test type is on, and only for connectors that really
    # call the app: an upload-outputs run has nothing to attack.
    include_safety = "safety" in [str(value) for value in (snapshot.get("test_types") or [])]
    extra_metrics: dict[str, MetricResult] = {}
    if include_safety:
        if sender is None:
            extra_metrics = not_instrumented_safety(
                "this run scores uploaded answers, so the app was never asked"
            )
        elif is_stopping():
            extra_metrics = not_instrumented_safety(
                "the run was cancelled before the safety probes ran"
            )
        else:
            extra_metrics = probe_safety(sender, workers=workers)

    # ---- phase 2c: judge the answers (spec 8.2) --------------------------
    # A cancelled run stops here, like the safety probes: paying for judge calls
    # on results that are already labelled partial helps nobody.
    judge_requested = bool(snapshot.get("judge_profile_id"))
    if not judge_requested:
        judge_result = JudgeRunResult(skipped_reason=NO_JUDGE_REASON)
    elif is_stopping():
        judge_result = _judge_skipped(
            "The run was cancelled before the answers were judged.", cases
        )
    else:
        judge_result = judge_run(factory, snapshot, cases, run_id=rid, chat=judge_chat)
    if judge_result.metric is not None:
        extra_metrics[ANSWER_QUALITY] = judge_result.metric

    # ---- phase 3: score the finished items and store the verdict ---------
    report: dict[str, Any]
    final_payload: RunProgress
    try:
        with lock, factory() as session:
            run = session.get(Run, rid)
            if run is None:
                raise RunExecutionError(f"Run {rid} disappeared while executing.")
            items = list_run_items(session, rid)
            # Provenance travels with the verdict: which judge, which rubric and
            # which prompt hash scored these answers, or why no judge ran.
            snapshot_update = dict(snapshot)
            if judge_result.metadata is not None:
                snapshot_update["judge"] = judge_result.metadata
            if judge_result.skipped_reason is not None:
                snapshot_update["judge_skipped_reason"] = judge_result.skipped_reason
            if snapshot_update != snapshot:
                update_run(session, run, settings_snapshot=snapshot_update)
            was_cancelled = run.state in (
                RunState.CANCELLING.value,
                RunState.CANCELLED.value,
            )
            finished = [
                item
                for item in items
                if item.state in (RunItemState.COMPLETED.value, RunItemState.FAILED.value)
            ]
            if not finished:
                # Cancelled (or nothing ever finished): no verdict, labelled partial.
                reason = (
                    "The run was cancelled before any case finished; there is nothing to score."
                    if was_cancelled
                    else "No case finished; there is nothing to score."
                )
                final_state = RunState.CANCELLED if was_cancelled else RunState.FAILED
                update_run(
                    session,
                    run,
                    state=final_state,
                    verdict=None,
                    score=None,
                    verdict_reason=reason,
                    is_partial=True if was_cancelled else run.is_partial,
                    completed_at=utcnow(),
                )
                session.commit()
                report = _report(
                    rid,
                    status=str(final_state),
                    state=final_state,
                    total=total,
                    completed=counts["completed"],
                    failed=counts["failed"],
                    cancelled=counts["cancelled"],
                    partial=was_cancelled,
                    reason=reason,
                )
            else:
                case_by_row = {case.row_index: case for case in cases}
                scored: list[CaseData] = []
                for item in finished:
                    original = case_by_row.get(item.row_index)
                    meta = item.trace if isinstance(item.trace, dict) else {}
                    scored.append(
                        CaseData(
                            input=item.input_text,
                            expected_answer=original.expected_answer if original else None,
                            output=item.output,
                            reference_context=original.reference_context if original else None,
                            retrieved_context=item.retrieved_context,
                            latency_ms=item.latency_ms,
                            tokens_in=item.tokens_in,
                            tokens_out=item.tokens_out,
                            error=item.error,
                            timed_out=bool(meta.get("timed_out")),
                        )
                    )
                try:
                    preview = evaluate_preview(
                        run.criteria_profile,
                        scored,
                        judge_result.status if judge_requested else None,
                        latency_limit_ms=_LATENCY_LIMIT_MS,
                        include_safety=include_safety,
                        include_judge=judge_requested,
                        extra_metrics=extra_metrics,
                    )
                except EvaluationError as exc:
                    update_run(
                        session,
                        run,
                        state=RunState.FAILED,
                        verdict=None,
                        score=None,
                        verdict_reason=exc.message,
                        completed_at=utcnow(),
                    )
                    session.commit()
                    report = _report(
                        rid,
                        status="failed",
                        state=RunState.FAILED,
                        total=total,
                        completed=counts["completed"],
                        failed=counts["failed"],
                        cancelled=counts["cancelled"],
                        partial=was_cancelled,
                        reason=exc.message,
                    )
                else:
                    criteria = {
                        criterion.metric: criterion for criterion in preview.profile.criteria
                    }
                    for result in preview.metrics:
                        criterion = criteria.get(result.name)
                        add_metric_result(
                            session,
                            run,
                            name=result.name,
                            score=result.score,
                            passed=result.passed,
                            explanation=result.explanation,
                            instrumented=result.instrumented,
                            weight=criterion.weight if criterion else 0.0,
                            threshold=criterion.threshold if criterion else 0.0,
                            hard_gate=criterion.hard_gate if criterion else False,
                            details=result.details,
                        )
                    # Per-item judge rows: the score, the reason, the confidence and
                    # the rubric that produced it, so one bad answer is traceable.
                    for item_id, verdict in judge_result.verdicts.items():
                        add_metric_result(
                            session,
                            run,
                            name=ANSWER_QUALITY,
                            score=verdict.score if verdict.score is not None else 0.0,
                            passed=bool(
                                verdict.available
                                and (verdict.score or 0.0) >= DEFAULT_ANSWER_QUALITY_THRESHOLD
                            ),
                            explanation=verdict.reason,
                            instrumented=verdict.available,
                            run_item_id=item_id,
                            threshold=DEFAULT_ANSWER_QUALITY_THRESHOLD,
                            details={
                                "confidence": verdict.confidence,
                                "attempts": verdict.attempts,
                                "rubric_version": JUDGE_RUBRIC_VERSION,
                                "prompt_template_hash": prompt_template_hash(),
                                "judge_model": (judge_result.metadata or {}).get("judge_model"),
                            },
                        )
                    decision = preview.decision
                    reason = decision.reason
                    if decision.suggested_fixes:
                        reason = f"{reason} Suggested fixes: {'; '.join(decision.suggested_fixes)}."
                    if was_cancelled:
                        reason = f"This run was cancelled, so the results are partial. {reason}"
                    final_state = RunState.CANCELLED if was_cancelled else RunState.COMPLETED
                    update_run(
                        session,
                        run,
                        state=final_state,
                        verdict=decision.verdict,
                        score=decision.score,
                        verdict_reason=reason,
                        is_partial=was_cancelled,
                        completed_at=utcnow(),
                    )
                    session.commit()
                    report = _report(
                        rid,
                        status=str(final_state),
                        state=final_state,
                        total=total,
                        completed=counts["completed"],
                        failed=counts["failed"],
                        cancelled=counts["cancelled"],
                        verdict=decision.verdict,
                        score=decision.score,
                        partial=was_cancelled,
                        reason=reason,
                    )
            final_payload = snapshot_progress(str(report["state"]))
    except RunExecutionError as exc:
        return _fail(factory, reporter, rid, exc.message)
    except Exception:
        # The user-facing reason stays generic, but the traceback belongs in the
        # worker log: without it a scoring bug looks like an environment problem.
        logger.exception("Run %s failed while scoring", rid)
        _fail(
            factory,
            reporter,
            rid,
            "The worker hit an unexpected error while scoring the run.",
        )
        raise
    reporter.publish(rid, final_payload)
    return report


def _report(
    rid: uuid.UUID,
    *,
    status: str,
    state: str | RunState,
    reason: str | None = None,
    total: int = 0,
    completed: int = 0,
    failed: int = 0,
    cancelled: int = 0,
    verdict: str | None = None,
    score: float | None = None,
    partial: bool = False,
) -> dict[str, Any]:
    """JSON-able report of one execution (also the Celery result value)."""
    return {
        "run_id": str(rid),
        "status": status,
        "state": str(state),
        "reason": reason,
        "items_total": total,
        "items_completed": completed,
        "items_failed": failed,
        "items_cancelled": cancelled,
        "verdict": verdict,
        "score": score,
        "partial": partial,
    }


def _fail(
    factory: Callable[[], Session],
    reporter: ProgressReporter,
    rid: uuid.UUID,
    message: str,
) -> dict[str, Any]:
    """Record a run-level failure without ever raising from here."""
    logger.error("Run %s failed: %s", rid, message)
    try:
        with factory() as session:
            run = session.get(Run, rid)
            if run is None:
                return _report(rid, status="failed", state=RunState.FAILED, reason=message)
            if run.state == RunState.CANCELLING.value:
                target = RunState.CANCELLED
            elif run.state in (RunState.QUEUED.value, RunState.RUNNING.value):
                target = RunState.FAILED
            else:
                return _report(rid, status="failed", state=run.state, reason=message)
            update_run(
                session,
                run,
                state=target,
                verdict_reason=message,
                completed_at=utcnow(),
                is_partial=True if target == RunState.CANCELLED else run.is_partial,
            )
            session.commit()
            reporter.publish(
                rid,
                RunProgress(
                    stage=str(target),
                    started_at=run.started_at.isoformat() if run.started_at else None,
                    updated_at=utcnow().isoformat(),
                ),
            )
            return _report(
                rid,
                status=str(target),
                state=target,
                reason=message,
                partial=target == RunState.CANCELLED,
            )
    except Exception:  # a broken DB must not mask the original failure
        logger.exception("Could not record the failure of run %s", rid)
        return _report(rid, status="failed", state=RunState.FAILED, reason=message)
