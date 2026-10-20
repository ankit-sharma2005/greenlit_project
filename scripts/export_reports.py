from __future__ import annotations

import argparse
import csv
import sys
from pathlib import Path
from typing import Any

if __package__ in {None, ""}:
    root = Path(__file__).resolve().parent.parent
    if str(root) not in sys.path:
        sys.path.insert(0, str(root))

from scripts.seed_demo import build_demo_states


def write_markdown(path: Path, states: dict[str, dict[str, Any]]) -> None:
    lines = [
        "# GreenLit Phase 9 demo report",
        "",
        "| State | Outcome | Score | Summary |",
        "| --- | --- | ---: | --- |",
    ]
    for key, state in states.items():
        lines.append(
            f"| {key} | {state['outcome']} | {state['score']:.2f} | "
            f"{state['summary']} |"
        )
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def write_csv(path: Path, states: dict[str, dict[str, Any]]) -> None:
    with path.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.writer(fh)
        writer.writerow(["state", "outcome", "score", "summary"])
        for key, state in states.items():
            writer.writerow([key, state["outcome"], state["score"], state["summary"]])


def write_pdf(path: Path, states: dict[str, dict[str, Any]]) -> None:
    lines = ["GreenLit Phase 9 demo report"]
    for key, state in states.items():
        lines.append(
            f"{key}: {state['outcome']} ({state['score']:.2f}) - "
            f"{state['summary']}"
        )
    text = "\n".join(lines)
    pdf = (
        "%PDF-1.4\n"
        "1 0 obj\n<< /Type /Catalog /Pages 2 0 R >>\nendobj\n"
        "2 0 obj\n<< /Type /Pages /Kids [3 0 R] /Count 1 >>\nendobj\n"
        "3 0 obj\n<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] "
        "/Contents 4 0 R /Resources << /Font << /F1 5 0 R >> >> >>\nendobj\n"
        "4 0 obj\n<< /Length 170 >>\nstream\nBT\n/F1 12 Tf\n72 760 Td\n("
        + text.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")
        + ") Tj\nET\nendstream\nendobj\n"
        "5 0 obj\n<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>\nendobj\n"
        "xref\n0 6\n0000000000 65535 f \n0000000010 00000 n \n0000000062 00000 n \n"
        "0000000123 00000 n \n0000000245 00000 n \n0000000682 00000 n \n"
        "trailer\n<< /Root 1 0 R /Size 6 >>\nstartxref\n760\n%%EOF\n"
    )
    path.write_bytes(pdf.encode("latin-1", errors="replace"))


def main() -> int:
    parser = argparse.ArgumentParser(description="Export demo reports.")
    parser.add_argument(
        "--format",
        choices=["markdown", "csv", "pdf", "all"],
        default="all",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=Path(".tmp/reports"),
        help="Directory for exports.",
    )
    args = parser.parse_args()

    states = build_demo_states()
    args.output_dir.mkdir(parents=True, exist_ok=True)

    formats = [args.format] if args.format != "all" else ["markdown", "csv", "pdf"]
    for fmt in formats:
        if fmt == "markdown":
            write_markdown(args.output_dir / "demo-report.md", states)
        elif fmt == "csv":
            write_csv(args.output_dir / "demo-report.csv", states)
        elif fmt == "pdf":
            write_pdf(args.output_dir / "demo-report.pdf", states)

    print(f"wrote {len(formats)} export files to {args.output_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
