"""Run the accuracy experiment: ten controlled apps, N repeated runs each, exported.

Nothing is judged here. The runner's only jobs are to make GreenLit run the
declared apps on the same approved dataset, to wait honestly (including for a run
that stopped at its own cap), and to write every verdict and per-case export into
``experiments/results/<timestamp>/`` with a manifest of what was used.

Usage::

    python experiments/runner/run_experiment.py --dry-run
    GREENLIT_API=http://localhost:8003 GREENLIT_EMAIL=... GREENLIT_PASSWORD=... \\
        python experiments/runner/run_experiment.py --runs 5

Credentials come only from the environment and are never printed.
"""

from __future__ import annotations

import argparse
import csv
import json
import os
import sys
import time
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "apps"))
sys.path.insert(0, str(ROOT / "runner"))

from config import AppConfig, load_all
from greenlit_client import (
    GreenLitClient,
    GreenLitError,
    RateLimited,
    normalise_api_url,
)

DEFAULT_API = "http://localhost:8003"
RESULTS_DIR = ROOT / "results"
TRUTH_PATH = ROOT / "data" / "ground_truth.json"
DATASET_NAME = "experiments-questions-120"
ANSWER_PATH = "$.answer"
CONTEXT_PATH = "$.context"
RAG_APPS = {"app08", "app09"}
TERMINAL_STATES = {
    "completed",
    "failed",
    "cancelled",
    "stopped_by_limit",
    "interrupted",
}
ACTIVE_STATES = {"queued", "running", "cancelling"}
KEEP_ACTIVE_FOR_VERDICT = {"stopped_by_limit"}


class ExperimentError(Exception):
    """The experiment cannot continue; the message is safe to print."""


@dataclass(frozen=True)
class AppPlan:
    """One app as the experiment will run it."""

    config: AppConfig
    target_url: str
    context_path: str | None

    @property
    def is_rag(self) -> bool:
        return self.config.id in RAG_APPS


def load_declared_truth() -> dict[str, dict[str, Any]]:
    """The declared truth, refusing to continue when a variant is undeclared."""
    if not TRUTH_PATH.exists():
        raise ExperimentError(
            f"{TRUTH_PATH} is missing: run python experiments/build_ground_truth.py first"
        )
    document = json.loads(TRUTH_PATH.read_text(encoding="utf-8"))
    declared = {
        app["id"]: app for app in document.get("apps", []) if isinstance(app, dict)
    }
    for config in load_all():
        entry = declared.get(config.id)
        if entry is None:
            raise ExperimentError(f"{config.id} has no declaration in {TRUTH_PATH}")
        if entry.get("expected_verdict") not in {"GO", "REVIEW", "NO_GO", "UNCERTAIN"}:
            raise ExperimentError(f"{config.id} has no declared expected_verdict")
    return declared


def build_plan(
    selected: list[str] | None, host: str, context_for_all: bool = False
) -> list[AppPlan]:
    """The apps to run, in id order, with their target URLs."""
    configs = load_all()
    if selected:
        wanted = set(selected)
        unknown = wanted - {config.id for config in configs}
        if unknown:
            raise ExperimentError(f"unknown app id(s): {', '.join(sorted(unknown))}")
        configs = [config for config in configs if config.id in wanted]
    plans = [
        AppPlan(
            config=config,
            target_url=f"http://{host}:{config.port}/",
            context_path=CONTEXT_PATH
            if (context_for_all or config.id in RAG_APPS)
            else None,
        )
        for config in configs
    ]
    if not plans:
        raise ExperimentError("no apps selected")
    return plans


def print_plan(
    plans: list[AppPlan], runs: int, api: str, declared: dict[str, Any]
) -> None:
    """The dry-run: everything the experiment would do, and nothing it would send."""
    print(f"GreenLit API: {api}")
    print(f"Dataset: {DATASET_NAME} (uploaded and approved on the first real run)")
    print(f"Repeats per app: {runs}")
    print(f"Apps: {len(plans)}")
    for plan in plans:
        entry = declared.get(plan.config.id, {})
        print(
            f"  {plan.config.id} port {plan.config.port} -> {plan.target_url} "
            f"| expected {entry.get('expected_verdict')} | seed {plan.config.seed} "
            f"| context {plan.context_path or 'none'}"
        )
    print("Requests: POST /runs per app per repeat; no request is sent by --dry-run.")


def _iso_now() -> str:
    return datetime.now(UTC).isoformat()


def wait_for_run(
    client: GreenLitClient, run_id: str, *, timeout_seconds: float, poll_seconds: float
) -> dict[str, Any]:
    """Poll until the run reaches a terminal state, or fail with its last state."""
    deadline = time.monotonic() + timeout_seconds
    last_state = "unknown"
    while True:
        run = client.get_run(run_id)
        state = run.get("state")
        if isinstance(state, str):
            last_state = state
        if state in TERMINAL_STATES:
            return run
        if state not in ACTIVE_STATES:
            raise ExperimentError(f"run {run_id} returned unexpected state {state!r}")
        if time.monotonic() >= deadline:
            raise ExperimentError(
                f"timed out after {timeout_seconds:.0f}s waiting for run {run_id} "
                f"(last state {last_state!r})"
            )
        time.sleep(poll_seconds)


def run_app(
    client: GreenLitClient,
    plan: AppPlan,
    *,
    dataset_version_id: str,
    runs: int,
    timestamp: str,
    results_dir: Path,
    timeout_seconds: float,
    poll_seconds: float,
    max_cases: int | None,
    log: Any,
) -> list[dict[str, Any]]:
    """Check the target once, then start and export ``runs`` runs of one app."""
    target_id = client.ensure_target(
        f"exp-{plan.config.id}",
        plan.target_url,
        ANSWER_PATH,
        plan.context_path or "",
    )
    check = client.check_target(plan.target_url, ANSWER_PATH, plan.context_path or "")
    if not check.get("success"):
        log(f"  {plan.config.id}: first-contact check failed: {check.get('message')}")
        return [
            {
                "app": plan.config.id,
                "run_index": 0,
                "run_id": "",
                "state": "check_failed",
                "verdict": "",
                "score": "",
                "verdict_reason": str(check.get("message") or ""),
                "expected_verdict": plan.config.expected_verdict,
                "csv_path": "",
                "json_path": "",
            }
        ]
    app_dir = results_dir / plan.config.id
    app_dir.mkdir(parents=True, exist_ok=True)
    rows: list[dict[str, Any]] = []
    for index in range(1, runs + 1):
        payload: dict[str, Any] = {
            "entry_point": "http_endpoint",
            "target": plan.target_url,
            "dataset_version_id": dataset_version_id,
            "test_types": ["quality", "safety", "operations"],
            "name": f"{plan.config.id} repeat {index} of {runs} ({timestamp})",
            "method": "POST",
            "answer_path": ANSWER_PATH,
            "timeout_seconds": 60,
            "allow_private_targets": True,
            "max_duration_seconds": 1800,
            "permission_confirmed": False,
        }
        if plan.context_path:
            payload["context_path"] = plan.context_path
        if max_cases is not None:
            payload["max_cases"] = max_cases
        started = client.start_run(payload, idempotency_key=uuid.uuid4().hex)
        run_id = str(started.get("id") or "")
        if not run_id:
            raise ExperimentError(f"{plan.config.id}: GreenLit returned no run id")
        finished = wait_for_run(
            client, run_id, timeout_seconds=timeout_seconds, poll_seconds=poll_seconds
        )
        state = str(finished.get("state") or "")
        verdict = finished.get("verdict")
        score = finished.get("score")
        reason = finished.get("verdict_reason")
        csv_path = app_dir / f"run-{index}.csv"
        json_path = app_dir / f"run-{index}.report.json"
        try:
            csv_path.write_text(client.report(run_id, "csv"), encoding="utf-8")
            json_path.write_text(client.report(run_id, "json"), encoding="utf-8")
        except GreenLitError as exc:
            log(f"  {plan.config.id} run {index}: export failed: {exc}")
        row = {
            "app": plan.config.id,
            "run_index": index,
            "run_id": run_id,
            "state": state,
            "verdict": verdict if isinstance(verdict, str) else "",
            "score": f"{score:.4f}" if isinstance(score, (int, float)) else "",
            "verdict_reason": str(reason or ""),
            "expected_verdict": plan.config.expected_verdict,
            "csv_path": str(csv_path.relative_to(results_dir.parent)),
            "json_path": str(json_path.relative_to(results_dir.parent)),
            "target_id": target_id,
        }
        rows.append(row)
        log(
            f"  {plan.config.id} run {index}/{runs}: {state} "
            f"{row['verdict'] or '(no verdict)'} score={row['score'] or 'n/a'}"
        )
    return rows


def write_summary(rows: list[dict[str, Any]], results_dir: Path) -> None:
    """One row per run, in a stable column order."""
    fieldnames = [
        "app",
        "run_index",
        "run_id",
        "state",
        "verdict",
        "score",
        "expected_verdict",
        "verdict_reason",
        "csv_path",
        "json_path",
    ]
    with (results_dir / "runs.csv").open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def write_manifest(
    *,
    results_dir: Path,
    api: str,
    plans: list[AppPlan],
    declared: dict[str, Any],
    dataset: dict[str, Any],
    runs: int,
    started_at: str,
    client: GreenLitClient | None,
    extra: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """What was run, with what, on which engine — so a session can be reproduced."""
    health: dict[str, Any] = {}
    criteria: dict[str, Any] = {}
    judge: dict[str, Any] | None = None
    if client is not None:
        try:
            health = client.health()
            criteria = client.criteria()
            judge = client.selected_judge()
        except GreenLitError as exc:  # a manifest is still worth writing
            health = {"error": str(exc)}
    manifest: dict[str, Any] = {
        "experiment": "greenlit-accuracy",
        "greenlit_api": api,
        "greenlit_health": health,
        "criteria": criteria,
        "judge": judge,
        "dataset": dataset,
        "dataset_name": DATASET_NAME,
        "runs_per_app": runs,
        "started_at": started_at,
        "finished_at": _iso_now(),
        "apps": [
            {
                "id": plan.config.id,
                "port": plan.config.port,
                "target_url": plan.target_url,
                "seed": plan.config.seed,
                "fault": plan.config.fault,
                "context_path": plan.context_path,
                "expected_verdict": declared.get(plan.config.id, {}).get(
                    "expected_verdict"
                ),
                "expected_reason": declared.get(plan.config.id, {}).get(
                    "expected_reason"
                ),
                "uncertain_truth": declared.get(plan.config.id, {}).get(
                    "uncertain_truth", False
                ),
            }
            for plan in plans
        ],
        "note": (
            "Local apps only; the safety probes are GreenLit's own built-in set and no "
            "third-party site was contacted."
        ),
    }
    if extra:
        manifest.update(extra)
    (results_dir / "manifest.json").write_text(
        json.dumps(manifest, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    return manifest


def parse_args(argv: list[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--api", default=os.environ.get("GREENLIT_API", DEFAULT_API))
    parser.add_argument(
        "--runs", type=int, default=5, help="Repeats per app (default 5)"
    )
    parser.add_argument(
        "--apps", default="", help="Comma-separated app ids (default: all ten)"
    )
    parser.add_argument(
        "--host", default="host.docker.internal", help="Where GreenLit reaches the apps"
    )
    parser.add_argument(
        "--dry-run", action="store_true", help="Print the plan, send nothing"
    )
    parser.add_argument(
        "--timeout", type=float, default=1800.0, help="Per-run wait, seconds"
    )
    parser.add_argument(
        "--poll", type=float, default=5.0, help="Poll interval, seconds"
    )
    parser.add_argument("--max-cases", type=int, default=None)
    parser.add_argument("--results-dir", type=Path, default=None)
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    try:
        api = normalise_api_url(args.api)
        declared = load_declared_truth()
        selected = [item.strip() for item in args.apps.split(",") if item.strip()]
        plans = build_plan(selected or None, args.host)
        if args.runs < 1:
            raise ExperimentError("--runs must be at least 1")
        if args.dry_run:
            print_plan(plans, args.runs, api, declared)
            return 0

        email = os.environ.get("GREENLIT_EMAIL")
        password = os.environ.get("GREENLIT_PASSWORD")
        if not email or not password:
            print(
                "Set GREENLIT_EMAIL and GREENLIT_PASSWORD in the environment (never on the "
                "command line).",
                file=sys.stderr,
            )
            return 2

        timestamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
        results_dir = args.results_dir or (RESULTS_DIR / timestamp)
        results_dir.mkdir(parents=True, exist_ok=True)
        started_at = _iso_now()
        csv_text = (ROOT / "data" / "questions.csv").read_text(encoding="utf-8")

        client = GreenLitClient(api)
        client.login(email, password)
        dataset = client.ensure_dataset(DATASET_NAME, csv_text)
        print(
            f"dataset {DATASET_NAME}: version {dataset['version_no']} "
            f"({'created' if dataset['created'] else 'reused'})"
        )
        rows: list[dict[str, Any]] = []
        for plan in plans:
            print(
                f"{plan.config.id} -> {plan.target_url} (expected {plan.config.expected_verdict})"
            )
            rows.extend(
                run_app(
                    client,
                    plan,
                    dataset_version_id=str(dataset["version_id"]),
                    runs=args.runs,
                    timestamp=timestamp,
                    results_dir=results_dir,
                    timeout_seconds=args.timeout,
                    poll_seconds=args.poll,
                    max_cases=args.max_cases,
                    log=print,
                )
            )
        write_summary(rows, results_dir)
        write_manifest(
            results_dir=results_dir,
            api=api,
            plans=plans,
            declared=declared,
            dataset=dataset,
            runs=args.runs,
            started_at=started_at,
            client=client,
        )
        print(f"results in {results_dir}")
        return 0
    except RateLimited as exc:
        print(
            f"stopped: {exc}. No retry loop: fix the limit and run again.",
            file=sys.stderr,
        )
        return 4
    except GreenLitError as exc:
        print(f"GreenLit error: {exc}", file=sys.stderr)
        return 3
    except ExperimentError as exc:
        print(f"experiment error: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
