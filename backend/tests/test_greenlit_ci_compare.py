"""The CI script's --baseline compare and its own exit code.

A fake GreenLit answers login, quick-test, the run and the compare, so the exit
code contract is proven without a database. The existing contract tests are
unchanged: 0/1/2/3 keep their meaning, and 4 is only reachable with --baseline.
"""

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
    compare: dict[str, Any] = field(default_factory=dict)
    query: str = ""


def _compare_body(classification: str | None, **overrides: Any) -> dict[str, Any]:
    body: dict[str, Any] = {
        "comparable": True,
        "reasons": [],
        "classification": classification,
        "classification_reason": "the verdict went GO → REVIEW." if classification else None,
        "verdict": {"baseline": "GO", "current": "REVIEW", "direction": "worse"},
        "score": {"baseline": 0.9, "current": 0.8, "delta": -0.1},
        "metrics": [
            {"name": "answer_match", "status": "measured", "delta": -0.1},
            {"name": "groundedness", "status": "not measured", "delta": None},
        ],
        "hard_gates": {"newly_failed": [], "newly_passed": []},
        "cases": {
            "pass_to_fail": [{"row_index": 1, "input": "q"}],
            "fail_to_pass": [],
            "new_errors": [],
            "only_in_baseline": [],
            "only_in_current": [],
        },
        "noise_caution": "Repeat the run before concluding.",
    }
    body.update(overrides)
    return body


@pytest.fixture
def fake_api():
    def start(scenario: Scenario) -> str:
        class Handler(BaseHTTPRequestHandler):
            def _respond(self, status: int, body: dict[str, Any]) -> None:
                data = json.dumps(body).encode("utf-8")
                self.send_response(status)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(data)))
                if self.path.startswith("/api/v1/auth/login"):
                    self.send_header("Set-Cookie", "greenlit_access=fake; Path=/; HttpOnly")
                self.end_headers()
                self.wfile.write(data)

            def do_POST(self) -> None:
                length = int(self.headers.get("Content-Length", "0"))
                self.rfile.read(length)
                if self.path == "/api/v1/auth/login":
                    self._respond(200, {"user": {"email": "ci@example.com"}})
                    return
                if self.path == "/api/v1/quick-test":
                    self._respond(202, {"run": {"id": "run-123"}})
                    return
                self._respond(404, {"error": {"message": "not found"}})

            def do_GET(self) -> None:
                if self.path.startswith("/api/v1/runs/run-123/compare"):
                    scenario.query = self.path
                    self._respond(200, scenario.compare)
                    return
                self._respond(
                    200,
                    {
                        "id": "run-123",
                        "state": "completed",
                        "verdict": "GO",
                        "score": 1.0,
                        "verdict_reason": "fine",
                        "metrics": [],
                    },
                )

            def log_message(self, format: str, *args: object) -> None:
                return

        server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        threading.Thread(target=server.serve_forever, daemon=True).start()
        servers.append(server)
        return f"http://127.0.0.1:{server.server_port}"

    servers: list[ThreadingHTTPServer] = []
    yield start
    for server in servers:
        server.shutdown()
        server.server_close()


def _run_cli(api_url: str, tmp_path: Path, *extra: str) -> subprocess.CompletedProcess[str]:
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
        "2",
        "--poll-interval",
        "0.01",
        "--allow-private-targets",
        *extra,
    ]
    env = {
        **os.environ,
        "GREENLIT_EMAIL": "ci@example.com",
        "GREENLIT_PASSWORD": "safe-test-password",
    }
    return subprocess.run(args, capture_output=True, text=True, timeout=15, env=env)


def test_a_regressed_comparison_exits_four(fake_api, tmp_path: Path) -> None:
    scenario = Scenario(compare=_compare_body("regressed"))
    result = _run_cli(fake_api(scenario), tmp_path, "--baseline", "baseline")
    assert result.returncode == 4, result.stderr
    assert "Comparable: yes" in result.stdout
    assert "Regression: regressed" in result.stdout
    assert "Verdict change: GO -> REVIEW (worse)" in result.stdout
    assert "Score delta: -0.10" in result.stdout
    assert "Cases pass -> fail: 1" in result.stdout
    assert "Metric not measured on both sides: groundedness" in result.stdout
    assert "against=baseline" in scenario.query
    assert "tolerance=0.05" in scenario.query


def test_an_unchanged_comparison_keeps_the_verdict_code(fake_api, tmp_path: Path) -> None:
    scenario = Scenario(compare=_compare_body("unchanged"))
    result = _run_cli(fake_api(scenario), tmp_path, "--baseline", "baseline")
    assert result.returncode == 0, result.stderr
    assert "Regression: unchanged" in result.stdout


def test_a_not_comparable_answer_prints_reasons_and_no_deltas(fake_api, tmp_path: Path) -> None:
    scenario = Scenario(
        compare=_compare_body(
            None,
            comparable=False,
            reasons=["the dataset version is different"],
            metrics=[],
        )
    )
    result = _run_cli(fake_api(scenario), tmp_path, "--baseline", "run-77", "--tolerance", "0.2")
    assert result.returncode == 0, result.stderr
    assert "Comparable: no" in result.stdout
    assert "Not comparable: the dataset version is different" in result.stdout
    assert "Score delta" not in result.stdout
    assert "against=run-77" in scenario.query
    assert "tolerance=0.2" in scenario.query


def test_a_tolerance_outside_the_range_is_refused(fake_api, tmp_path: Path) -> None:
    result = _run_cli(
        fake_api(Scenario(compare=_compare_body("regressed"))),
        tmp_path,
        "--baseline",
        "baseline",
        "--tolerance",
        "0.9",
    )
    assert result.returncode == 2
    assert "between 0 and 0.5" in result.stderr


def test_without_baseline_the_exit_codes_are_unchanged(fake_api, tmp_path: Path) -> None:
    result = _run_cli(fake_api(Scenario(compare=_compare_body("regressed"))), tmp_path)
    assert result.returncode == 0
    assert "Regression:" not in result.stdout
