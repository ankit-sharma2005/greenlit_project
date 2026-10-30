#!/usr/bin/env python3
"""Run a GreenLit quick test from a CI job."""

from __future__ import annotations

import argparse
import http.cookiejar
import json
import math
import os
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any


class GreenLitCIError(Exception):
    """A request or response prevented the CI run from completing."""


class GreenLitClient:
    def __init__(self, base_url: str, timeout: float) -> None:
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout
        cookies = http.cookiejar.CookieJar()
        self.opener = urllib.request.build_opener(
            urllib.request.HTTPCookieProcessor(cookies)
        )

    def request_json(
        self, method: str, path: str, payload: dict[str, Any] | None = None
    ) -> dict[str, Any]:
        data = json.dumps(payload).encode("utf-8") if payload is not None else None
        request = urllib.request.Request(
            f"{self.base_url}{path}",
            data=data,
            headers={"Accept": "application/json", "Content-Type": "application/json"},
            method=method,
        )
        try:
            with self.opener.open(request, timeout=self.timeout) as response:
                body = json.loads(response.read())
        except urllib.error.HTTPError as exc:
            if path.endswith("/auth/login") and exc.code == 401:
                raise GreenLitCIError("Authentication failed (HTTP 401).") from exc
            raise GreenLitCIError(
                f"GreenLit returned HTTP {exc.code} for {method} {path}."
            ) from exc
        except (urllib.error.URLError, TimeoutError, OSError) as exc:
            raise GreenLitCIError(
                f"Could not reach GreenLit at {self.base_url}: {exc}"
            ) from exc
        except json.JSONDecodeError as exc:
            raise GreenLitCIError(
                f"GreenLit returned invalid JSON for {method} {path}."
            ) from exc
        if not isinstance(body, dict):
            raise GreenLitCIError(
                f"GreenLit returned an unexpected response for {method} {path}."
            )
        return body


def _positive_number(value: str) -> float:
    try:
        number = float(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError("must be a positive number") from exc
    if not math.isfinite(number) or number <= 0:
        raise argparse.ArgumentTypeError("must be a positive number")
    return number


def _arguments(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--api-url", default=os.environ.get("GREENLIT_API_URL"))
    parser.add_argument(
        "--entry-point",
        required=True,
        choices=("http_endpoint", "prompt_app", "upload_outputs"),
    )
    parser.add_argument("--target", required=True, help="URL, prompt, or upload target")
    parser.add_argument(
        "--provider-id", help="Saved provider id required for prompt_app"
    )
    parser.add_argument("--model", help="Optional model override for prompt_app")
    parser.add_argument(
        "--csv-file", type=Path, help="CSV file used as the approved dataset"
    )
    parser.add_argument(
        "--dataset-id", help="Use an existing approved dataset instead of a CSV"
    )
    parser.add_argument(
        "--tests",
        nargs="+",
        choices=("quality", "safety", "operations"),
        default=["quality", "safety", "operations"],
    )
    parser.add_argument("--timeout", type=_positive_number, default=180.0)
    parser.add_argument("--poll-interval", type=_positive_number, default=2.0)
    parser.add_argument(
        "--fail-on",
        choices=("review",),
        help="Treat REVIEW as a pipeline failure (exit 1 instead of exit 2).",
    )
    parser.add_argument(
        "--allow-private-targets",
        action="store_true",
        help="Allow the API to connect to a private or loopback target.",
    )
    args = parser.parse_args(argv)
    if not args.api_url:
        parser.error("--api-url or GREENLIT_API_URL is required")
    parsed_api_url = urllib.parse.urlsplit(args.api_url)
    if parsed_api_url.scheme not in {"http", "https"} or not parsed_api_url.netloc:
        parser.error("--api-url must be a full http(s) URL")
    if bool(args.csv_file) == bool(args.dataset_id):
        parser.error("provide exactly one of --csv-file or --dataset-id")
    if args.entry_point == "prompt_app" and not args.provider_id:
        parser.error("--provider-id is required for prompt_app")
    return args


def _payload(args: argparse.Namespace) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "entry_point": args.entry_point,
        "target": args.target,
        "tests": args.tests,
        "allow_private_targets": args.allow_private_targets,
    }
    if args.csv_file is not None:
        try:
            payload["csv"] = args.csv_file.read_text(encoding="utf-8")
        except OSError as exc:
            raise GreenLitCIError(
                f"Could not read CSV file {args.csv_file}: {exc}"
            ) from exc
    if args.dataset_id is not None:
        payload["dataset_id"] = args.dataset_id
    if args.provider_id is not None:
        payload["provider_id"] = args.provider_id
    if args.model is not None:
        payload["model"] = args.model
    return payload


def _run(args: argparse.Namespace, email: str, password: str) -> int:
    client = GreenLitClient(args.api_url, min(args.timeout, 30.0))
    deadline = time.monotonic() + args.timeout

    remaining = deadline - time.monotonic()
    if remaining <= 0:
        raise GreenLitCIError("Timed out before authentication completed.")
    client.timeout = min(remaining, 30.0)
    client.request_json(
        "POST", "/api/v1/auth/login", {"email": email, "password": password}
    )
    remaining = deadline - time.monotonic()
    if remaining <= 0:
        raise GreenLitCIError("Timed out before the quick test was created.")
    client.timeout = min(remaining, 30.0)
    created = client.request_json("POST", "/api/v1/quick-test", _payload(args))
    run = created.get("run")
    if not isinstance(run, dict) or not isinstance(run.get("id"), str):
        raise GreenLitCIError("GreenLit did not return a run id.")
    run_id = run["id"]
    terminal = {"completed", "failed", "cancelled"}
    active = {"queued", "running", "cancelling"}

    while True:
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise GreenLitCIError(f"Timed out waiting for run {run_id}.")
        client.timeout = min(remaining, 30.0)
        run = client.request_json("GET", f"/api/v1/runs/{run_id}")
        state = run.get("state")
        if not isinstance(state, str):
            raise GreenLitCIError(f"Run {run_id} returned an invalid state.")
        if state in terminal:
            break
        if state not in active:
            raise GreenLitCIError(f"Run {run_id} returned unexpected state {state!r}.")
        time.sleep(min(args.poll_interval, max(0.0, deadline - time.monotonic())))

    if state != "completed":
        raise GreenLitCIError(
            f"Run {run_id} finished in state {state!r}: {run.get('verdict_reason')}"
        )

    verdict = run.get("verdict")
    score = run.get("score")
    if not isinstance(verdict, str) or verdict not in {"GO", "NO_GO", "REVIEW"}:
        raise GreenLitCIError(f"Run {run_id} returned unexpected verdict {verdict!r}.")
    if isinstance(score, (int, float)) and not isinstance(score, bool):
        print(f"Weighted score: {score:.2f}")
    else:
        print("Weighted score: not available")
    print(f"Verdict: {verdict}")

    metrics = run.get("metrics")
    if not isinstance(metrics, list):
        raise GreenLitCIError(f"Run {run_id} did not return its metric results.")
    failed_metrics = []
    for metric in metrics:
        if not isinstance(metric, dict):
            raise GreenLitCIError(f"Run {run_id} returned an invalid metric result.")
        if metric.get("instrumented") is not True or metric.get("passed") is not False:
            continue
        name = metric.get("name")
        metric_score = metric.get("score")
        threshold = metric.get("threshold")
        if (
            not isinstance(name, str)
            or not isinstance(metric_score, (int, float))
            or not isinstance(threshold, (int, float))
        ):
            raise GreenLitCIError(f"Run {run_id} returned an incomplete failed metric.")
        failed_metrics.append(f"{name} ({metric_score:.2f}; threshold {threshold:.2f})")
    print(f"Failed metrics: {', '.join(failed_metrics) if failed_metrics else 'none'}")
    if args.fail_on == "review" and verdict == "REVIEW":
        return 1
    return {"GO": 0, "NO_GO": 1, "REVIEW": 2}[verdict]


def main(argv: list[str] | None = None) -> int:
    args = _arguments(argv)
    email = os.environ.get("GREENLIT_EMAIL")
    password = os.environ.get("GREENLIT_PASSWORD")
    if not email or not password:
        print(
            "Set GREENLIT_EMAIL and GREENLIT_PASSWORD for API authentication.",
            file=sys.stderr,
        )
        return 3
    try:
        return _run(args, email, password)
    except GreenLitCIError as exc:
        print(f"GreenLit CI error: {exc}", file=sys.stderr)
        return 3


if __name__ == "__main__":
    raise SystemExit(main())
