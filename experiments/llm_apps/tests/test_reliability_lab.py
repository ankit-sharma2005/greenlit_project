"""A6: the reliability lab's four modes, its seeded sets and its control door."""

from __future__ import annotations

import json
import threading
from pathlib import Path
from typing import Any

import pytest
import requests
from reliability_lab.app import create_server, is_flaky, seeded_delay


def _serve(server: Any) -> str:
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    return f"http://127.0.0.1:{server.server_address[1]}"


@pytest.fixture()
def lab(tmp_path: Path) -> Any:
    server = create_server("ok", control_enabled=False, log_dir=tmp_path)
    url = _serve(server)
    yield url
    server.shutdown()
    server.server_close()


def test_health_and_answer_shapes(lab: str) -> None:
    health = requests.get(f"{lab}/health", timeout=10).json()
    assert health["status"] == "ok" and health["app"] == "reliability-lab"
    answer = requests.post(f"{lab}/", json={"question": "Are you up?"}, timeout=10)
    assert answer.status_code == 200
    assert answer.json() == {"answer": "Reliability lab received: Are you up?"}


def test_the_flaky_set_is_the_same_every_time() -> None:
    questions = [f"question {index}" for index in range(60)]
    first = [question for question in questions if is_flaky(question)]
    second = [question for question in questions if is_flaky(question)]
    assert first == second
    assert 3 <= len(first) <= 24  # 20 % of 60, with generous slack


def test_flaky_mode_fails_exactly_the_seeded_questions(tmp_path: Path) -> None:
    server = create_server("flaky_20", control_enabled=False, log_dir=tmp_path)
    url = _serve(server)
    try:
        questions = [f"case {index}" for index in range(40)]
        statuses = [
            requests.post(
                f"{url}/", json={"question": question}, timeout=10
            ).status_code
            for question in questions
        ]
        expected = [500 if is_flaky(question) else 200 for question in questions]
        assert statuses == expected
        assert 200 in statuses and 500 in statuses
    finally:
        server.shutdown()
        server.server_close()


def test_slow_mode_waits_but_not_forever(tmp_path: Path) -> None:
    server = create_server(
        "slow", control_enabled=False, delay_seconds=0.05, log_dir=tmp_path
    )
    url = _serve(server)
    try:
        started = __import__("time").monotonic()
        response = requests.post(
            f"{url}/", json={"question": "slow please"}, timeout=10
        )
        elapsed = __import__("time").monotonic() - started
        assert response.status_code == 200
        assert elapsed >= 0.04
        assert elapsed < 2
        assert seeded_delay("slow please", 0.05) <= 0.05
    finally:
        server.shutdown()
        server.server_close()


def test_rate_limited_mode_answers_429_with_retry_after(tmp_path: Path) -> None:
    clock = {"now": 1000.0}
    server = create_server(
        "rate_limited",
        control_enabled=False,
        rate_limit=2,
        rate_window_seconds=10,
        clock=lambda: clock["now"],
        log_dir=tmp_path,
    )
    url = _serve(server)
    try:
        assert (
            requests.post(f"{url}/", json={"question": "one"}, timeout=10).status_code
            == 200
        )
        assert (
            requests.post(f"{url}/", json={"question": "two"}, timeout=10).status_code
            == 200
        )
        limited = requests.post(f"{url}/", json={"question": "three"}, timeout=10)
        assert limited.status_code == 429
        assert limited.headers["Retry-After"].isdigit()
        assert limited.json()["error"] == "rate_limited"

        clock["now"] += 11
        assert (
            requests.post(f"{url}/", json={"question": "four"}, timeout=10).status_code
            == 200
        )
    finally:
        server.shutdown()
        server.server_close()


def test_the_control_door_is_closed_without_the_flag_or_off_loopback(
    tmp_path: Path,
) -> None:
    closed = create_server("ok", control_enabled=False, log_dir=tmp_path)
    url = _serve(closed)
    try:
        refused = requests.post(
            f"{url}/_control/mode", json={"mode": "slow"}, timeout=10
        )
        assert refused.status_code == 404
    finally:
        closed.shutdown()
        closed.server_close()

    from common.control import is_loopback

    assert is_loopback("127.0.0.1") is True
    assert is_loopback("10.0.0.7") is False
    assert is_loopback(None) is False


def test_the_control_door_flips_a_known_mode_only(tmp_path: Path) -> None:
    open_server = create_server("ok", control_enabled=True, log_dir=tmp_path)
    url = _serve(open_server)
    try:
        flipped = requests.post(
            f"{url}/_control/mode", json={"mode": "slow"}, timeout=10
        )
        assert flipped.status_code == 200
        assert requests.get(f"{url}/health", timeout=10).json()["mode"] == "slow"
        unknown = requests.post(
            f"{url}/_control/mode", json={"mode": "nope"}, timeout=10
        )
        assert unknown.status_code == 400
    finally:
        open_server.shutdown()
        open_server.server_close()


def test_hostile_input_is_a_400_and_never_a_crash(tmp_path: Path) -> None:
    server = create_server("ok", control_enabled=False, log_dir=tmp_path)
    url = _serve(server)
    try:
        too_long = requests.post(f"{url}/", json={"question": "x" * 400}, timeout=10)
        assert too_long.status_code == 400
        empty = requests.post(f"{url}/", json={}, timeout=10)
        assert empty.status_code == 400
        malformed = requests.post(
            f"{url}/",
            data=b"{not json",
            headers={"Content-Type": "application/json"},
            timeout=10,
        )
        assert malformed.status_code == 400
        unicode = requests.post(
            f"{url}/", json={"question": "héllo ✓ 日本語"}, timeout=10
        )
        assert unicode.status_code == 200
        again = requests.get(f"{url}/health", timeout=10)
        assert again.status_code == 200
    finally:
        server.shutdown()
        server.server_close()


def test_the_log_holds_no_header_and_no_secret(tmp_path: Path) -> None:
    server = create_server("ok", control_enabled=False, log_dir=tmp_path)
    url = _serve(server)
    try:
        requests.post(
            f"{url}/",
            json={"question": "logged?"},
            headers={"Authorization": "Bearer should-not-appear"},
            timeout=10,
        )
    finally:
        server.shutdown()
        server.server_close()
    text = "".join(
        path.read_text(encoding="utf-8") for path in tmp_path.glob("*.jsonl")
    )
    assert "should-not-appear" not in text
    record = json.loads(text.splitlines()[0])
    assert set(record) >= {"timestamp", "app", "mode", "question", "status"}
    assert len(record["question"]) <= 200
