"""The first-contact check for a remote target (STEP 2)."""

from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from app.schemas.runs import EntryPoint, ResponseFormat, RunCreateRequest


class TargetCheckRequest(BaseModel):
    """The connector settings a check sends, exactly as a run would.

    Deliberately the same names and limits as :class:`RunCreateRequest`: the
    check must exercise the settings the run will use, not a simplified copy.
    """

    model_config = ConfigDict(extra="forbid")

    # A check runs the connector the run would use. Only MCP needs the field
    # named here; an HTTP endpoint check is the default and never changes.
    entry_point: EntryPoint = "http_endpoint"
    target: str = Field(min_length=1, max_length=2000)
    # The first approved case of this dataset is the harmless question; with no
    # dataset, GreenLit sends a fixed "Hello".
    dataset_version_id: UUID | None = None

    method: str = Field(default="POST", max_length=10)
    body_template: str | None = Field(default=None, max_length=20_000)
    headers: dict[str, str] = Field(default_factory=dict)
    headers_secret: str | None = Field(default=None, max_length=20_000)
    # Names only: a pasted cURL keeps its values encrypted, but the check is
    # bound to which headers a run sends.
    header_names: list[str] | None = Field(default=None, max_length=60)
    answer_path: str | None = Field(default=None, max_length=300)
    context_path: str | None = Field(default=None, max_length=300)
    timeout_seconds: int = Field(default=60, ge=1, le=300)

    allow_private_targets: bool = False
    permission_confirmed: bool = False
    permission_reference: str | None = Field(default=None, max_length=300)
    safety_attacks_confirmed: bool = False

    max_concurrency: int = Field(default=1, ge=1, le=8)
    min_delay_ms: int = Field(default=500, ge=0, le=60_000)
    max_retries: int = Field(default=3, ge=0, le=10)
    response_format: ResponseFormat = "json"
    stream_content_path: str | None = Field(default=None, max_length=300)
    # The message the user typed, when the check is being used to build a body
    # template; GreenLit finds the first body field whose value equals this.
    sample_question: str | None = Field(default=None, max_length=2000)
    # MCP server settings: the check calls one tool once, like a run's first case.
    mcp_tool: str | None = Field(default=None, min_length=1, max_length=120)
    mcp_question_arg: str | None = Field(
        default=None, min_length=1, max_length=60, pattern=r"^[A-Za-z0-9_.-]+$"
    )
    mcp_extra_args: dict[str, Any] | None = None

    def to_run_request(self) -> RunCreateRequest:
        """The run request shape, so the check reuses the run's own snapshot rules."""
        return RunCreateRequest(
            entry_point=self.entry_point,
            target=self.target,
            test_types=["quality"],
            method=self.method,
            body_template=self.body_template,
            headers=self.headers,
            headers_secret=self.headers_secret,
            header_names=self.header_names,
            answer_path=self.answer_path,
            context_path=self.context_path,
            timeout_seconds=self.timeout_seconds,
            allow_private_targets=self.allow_private_targets,
            permission_confirmed=self.permission_confirmed,
            permission_reference=self.permission_reference,
            safety_attacks_confirmed=self.safety_attacks_confirmed,
            max_concurrency=self.max_concurrency,
            min_delay_ms=self.min_delay_ms,
            max_retries=self.max_retries,
            response_format=self.response_format,
            stream_content_path=self.stream_content_path,
            mcp_tool=self.mcp_tool,
            mcp_question_arg=self.mcp_question_arg,
            mcp_extra_args=self.mcp_extra_args,
        )


class McpToolsRequest(BaseModel):
    """Discover the tools of one MCP server, under the check's own rules.

    The URL, the encrypted headers and the permission record are the run's, so a
    discovery request is subject to exactly the same SSRF and consent checks as
    the run it is preparing.
    """

    model_config = ConfigDict(extra="forbid")

    target: str = Field(min_length=1, max_length=2000)
    headers: dict[str, str] = Field(default_factory=dict)
    headers_secret: str | None = Field(default=None, max_length=20_000)
    header_names: list[str] | None = Field(default=None, max_length=60)
    timeout_seconds: int = Field(default=60, ge=1, le=300)
    allow_private_targets: bool = False
    permission_confirmed: bool = False
    permission_reference: str | None = Field(default=None, max_length=300)
    max_retries: int = Field(default=3, ge=0, le=10)

    def to_check_request(self) -> TargetCheckRequest:
        """The same settings as a check, so one set of rules applies."""
        return TargetCheckRequest(
            entry_point="mcp_server",
            target=self.target,
            headers=self.headers,
            headers_secret=self.headers_secret,
            header_names=self.header_names,
            timeout_seconds=self.timeout_seconds,
            allow_private_targets=self.allow_private_targets,
            permission_confirmed=self.permission_confirmed,
            permission_reference=self.permission_reference,
            max_retries=self.max_retries,
        )


class McpToolOut(BaseModel):
    """One tool a server lists: a name, a bounded description and its arguments."""

    name: str
    description: str = ""
    required_arguments: list[str] = Field(default_factory=list)
    string_arguments: list[str] = Field(default_factory=list)
    argument_names: list[str] = Field(default_factory=list)
    suggested_question_arg: str | None = None


class McpToolsResponse(BaseModel):
    """The tools discovered, plus the server that listed them."""

    server: str | None = None
    tools: list[McpToolOut] = Field(default_factory=list)
    # The host and path only: a query string can hold a token.
    target: str = ""


class AnswerCandidate(BaseModel):
    """One string value found in the JSON response that a person may inspect."""

    path: str
    preview: str


class TargetCheckResponse(BaseModel):
    """What one harmless request found, and whether a person accepted it."""

    check_id: str
    expires_at: datetime
    accepted: bool
    # The request as it was sent: query values and header values are XXXX.
    request: dict[str, Any]
    status: int | None = None
    latency_ms: int | None = None
    # The answer read through the run's current mapping, capped at 500 chars.
    answer: str = ""
    answer_truncated: bool = False
    # Only a readable, non-HTML answer may be accepted by a person.
    extraction_ok: bool = False
    mapping_path: str | None = None
    # Plain words when the extraction is empty or looks like a web page.
    hint: str | None = None
    # The structured failure (kind, status, target, redacted snippet), if any.
    error: dict[str, Any] | None = None
    # A shortlist of string values found in the JSON response, for picking the
    # answer field. Empty when the response is not JSON or holds no strings.
    answer_candidates: list[AnswerCandidate] = Field(default_factory=list)
    # When ``sample_question`` was given, the path of the body field that equals
    # it, so the UI can build a body template with a question placeholder. Set
    # only when there is exactly one such field.
    question_path: str | None = None
    question_path_reason: str | None = None
