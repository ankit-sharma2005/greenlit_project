from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def test_seed_demo_generates_required_states(tmp_path: Path) -> None:
    output = tmp_path / "seed.json"
    result = subprocess.run(
        [sys.executable, str(ROOT / "scripts" / "seed_demo.py"), "--output", str(output)],
        capture_output=True,
        text=True,
        cwd=str(ROOT),
        check=True,
    )
    assert "GOOD" in result.stdout
    payload = json.loads(output.read_text(encoding="utf-8"))
    states = payload["seeded_states"]
    assert set(states) == {"GOOD", "BROKEN", "REGRESSING"}
    assert states["GOOD"]["outcome"] == "GO"
    assert states["BROKEN"]["outcome"] == "NO_GO"
    assert states["REGRESSING"]["outcome"] == "BLOCK"


def test_exports_and_research_scripts_create_artifacts(tmp_path: Path) -> None:
    export_dir = tmp_path / "reports"
    result = subprocess.run(
        [
            sys.executable,
            str(ROOT / "scripts" / "export_reports.py"),
            "--format",
            "all",
            "--output-dir",
            str(export_dir),
        ],
        capture_output=True,
        text=True,
        cwd=str(ROOT),
        check=True,
    )
    assert "wrote 3 export files" in result.stdout
    assert (export_dir / "demo-report.md").exists()
    assert (export_dir / "demo-report.csv").exists()
    assert (export_dir / "demo-report.pdf").exists()

    research_file = tmp_path / "research.json"
    research = subprocess.run(
        [
            sys.executable,
            str(ROOT / "scripts" / "research_analysis.py"),
            "--output",
            str(research_file),
        ],
        capture_output=True,
        text=True,
        cwd=str(ROOT),
        check=True,
    )
    assert "cohens_kappa" in research.stdout
    payload = json.loads(research_file.read_text(encoding="utf-8"))
    assert "score_ci" in payload
