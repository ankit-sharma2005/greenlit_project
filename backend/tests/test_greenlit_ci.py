"""CLI contract tests using a local fake GreenLit HTTP server."""

from __future__ import annotations

import json
import os
import subprocess
import sys
import threading
from dataclasses import dataclass, field
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any

import pytest

SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "greenlit_ci.py"


@dataclass
class Scenario:
    verdict: str = "GO"
    auth_status: int = 200
    never_finishes: bool = False
    polls: int = 0
    request_payload: dict[str, Any] = field(default_factory=dict)
    cookie_seen: bool = False


@pytest.fixture
def fake_api():
    def start(scenario: Scenario) -> tuple[str, ThreadingHTTPServer]:
        class Handler(BaseHTTPRequestHandler):
            def _respond(
                self, status: int, body: dict[str, Any], headers: dict[str, str] | None = None
            ) -> None:
                data = json.dumps(body).encode("utf-8")
                self.send_response(status)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(data)))
                for key, value in (headers or {}).items():
                    self.send_header(key, value)
                self.end_headers()
                self.wfile.write(data)

            def do_POST(self) -> None:
                length = int(self.headers.get("Content-Length", "0"))
                payload = json.loads(self.rfile.read(length) or b"{}")
                if self.path == "/api/v1/auth/login":
                    if scenario.auth_status != 200:
                        self._respond(scenario.auth_status, {"error": {"message": "invalid"}})
                        return
                    self._respond(
                        200,
                        {"user": {"email": payload["email"]}},
                        {"Set-Cookie": "greenlit_access=fake-session; Path=/; HttpOnly"},
                    )
                    return
                if self.path == "/api/v1/quick-test":
                    scenario.cookie_seen = "greenlit_access=fake-session" in self.headers.get(
                        "Cookie", ""
                    )
                    scenario.request_payload = payload
                    self._respond(202, {"run": {"id": "run-123"}})
                    return
                self._respond(404, {"error": {"message": "not found"}})

            def do_GET(self) -> None:
                scenario.cookie_seen = scenario.cookie_seen and (
                    "greenlit_access=fake-session" in self.headers.get("Cookie", "")
                )
                scenario.polls += 1
                state = "running" if scenario.never_finishes or scenario.polls == 1 else "completed"
                self._respond(
                    200,
                    {
                        "id": "run-123",
                        "state": state,
                        "verdict": scenario.verdict if state == "completed" else None,
                        "score": {"GO": 1.0, "NO_GO": 0.42, "REVIEW": 0.74}[scenario.verdict],
                        "verdict_reason": "Test verdict",
                        "metrics": [
                            {
                                "name": "answer_match",
                                "score": 0.42,
                                "threshold": 0.8,
                                "passed": scenario.verdict == "GO",
                                "instrumented": True,
                            },
                            {
                                "name": "not_instrumented",
                                "score": 0.0,
                                "threshold": 0.8,
                                "passed": False,
                                "instrumented": False,
                            },
                        ],
                    },
                )

            def log_message(self, format: str, *args: object) -> None:
                return

        server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        threading.Thread(target=server.serve_forever, daemon=True).start()
        return f"http://127.0.0.1:{server.server_port}", server

    servers: list[ThreadingHTTPServer] = []

    def run(scenario: Scenario) -> str:
        url, server = start(scenario)
        servers.append(server)
        return url

    yield run
    for server in servers:
        server.shutdown()
        server.server_close()


def _run_cli(
    api_url: str, tmp_path: Path, *, timeout: str = "2", fail_on_review: bool = False
) -> subprocess.CompletedProcess[str]:
    csv_file = tmp_path / "cases.csv"
    csv_file.write_text("question,answer\nQuestion,Answer\n", encoding="utf-8")
    args = [
        sys.executable,
        str(SCRIPT),
        "--api-url",
        api_url,
        "--entry-point",
        "http_endpoint",
        "--target",
        "http://127.0.0.1:9000/chat",
        "--csv-file",
        str(csv_file),
        "--tests",
        "quality",
        "--timeout",
        timeout,
        "--poll-interval",
        "0.01",
        "--allow-private-targets",
    ]
    if fail_on_review:
        args.extend(["--fail-on", "review"])
    env = {
        **os.environ,
        "GREENLIT_EMAIL": "ci@example.com",
        "GREENLIT_PASSWORD": "safe-test-password",
    }
    return subprocess.run(args, capture_output=True, text=True, timeout=10, env=env)


@pytest.mark.parametrize(
    ("verdict", "expected_code"),
    [("GO", 0), ("NO_GO", 1), ("REVIEW", 2)],
)
def test_cli_reports_verdict_score_and_failed_metrics(
    fake_api, tmp_path: Path, verdict: str, expected_code: int
) -> None:
    scenario = Scenario(verdict=verdict)
    result = _run_cli(fake_api(scenario), tmp_path)

    assert result.returncode == expected_code, result.stderr
    assert f"Verdict: {verdict}" in result.stdout
    expected_score = {"GO": "1.00", "NO_GO": "0.42", "REVIEW": "0.74"}[verdict]
    assert f"Weighted score: {expected_score}" in result.stdout
    if verdict == "GO":
        assert "Failed metrics: none" in result.stdout
    else:
        assert "Failed metrics: answer_match (0.42; threshold 0.80)" in result.stdout
        assert "not_instrumented" not in result.stdout
    assert scenario.cookie_seen
    assert scenario.request_payload["entry_point"] == "http_endpoint"
    assert scenario.request_payload["target"] == "http://127.0.0.1:9000/chat"
    assert scenario.request_payload["csv"].startswith("question,answer")
    assert scenario.request_payload["allow_private_targets"] is True


def test_review_can_be_configured_as_a_pipeline_failure(fake_api, tmp_path: Path) -> None:
    result = _run_cli(fake_api(Scenario(verdict="REVIEW")), tmp_path, fail_on_review=True)

    assert result.returncode == 1
    assert "Verdict: REVIEW" in result.stdout


def test_cli_returns_error_on_timeout(fake_api, tmp_path: Path) -> None:
    result = _run_cli(fake_api(Scenario(never_finishes=True)), tmp_path, timeout="0.15")

    assert result.returncode == 3
    assert "Timed out waiting for run run-123" in result.stderr


def test_cli_returns_error_for_authentication_failure(fake_api, tmp_path: Path) -> None:
    result = _run_cli(fake_api(Scenario(auth_status=401)), tmp_path)

    assert result.returncode == 3
    assert "Authentication failed" in result.stderr
