"""Uniform error responses: ``{"error": {"code", "message", "fields"}}``."""

from __future__ import annotations

import logging
from typing import Any

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

logger = logging.getLogger("greenlit.errors")

_CODE_BY_STATUS: dict[int, str] = {
    400: "bad_request",
    401: "unauthorized",
    403: "forbidden",
    404: "not_found",
    405: "method_not_allowed",
    409: "conflict",
    413: "payload_too_large",
    415: "unsupported_media_type",
    422: "validation_error",
    429: "rate_limited",
    501: "not_implemented",
    503: "service_unavailable",
}


def error_response(
    status_code: int,
    message: str,
    *,
    code: str | None = None,
    fields: list[dict[str, Any]] | None = None,
) -> JSONResponse:
    """Build an error response in the single API error shape."""
    return JSONResponse(
        status_code=status_code,
        content={
            "error": {
                "code": code or _CODE_BY_STATUS.get(status_code, "error"),
                "message": message,
                "fields": fields or [],
            }
        },
    )


def install_error_handlers(app: FastAPI) -> None:
    """Register handlers so every error uses the same envelope."""

    @app.exception_handler(StarletteHTTPException)
    async def http_exception_handler(request: Request, exc: StarletteHTTPException) -> JSONResponse:
        detail = exc.detail if isinstance(exc.detail, str) else "Request failed."
        return error_response(exc.status_code, detail, fields=_http_exception_fields(exc))

    @app.exception_handler(RequestValidationError)
    async def validation_exception_handler(
        request: Request, exc: RequestValidationError
    ) -> JSONResponse:
        fields = [
            {
                "field": ".".join(str(part) for part in error.get("loc", ())[1:]) or "body",
                "message": error.get("msg", "Invalid value."),
            }
            for error in exc.errors()
        ]
        return error_response(
            422, "Some fields are invalid. Check the highlighted fields.", fields=fields
        )

    @app.exception_handler(Exception)
    async def unhandled_exception_handler(request: Request, exc: Exception) -> JSONResponse:
        logger.exception("Unhandled error on %s %s", request.method, request.url.path)
        return error_response(
            500,
            "Something went wrong on our side. "
            "Try again, and check the server logs if it persists.",
        )


def _http_exception_fields(exc: StarletteHTTPException) -> list[dict[str, Any]]:
    detail = exc.detail
    if isinstance(detail, dict):
        fields = detail.get("fields")
        if isinstance(fields, list):
            return [field for field in fields if isinstance(field, dict)]
    return []
