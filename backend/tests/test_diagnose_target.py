"""The own-target diagnostic: one request, then the evidence.

Every case runs the script against a local server that refuses the way a real
site does, so what it prints can be proven without pointing it at anybody.
"""

from __future__ import annotations

import json
import subprocess
import sys
import threading
from collections.abc import Callable
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest

from tests.support.refusal_server import start_refusal

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts" / "diagnose_target.py"
SENTINEL = "sentinel-cookie-do-not-print"


def _run(*args: str) -> subprocess.CompletedProcess[str]:
    """Run the script the way a person does, and keep its exit code."""
    return subprocess.run(
        [sys.executable, str(SCRIPT), *args],
        capture_output=True,
        text=True,
        cwd=str(ROOT),
        timeout=120,
    )


@pytest.fixture
def curl_file(tmp_path: Path) -> Callable[[str], str]:
    """Write a copied-cURL file that carries a cookie nobody may see printed."""

    def write(url: str) -> str:
        path = tmp_path / "request.curl"
        path.write_text(
            "curl -X POST "
            + url
            + " -H 'Content-Type: application/json' -H 'Cookie: session="
            + SENTINEL
            + '\' -d \'{"question": "hello"}\'',
            encoding="utf-8",
        )
        return str(path)

    return write


@pytest.mark.parametrize(
    ("mode", "code", "says"),
    [
        ("nginx_forbidden", "auth_error", "refused this request"),
        ("csrf_json", "csrf_rejected", "CSRF"),
        ("cloudflare_challenge", "blocked_by_site", "Cloudflare"),
        ("rate_limited", "http_error", "rate-limiting"),
    ],
)
def test_a_refusal_is_named_with_its_evidence(
    curl_file: Callable[[str], str], mode: str, code: str, says: str
) -> None:
    server = start_refusal(mode)
    try:
        result = _run(curl_file(server.url))
    finally:
        server.close()

    assert result.returncode == 0, result.stderr
    assert f"Class: {code}" in result.stdout
    assert says in result.stdout
    assert "HTTP status:" in result.stdout
    assert "Evidence:" in result.stdout
    assert "Nothing was retried" in result.stdout
    # The pasted session was sent, and is never echoed back.
    assert SENTINEL not in result.stdout
    assert SENTINEL not in result.stderr
    # One request: this tool has no retry path at all.
    assert len(server.calls) == 1


def test_a_working_target_is_not_called_a_refusal(curl_file: Callable[[str], str]) -> None:
    class Ok(BaseHTTPRequestHandler):
        def do_POST(self) -> None:
            length = int(self.headers.get("content-length") or 0)
            if length:
                self.rfile.read(length)
            body = json.dumps({"answer": "the answer"}).encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *args: object) -> None:
            return

    httpd = ThreadingHTTPServer(("127.0.0.1", 0), Ok)
    httpd.daemon_threads = True
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    try:
        url = f"http://127.0.0.1:{httpd.server_address[1]}/chat"
        result = _run(curl_file(url))
    finally:
        httpd.shutdown()
        httpd.server_close()
        thread.join(timeout=5)

    assert result.returncode == 0, result.stderr
    assert "HTTP status: 200" in result.stdout
    assert "Class: none" in result.stdout
    assert "the answer" in result.stdout
    assert SENTINEL not in result.stdout


def test_a_remote_target_is_refused_before_any_network_call(
    curl_file: Callable[[str], str],
) -> None:
    """A host that cannot resolve must never be reached: the refusal is textual."""
    result = _run(curl_file("https://chat.example.invalid/chat"))

    assert result.returncode == 2
    assert "Only test systems you own or have written permission to test." in result.stdout
    assert "--owned-or-permitted" in result.stderr
    # Nothing was sent, and no DNS lookup happened: no class, no connection story.
    assert "Class:" not in result.stdout
    assert "could not connect" not in result.stderr
    assert SENTINEL not in result.stdout
    assert SENTINEL not in result.stderr


def test_a_file_that_is_not_a_curl_is_a_usage_error(tmp_path: Path) -> None:
    path = tmp_path / "notes.txt"
    path.write_text("just some notes", encoding="utf-8")

    result = _run(str(path))

    assert result.returncode == 2
    assert "does not hold a cURL command" in result.stderr
