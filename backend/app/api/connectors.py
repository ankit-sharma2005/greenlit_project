"""Connector endpoints (M3)."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request

from app.deps import get_current_user
from app.schemas.connectors import (
    ConnectTestRequest,
    ConnectTestResponse,
    CurlParseRequest,
    CurlParseResponse,
)
from app.services.connectors import ConnectorError, HttpConnector
from app.utils.curl import decrypt_headers, encrypt_headers, parse_curl

router = APIRouter(prefix="/api/v1/connectors", tags=["connectors"])


@router.post("/curl/parse", response_model=CurlParseResponse)
def parse_curl_endpoint(
    payload: CurlParseRequest, user: Any = Depends(get_current_user)
) -> CurlParseResponse:
    parsed = parse_curl(payload.curl)
    if not parsed:
        raise HTTPException(
            status_code=400, detail="That does not look like a curl command with a URL."
        )
    return CurlParseResponse(
        method=parsed.method,
        url=parsed.url,
        header_names=sorted(parsed.headers),
        headers_secret=encrypt_headers(parsed.headers),
        body_template=parsed.body_template,
        header_count=parsed.header_count,
    )


@router.post("/test", response_model=ConnectTestResponse)
def test_connection(
    payload: ConnectTestRequest, request: Request, user: Any = Depends(get_current_user)
) -> ConnectTestResponse:
    if payload.connector_type == "http_endpoint":
        headers = (
            decrypt_headers(payload.headers_secret) if payload.headers_secret else payload.headers
        )
        connector = HttpConnector(
            allow_private=payload.allow_private_targets,
            max_concurrency=payload.max_concurrency,
            min_delay_ms=payload.min_delay_ms,
            max_retries=payload.max_retries,
        )
        try:
            if payload.auto_detect or not payload.body_template:
                trace, template, detected_answer, detected_context = connector.auto_detect(
                    url=str(payload.url) if payload.url else "",
                    input_text="Hello",
                    headers=headers,
                    timeout_seconds=payload.timeout_seconds,
                    method=payload.method,
                    response_format=payload.response_format,
                    stream_content_path=payload.stream_content_path,
                )
                return ConnectTestResponse(
                    success=True,
                    message="Connection test successful",
                    trace=trace.to_dict(),
                    detected_answer_path=detected_answer or payload.answer_path,
                    detected_context_path=detected_context or payload.context_path,
                    detected_request_shape=template,
                )
            trace = connector.render_and_send(
                url=str(payload.url) if payload.url else "",
                body_template=payload.body_template or '{"question": {{input}}}',
                input_text="Hello",
                headers=headers,
                timeout_seconds=payload.timeout_seconds,
                method=payload.method,
                answer_path=payload.answer_path,
                response_format=payload.response_format,
                stream_content_path=payload.stream_content_path,
            )
            return ConnectTestResponse(
                success=True,
                message="Connection test successful",
                trace=trace.to_dict(),
                detected_answer_path=payload.answer_path,
                detected_context_path=payload.context_path,
            )
        except ConnectorError as e:
            raise HTTPException(status_code=400, detail=e.message) from e
    elif payload.connector_type == "prompt_app":
        try:
            from app.services.connectors import PromptAppConnector

            p_connector = PromptAppConnector()
            trace = p_connector.render_and_send(
                prompt=payload.body_template or payload.system_prompt or "{{input}}",
                input_text="Hello",
                model=payload.model or "gpt-4o-mini",
                system_prompt=payload.system_prompt,
                temperature=payload.temperature if payload.temperature is not None else 0.2,
            )
            return ConnectTestResponse(
                success=True,
                message="Connection test successful",
                trace=trace.to_dict(),
            )
        except ConnectorError as e:
            raise HTTPException(status_code=400, detail=e.message) from e
    elif payload.connector_type == "upload_outputs":
        try:
            from app.services.connectors import UploadOutputsConnector

            up_connector = UploadOutputsConnector()
            csv_content = payload.body_template or ""
            trace = up_connector.render_and_send(
                csv_content=csv_content,
                input_text="Hello",
                overrides=payload.column_overrides,
            )
            return ConnectTestResponse(
                success=True,
                message="Connection test successful",
                trace=trace.to_dict(),
            )
        except ConnectorError as e:
            raise HTTPException(status_code=400, detail=e.message) from e
    else:
        raise HTTPException(status_code=501, detail="This connector is coming soon.")
