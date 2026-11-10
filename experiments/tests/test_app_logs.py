"""The app's own truth log.

One JSON line per request, written where the analysis looks for it: the question,
whether the app's seeded fault fired, and the answer. Nothing else may appear, so
the file can be read without meeting a token or an identifier.
"""

from __future__ import annotations

import json
import threading
import urllib.request
from pathlib import Path

from behaviour import handle, load_faq
from config import load_config
from server import append_log, build_server

ROOT = Path(__file__).resolve().parent.parent


def _config(app_id: str = "app01"):
    return load_config(ROOT / "apps" / "app_config" / f"{app_id}.json")


def test_one_line_holds_the_question_the_fault_and_the_answer(tmp_path: Path) -> None:
    config = _config()

    path = append_log(
        config, "What is 2 + 2?", {"answer": "4", "faulted": False}, tmp_path
    )
    append_log(config, "What is 3 + 3?", {"answer": "7", "faulted": True}, tmp_path)

    lines = path.read_text(encoding="utf-8").splitlines()
    assert path.name == "app01.jsonl"
    assert len(lines) == 2
    assert json.loads(lines[0]) == {
        "question": "What is 2 + 2?",
        "faulted": False,
        "answer": "4",
    }
    assert json.loads(lines[1])["faulted"] is True
    # Nothing that identifies a caller, a token or a header may be in the record.
    assert set(json.loads(lines[0])) == {"question", "faulted", "answer"}


def test_a_live_request_writes_the_line_the_analysis_reads(tmp_path: Path) -> None:
    config = _config()
    server = build_server(config, port=0, log_dir=tmp_path)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        # The app binds 0.0.0.0 for the API container; a test connects from here.
        port = server.server_address[1]
        body = json.dumps({"question": "What is 10 + 5?"}).encode("utf-8")
        request = urllib.request.Request(
            f"http://127.0.0.1:{port}/",
            data=body,
            headers={"Content-Type": "application/json"},
        )
        with urllib.request.urlopen(request, timeout=10) as response:
            answer = json.loads(response.read())["answer"]
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)

    log = tmp_path / f"{config.id}.jsonl"
    row = json.loads(log.read_text(encoding="utf-8").strip())

    assert row["question"] == "What is 10 + 5?"
    assert row["answer"] == answer
    # app01 is the correct variant: this question is one it answers properly.
    assert row["faulted"] is handle(config, "What is 10 + 5?", load_faq())["faulted"]
