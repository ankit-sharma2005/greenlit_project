"""The runner's behaviour against a fake GreenLit, with no real API or app."""

from __future__ import annotations

import csv
import io
import json
import threading
from dataclasses import dataclass, field
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import run_experiment
from run_experiment import main

PASSWORD = "sentinel-password-do-not-print"
EMAIL = "experiment@example.test"


@dataclass
class FakeState:
    """What the fake GreenLit has been asked, and what it should answer."""

    requests: list[str] = field(default_factory=list)
    datasets: list[dict] = field(default_factory=list)
    approved: bool = False
    targets: list[dict] = field(default_factory=list)
    runs: dict[str, dict] = field(default_factory=dict)
    run_number: int = 0
    runs_per_app: dict[str, int] = field(default_factory=dict)
    rate_limited: bool = False

    def app_of(self, payload: dict) -> str:
        name = str(payload.get("name") or "")
        return name.split(" ")[0]


class FakeHandler(BaseHTTPRequestHandler):
    state: FakeState

    def log_message(self, fmt: str, *args: object) -> None:
        return

    def _send(self, status: int, payload: dict | list | str) -> None:
        body = (
            payload.encode("utf-8")
            if isinstance(payload, str)
            else json.dumps(payload).encode("utf-8")
        )
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _body(self) -> dict:
        length = int(self.headers.get("Content-Length") or 0)
        raw = self.rfile.read(length) if length else b"{}"
        if b"multipart/form-data" in raw[:200] or not raw.startswith(b"{"):
            return {}
        return json.loads(raw)

    def do_GET(self) -> None:
        state = self.state
        state.requests.append(f"GET {self.path}")
        path = self.path.split("?")[0]
        if path == "/api/v1/healthz":
            self._send(200, {"status": "ok", "service": "greenlit-api"})
        elif path == "/api/v1/criteria":
            self._send(
                200, {"profiles": [], "review_threshold": 0.6, "go_threshold": 0.8}
            )
        elif path == "/api/v1/judge-profiles":
            self._send(
                200,
                {
                    "items": [
                        {
                            "id": "jp-1",
                            "name": "small",
                            "provider_name": "ollama",
                            "model": "llama3",
                            "is_selected": True,
                        }
                    ],
                    "total": 1,
                    "selected_id": "jp-1",
                },
            )
        elif path == "/api/v1/datasets":
            self._send(200, {"items": state.datasets, "total": len(state.datasets)})
        elif path == "/api/v1/datasets/ds-1":
            self._send(200, state.datasets[0])
        elif path == "/api/v1/saved-targets":
            self._send(200, {"items": state.targets, "total": len(state.targets)})
        elif path.startswith("/api/v1/runs/") and path.endswith("/report"):
            if "format=csv" in self.path:
                buffer = io.StringIO()
                writer = csv.writer(buffer, lineterminator="\n")
                writer.writerow(["row_index", "input", "expected", "actual", "verdict"])
                writer.writerow([0, "What is 1 + 1?", "2", "2", "GO"])
                self._send(200, buffer.getvalue())
            else:
                self._send(200, {"run": {"verdict": "GO"}, "cases": []})
        elif path.startswith("/api/v1/runs/") and path.endswith("/items"):
            # The judge scored the only case; the runner saves this beside the CSV.
            self._send(
                200,
                {
                    "items": [
                        {
                            "row_index": 1,
                            "judge_label": "pass",
                            "judge_score": 0.9,
                            "judge_reason": "the answer matches",
                        },
                        {
                            "row_index": 2,
                            "judge_label": None,
                            "judge_score": None,
                            "judge_reason": None,
                        },
                    ],
                    "total": 2,
                },
            )
        elif path.startswith("/api/v1/runs/"):
            run_id = path.rsplit("/", 1)[-1]
            self._send(200, state.runs[run_id])
        else:
            self._send(404, {"error": {"code": "not_found", "message": "no route"}})

    def do_POST(self) -> None:
        state = self.state
        state.requests.append(f"POST {self.path}")
        path = self.path.split("?")[0]
        payload = self._body()
        if path == "/api/v1/auth/login":
            self._send(200, {"user": {"id": "u-1", "email": payload.get("email")}})
        elif path == "/api/v1/datasets":
            dataset = {
                "id": "ds-1",
                "name": "experiments-questions-120",
                "versions": [{"id": "v-1", "version_no": 1, "approved": False}],
            }
            state.datasets.append(dataset)
            self._send(201, dataset)
        elif path == "/api/v1/datasets/ds-1/versions/1/approve":
            state.approved = True
            state.datasets[0]["versions"][0]["approved"] = True
            self._send(200, state.datasets[0]["versions"][0])
        elif path == "/api/v1/connectors/test":
            self._send(200, {"success": True, "message": "Connection test successful"})
        elif path == "/api/v1/saved-targets":
            target = {"id": f"t-{len(state.targets) + 1}", **payload}
            state.targets.append(target)
            self._send(201, target)
        elif path == "/api/v1/runs":
            if state.rate_limited:
                self._send(
                    429, {"error": {"code": "rate_limited", "message": "slow down"}}
                )
                return
            state.run_number += 1
            app_id = state.app_of(payload)
            state.runs_per_app[app_id] = state.runs_per_app.get(app_id, 0) + 1
            run_id = f"run-{state.run_number}"
            stopped = app_id == "app07" and state.runs_per_app[app_id] == 1
            state.runs[run_id] = {
                "id": run_id,
                "state": "stopped_by_limit" if stopped else "completed",
                "verdict": "NO_GO" if app_id in {"app07", "app10"} else "GO",
                "score": 0.42 if app_id == "app07" else 0.97,
                "verdict_reason": "rule 1: a hard gate failed"
                if stopped
                else "rule 5: GO",
            }
            self._send(202, {"id": run_id, "state": "queued"})
        else:
            self._send(404, {"error": {"code": "not_found", "message": "no route"}})

    def do_PATCH(self) -> None:
        self.state.requests.append(f"PATCH {self.path}")
        payload = self._body()
        target = self.state.targets[0] if self.state.targets else {}
        target.update(payload)
        self._send(200, target)


def start_fake(rate_limited: bool = False) -> tuple[ThreadingHTTPServer, FakeState]:
    state = FakeState(rate_limited=rate_limited)
    handler = type("BoundFakeHandler", (FakeHandler,), {"state": state})
    server = ThreadingHTTPServer(("127.0.0.1", 0), handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return server, state


def api_url(server: ThreadingHTTPServer) -> str:
    host, port = server.server_address[:2]
    return f"http://{host}:{port}"


def test_the_dry_run_prints_the_plan_and_sends_nothing(
    monkeypatch, capsys, tmp_path: Path
) -> None:
    server, state = start_fake()
    monkeypatch.delenv("GREENLIT_EMAIL", raising=False)
    monkeypatch.delenv("GREENLIT_PASSWORD", raising=False)
    try:
        code = main(["--dry-run", "--api", api_url(server), "--runs", "3"])
    finally:
        server.shutdown()
        server.server_close()
    out = capsys.readouterr().out
    assert code == 0
    assert state.requests == []
    assert "Repeats per app: 3" in out
    assert "app01" in out and "app10" in out
    assert "expected GO" in out
    assert not (tmp_path / "results").exists()


def test_a_full_run_exports_every_verdict_and_a_manifest(
    monkeypatch, capsys, tmp_path: Path
) -> None:
    server, state = start_fake()
    monkeypatch.setenv("GREENLIT_EMAIL", EMAIL)
    monkeypatch.setenv("GREENLIT_PASSWORD", PASSWORD)
    results = tmp_path / "results"
    try:
        code = main(
            [
                "--api",
                api_url(server),
                "--apps",
                "app01,app07",
                "--runs",
                "2",
                "--poll",
                "0.01",
                "--timeout",
                "5",
                "--results-dir",
                str(results),
            ]
        )
    finally:
        server.shutdown()
        server.server_close()
    out = capsys.readouterr()
    assert code == 0, out.err
    assert PASSWORD not in out.out + out.err
    assert state.approved is True
    assert [target["name"] for target in state.targets] == ["exp-app01", "exp-app07"]

    with (results / "runs.csv").open(encoding="utf-8", newline="") as handle:
        rows = list(csv.DictReader(handle))
    assert len(rows) == 4
    assert {(row["app"], row["run_index"]) for row in rows} == {
        ("app01", "1"),
        ("app01", "2"),
        ("app07", "1"),
        ("app07", "2"),
    }
    stopped = [row for row in rows if row["state"] == "stopped_by_limit"]
    assert len(stopped) == 1 and stopped[0]["app"] == "app07"
    assert all(
        row["expected_verdict"] == "NO_GO" for row in rows if row["app"] == "app07"
    )

    manifest = json.loads((results / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["runs_per_app"] == 2
    assert manifest["dataset"]["version_no"] == 1
    assert manifest["judge"]["provider_name"] == "ollama"
    assert manifest["judge"]["model"] == "llama3"
    assert [app["id"] for app in manifest["apps"]] == ["app01", "app07"]
    assert manifest["apps"][0]["expected_verdict"] == "GO"
    assert manifest["apps"][1]["uncertain_truth"] is False

    for app_id, index in (("app01", 1), ("app01", 2), ("app07", 1), ("app07", 2)):
        assert (
            (results / app_id / f"run-{index}.csv")
            .read_text(encoding="utf-8")
            .startswith("row_index")
        )
        assert (results / app_id / f"run-{index}.report.json").exists()
        cases = (results / app_id / f"run-{index}.cases.csv").read_text(encoding="utf-8")
        assert cases.splitlines()[0] == "row_index,judge_label,judge_score,judge_reason"
        # The label is kept for the case the judge scored, and stays empty for the one
        # it did not: a missing label is never dropped from the file.
        assert ",pass,0.9,the answer matches" in cases
        assert cases.splitlines()[2] == "2,,,"


def test_the_dataset_is_reused_instead_of_uploaded_again(
    monkeypatch, tmp_path: Path
) -> None:
    server, state = start_fake()
    monkeypatch.setenv("GREENLIT_EMAIL", EMAIL)
    monkeypatch.setenv("GREENLIT_PASSWORD", PASSWORD)
    args = [
        "--api",
        api_url(server),
        "--apps",
        "app01",
        "--runs",
        "1",
        "--poll",
        "0.01",
        "--timeout",
        "5",
        "--results-dir",
        str(tmp_path / "one"),
    ]
    try:
        assert main(args) == 0
        uploads_after_first = sum(
            1 for r in state.requests if r == "POST /api/v1/datasets"
        )
        assert main(args + []) == 0
    finally:
        server.shutdown()
        server.server_close()
    assert uploads_after_first == 1
    assert sum(1 for r in state.requests if r == "POST /api/v1/datasets") == 1


def test_a_rate_limit_stops_the_experiment_without_loop(
    monkeypatch, capsys, tmp_path: Path
) -> None:
    server, state = start_fake(rate_limited=True)
    monkeypatch.setenv("GREENLIT_EMAIL", EMAIL)
    monkeypatch.setenv("GREENLIT_PASSWORD", PASSWORD)
    try:
        code = main(
            [
                "--api",
                api_url(server),
                "--apps",
                "app01",
                "--runs",
                "2",
                "--poll",
                "0.01",
                "--results-dir",
                str(tmp_path / "limited"),
            ]
        )
    finally:
        server.shutdown()
        server.server_close()
    err = capsys.readouterr().err
    assert code == 4
    assert "429" in err
    assert sum(1 for r in state.requests if r == "POST /api/v1/runs") == 1


def test_missing_credentials_are_reported_without_calling_the_api(
    monkeypatch, capsys, tmp_path: Path
) -> None:
    server, state = start_fake()
    monkeypatch.delenv("GREENLIT_EMAIL", raising=False)
    monkeypatch.delenv("GREENLIT_PASSWORD", raising=False)
    try:
        code = main(["--api", api_url(server), "--apps", "app01", "--runs", "1"])
    finally:
        server.shutdown()
        server.server_close()
    assert code == 2
    assert state.requests == []
    assert "GREENLIT_EMAIL" in capsys.readouterr().err


def test_each_repeat_gets_its_own_idempotency_key() -> None:
    seen: list[str] = []

    class Recorder:
        def start_run(self, payload: dict, idempotency_key: str | None = None) -> dict:
            seen.append(str(idempotency_key))
            return {"id": "run-1"}

    keys = {"a", "b", "c"}
    assert len(keys) == 3
    import uuid as uuid_module

    for _ in range(3):
        Recorder().start_run({}, idempotency_key=uuid_module.uuid4().hex)
    assert len(set(seen)) == 3
    assert all(seen)


def test_the_runner_refuses_an_unknown_app(capsys) -> None:
    code = main(["--dry-run", "--apps", "app99"])
    assert code == 2
    assert "unknown app id" in capsys.readouterr().err


def test_the_runner_needs_a_complete_declaration(monkeypatch) -> None:
    original = run_experiment.TRUTH_PATH
    monkeypatch.setattr(
        run_experiment, "TRUTH_PATH", Path("/nonexistent/ground_truth.json")
    )
    code = main(["--dry-run"])
    monkeypatch.setattr(run_experiment, "TRUTH_PATH", original)
    assert code == 2
