#!/usr/bin/env python
"""Diagnose why a site refuses GreenLit's request, on a target you own.

One request, sent by GreenLit's own connector: the same cURL import, the same
header cleaning, the same SSRF guard and the same redaction the product uses.
Nothing is retried, no challenge is solved and no browser is imitated — this
prints the evidence for a refusal and stops.

    python scripts/diagnose_target.py my-request.curl --question "hello"

The file is read and never echoed. A cURL aimed at anything that is not this
machine needs ``--owned-or-permitted`` and ``--reference "..."`` as well.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path
from urllib.parse import urlsplit

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from app.services.connectors import ConnectorError, HttpConnector  # noqa: E402
from app.services.target_error import redact_snippet, target_of  # noqa: E402
from app.utils.curl import clean_request_headers, parse_curl  # noqa: E402

PERMISSION_LINE = "Only test systems you own or have written permission to test."
LOCAL_HOSTS = frozenset({"localhost", "127.0.0.1", "::1", "0.0.0.0"})


def _refuse(message: str) -> int:
    """A usage or safety refusal: nothing was sent."""
    print(PERMISSION_LINE)
    print(message, file=sys.stderr)
    return 2


def _is_local(url: str) -> bool:
    """Whether the URL points at this machine, decided from the text alone."""
    host = (urlsplit(url).hostname or "").lower()
    return host in LOCAL_HOSTS or host.endswith(".localhost")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="One request, diagnosed: why did this site refuse GreenLit?",
    )
    parser.add_argument("curl_file", help="a file holding one copied cURL command")
    parser.add_argument("--question", default="hello", help="the message to send")
    parser.add_argument(
        "--owned-or-permitted",
        action="store_true",
        help="confirm the target is yours or you have written permission to test it",
    )
    parser.add_argument(
        "--reference",
        default="",
        help="where that permission comes from (a ticket, a contract, an owner)",
    )
    args = parser.parse_args(argv)

    path = Path(args.curl_file)
    try:
        text = path.read_text(encoding="utf-8")
    except OSError as exc:
        return _refuse(f"could not read {path}: {exc.strerror or exc}")

    parsed = parse_curl(text)
    if parsed is None:
        return _refuse("that file does not hold a cURL command with a URL")
    if parsed.method.upper() != "POST":
        return _refuse(f"this request uses {parsed.method.upper()}; GreenLit sends POST")

    local = _is_local(parsed.url)
    if not local and not (args.owned_or_permitted and args.reference.strip()):
        return _refuse(
            "this target is not on this machine: pass --owned-or-permitted and "
            '--reference "<where the permission comes from>" to describe your authority '
            "to test it"
        )

    connector = HttpConnector(
        allow_private=local,
        min_delay_ms=0,
        # One attempt by definition: a refusal is diagnosed, never retried.
        max_retries=0,
        item_budget_seconds=60,
    )
    print(PERMISSION_LINE)
    print(f"Target: {target_of(parsed.url)}")
    try:
        trace = connector.render_and_send(
            url=parsed.url,
            body_template=parsed.body_template or '{"question": {{input}}}',
            input_text=args.question,
            headers=clean_request_headers(parsed.headers),
            timeout_seconds=30,
            method="POST",
        )
    except ConnectorError as exc:
        details = exc.details or {}
        status = details.get("status_code")
        print(f"HTTP status: {status if status is not None else 'no answer'}")
        print(f"Class: {exc.code}")
        print(f"Message: {exc.message}")
        evidence = details.get("evidence") or []
        if evidence:
            print("Evidence:")
            for line in evidence:
                print(f"  - {line}")
        kept = details.get("headers") or {}
        if kept:
            print("Response headers:")
            for name, value in kept.items():
                print(f"  {name}: {value}")
        snippet = details.get("snippet") or ""
        if snippet:
            print(f"Body (redacted): {snippet}")
        print("Nothing was retried and no challenge was solved.")
        return 0

    print(f"HTTP status: {trace.status_code}")
    print("Class: none - the site answered with a readable reply")
    print(f"Latency: {trace.latency_ms} ms")
    answer = redact_snippet(trace.output, 300)
    if answer:
        print(f"Answer (redacted): {answer}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
