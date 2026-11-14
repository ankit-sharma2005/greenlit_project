"""A3: the streaming app, parsed the way GreenLit's connector reads each format."""

from __future__ import annotations

import json
import threading
import time
from pathlib import Path
from typing import Any

import pytest
import requests
from common.config import load_settings
from fake_llm import FakeLLM
from stream_bot.app import create_server

QUESTION = "When do you ship?"


def start(tmp_path: Path, **fake_options: Any) -> tuple[Any, FakeLLM]:
    fake = FakeLLM(**fake_options)
    fake.__enter__()
    settings = load_settings(
        {"LLM_BASE_URL": fake.url, "LLM_MODEL": "fake-model", "APP_MODE": "guarded"}
    )
    server = create_server(settings, port=0, log_dir=tmp_path)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    return (server, thread), fake


@pytest.fixture()
def bobbin(tmp_path: Path) -> Any:
    servers, fake = start(tmp_path)
    server, thread = servers
    yield f"http://127.0.0.1:{server.server_address[1]}", fake
    server.shutdown()
    server.server_close()
    thread.join(timeout=5)
    fake.close()


def read_sse(url: str) -> tuple[str, list[str]]:
    """The connector's rule: blank line ends an event, ``[DONE]`` ends the stream."""
    pieces: list[str] = []
    markers: list[str] = []
    with requests.post(
        f"{url}/sse", json={"question": QUESTION}, stream=True, timeout=15
    ) as r:
        assert r.status_code == 200
        assert "text/event-stream" in r.headers["content-type"]
        data: list[str] = []
        for line in r.iter_lines(decode_unicode=True):
            if line == "":
                if data:
                    payload = "\n".join(data)
                    data = []
                    if payload.strip() == "[DONE]":
                        markers.append("[DONE]")
                        continue
                    value = json.loads(payload)
                    if "delta" in value:
                        pieces.append(value["delta"])
                    else:
                        markers.append(value.get("error", ""))
                continue
            if line.startswith("data:"):
                value = line[5:]
                data.append(value.removeprefix(" "))
    return "".join(pieces), markers


def read_ndjson(url: str) -> tuple[str, bool]:
    """The connector's rule: one JSON object per line, ``done`` ends it."""
    pieces: list[str] = []
    done = False
    with requests.post(
        f"{url}/ndjson", json={"question": QUESTION}, stream=True, timeout=15
    ) as r:
        assert r.status_code == 200
        assert "application/x-ndjson" in r.headers["content-type"]
        for line in r.iter_lines(decode_unicode=True):
            if not line:
                continue
            value = json.loads(line)
            if value.get("done"):
                done = True
            elif "delta" in value:
                pieces.append(value["delta"])
    return "".join(pieces), done


def test_all_four_paths_return_the_same_answer(bobbin: Any) -> None:
    url, _fake = bobbin
    plain = requests.post(f"{url}/", json={"question": QUESTION}, timeout=15).json()[
        "answer"
    ]
    sse_text, sse_markers = read_sse(url)
    ndjson_text, ndjson_done = read_ndjson(url)
    text = requests.post(f"{url}/text", json={"question": QUESTION}, timeout=15)
    assert sse_text == plain
    assert ndjson_text == plain
    assert text.text == plain
    assert text.headers["content-type"].startswith("text/plain")
    assert sse_markers == ["[DONE]"]
    assert ndjson_done


def test_a_non_streaming_provider_is_chunked_and_still_streams(tmp_path: Path) -> None:
    servers, fake = start(tmp_path, streaming=False)
    server, thread = servers
    try:
        url = f"http://127.0.0.1:{server.server_address[1]}"
        text, markers = read_sse(url)
        plain = requests.post(
            f"{url}/", json={"question": QUESTION}, timeout=15
        ).json()["answer"]
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)
        fake.close()
    assert text == plain
    assert markers == ["[DONE]"]


def test_a_failure_after_the_first_byte_ends_the_stream_with_an_error(
    tmp_path: Path,
) -> None:
    servers, fake = start(tmp_path, die_after_first=True)
    server, thread = servers
    try:
        url = f"http://127.0.0.1:{server.server_address[1]}"
        began = time.monotonic()
        _text, markers = read_sse(url)
        elapsed = time.monotonic() - began
        _done_text, done = read_ndjson(url)
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)
        fake.close()
    assert "provider_unavailable" in markers
    assert markers[-1] == "[DONE]"
    assert elapsed < 10, "the reader must not hang"
    assert done is True


def test_a_429_before_the_first_byte_is_a_clean_503(tmp_path: Path) -> None:
    servers, fake = start(tmp_path, status=429, retry_after="13")
    server, thread = servers
    try:
        url = f"http://127.0.0.1:{server.server_address[1]}"
        response = requests.post(f"{url}/sse", json={"question": QUESTION}, timeout=15)
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)
        fake.close()
    assert response.status_code == 503
    assert response.json() == {"error": "provider_unavailable"}
    assert response.headers["Retry-After"] == "13"
    assert fake.count == 1
