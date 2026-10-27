"""The built-in demo helpdesk app (spec section 10).

A tiny FastAPI service the compose file runs under the ``demo`` profile: one
instance with ``MODE=good`` and one with ``MODE=broken``, both from this same
module, so "Try the demo" can show a GO and a NO-GO with no model and no setup.

The answers come from :mod:`app.services.demo`, the same code the tests and the
dataset loader use, so what GreenLit scores is exactly what this app returns.
"""

from __future__ import annotations

import os
from typing import Any

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, ConfigDict

from app.services.demo import chat

app = FastAPI(title="GreenLit demo helpdesk", version="1.0.0")

VALID_MODES = ("good", "broken")


def mode() -> str:
    """Read MODE at request time so tests can switch it without a restart."""
    value = os.environ.get("MODE", "good").strip().lower()
    return value if value in VALID_MODES else "good"


class ChatRequest(BaseModel):
    """``POST /chat`` accepts {"question": "..."} or {"input": "..."}."""

    model_config = ConfigDict(extra="ignore")

    question: str | None = None
    input: str | None = None


@app.get("/healthz")
def healthz() -> dict[str, Any]:
    return {"status": "ok", "mode": mode()}


@app.post("/chat")
def chat_endpoint(payload: ChatRequest) -> dict[str, str]:
    question = (payload.question or payload.input or "").strip()
    if not question:
        raise HTTPException(
            status_code=400,
            detail='Send {"question": "your question"} or {"input": "your question"}.',
        )
    return chat(question, mode=mode())
