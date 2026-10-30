"""Exercise the CI runner against a live disposable API and demo app."""

from __future__ import annotations

import json
import os
import subprocess
import sys
import urllib.request
import uuid
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
API_URL = os.environ.get("GREENLIT_CI_E2E_API_URL")
DEMO_TARGET = os.environ.get("GREENLIT_CI_E2E_TARGET")

pytestmark = pytest.mark.skipif(
    not API_URL or not DEMO_TARGET,
    reason="requires scripts/run-e2e.sh disposable API and demo app",
)


def test_greenlit_ci_runner_against_demo_stack() -> None:
    assert API_URL is not None
    assert DEMO_TARGET is not None
    email = f"greenlit-ci-{uuid.uuid4().hex}@example.com"
    password = f"e2e-{uuid.uuid4().hex}-safe-password"
    registration = urllib.request.Request(
        f"{API_URL.rstrip('/')}/api/v1/auth/register",
        data=json.dumps({"name": "GreenLit CI E2E", "email": email, "password": password}).encode(
            "utf-8"
        ),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(registration, timeout=10) as response:
        assert response.status == 201

    environment = {
        **os.environ,
        "GREENLIT_API_URL": API_URL,
        "GREENLIT_EMAIL": email,
        "GREENLIT_PASSWORD": password,
    }
    result = subprocess.run(
        [
            sys.executable,
            str(REPO_ROOT / "scripts" / "greenlit_ci.py"),
            "--entry-point",
            "http_endpoint",
            "--target",
            DEMO_TARGET,
            "--csv-file",
            str(REPO_ROOT / "demo" / "helpdesk_golden.csv"),
            "--tests",
            "quality",
            "--timeout",
            "180",
            "--allow-private-targets",
        ],
        cwd=REPO_ROOT,
        capture_output=True,
        check=False,
        env=environment,
        text=True,
        timeout=200,
    )

    assert result.returncode == 0, f"{result.stdout}\n{result.stderr}"
    assert "Verdict: GO" in result.stdout
    assert "Weighted score: 1.00" in result.stdout
    assert "Failed metrics: none" in result.stdout
