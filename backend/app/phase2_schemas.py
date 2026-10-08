from __future__ import annotations

from typing import Annotated, Literal
from uuid import UUID

from pydantic import (
    AnyHttpUrl,
    BaseModel,
    ConfigDict,
    Field,
    SecretStr,
    ValidationInfo,
    field_validator,
)


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class ProviderCreate(StrictModel):
    name: str = Field(min_length=1, max_length=120)
    provider_type: Literal["github_models", "ollama", "custom"]
    base_url: AnyHttpUrl | None = None
    api_key: SecretStr | None = None
    rpm: int = Field(default=10, ge=1, le=600)
    rpd: int = Field(default=500, ge=1, le=100_000)
    max_input_tokens: int = Field(default=8192, ge=1, le=1_000_000)
    max_output_tokens: int = Field(default=2048, ge=1, le=100_000)
    fallback_provider_ids: list[UUID] = Field(default_factory=list)


class ProviderOut(BaseModel):
    id: UUID
    name: str
    provider_type: str
    base_url: str
    rpm: int
    rpd: int
    max_input_tokens: int
    max_output_tokens: int
    fallback_provider_ids: list[str]
    has_api_key: bool


class ProjectCreate(StrictModel):
    name: str = Field(min_length=1, max_length=120)
    description: str = Field(default="", max_length=1000)


class ProjectOut(BaseModel):
    id: UUID
    name: str
    description: str
    created_at: str


class HttpEndpointSettings(StrictModel):
    entry_point_type: Literal["HTTP_ENDPOINT"]
    url: AnyHttpUrl
    method: Literal["GET", "POST"] = "POST"
    request_body_template: str = Field(
        default='{"input": {{input}}}', max_length=20_000
    )
    input_field: str = Field(default="input", min_length=1, max_length=100)
    output_field: str = Field(default="output", min_length=1, max_length=100)
    timeout_seconds: int = Field(default=15, ge=1, le=60)
    allow_private_targets: bool = False


class PythonFunctionSettings(StrictModel):
    entry_point_type: Literal["PYTHON_FUNCTION"]
    module: str = Field(min_length=1, max_length=255)
    function: str = Field(min_length=1, max_length=255)
    working_directory: str = Field(default="", max_length=500)
    timeout_seconds: int = Field(default=5, ge=1, le=30)


class PythonSdkTracedSettings(StrictModel):
    entry_point_type: Literal["PYTHON_SDK_TRACED"]
    module: str = Field(min_length=1, max_length=255)
    function: str = Field(min_length=1, max_length=255)
    working_directory: str = Field(default="", max_length=500)
    timeout_seconds: int = Field(default=5, ge=1, le=30)


class PromptAppSettings(StrictModel):
    entry_point_type: Literal["PROMPT_APP"]
    provider_id: UUID
    model: str = Field(min_length=1, max_length=200)
    system_prompt: str = Field(min_length=1, max_length=20_000)
    temperature: float = Field(default=0.0, ge=0, le=2)
    output_json_schema: dict[str, object] | None = None


class RagDocument(StrictModel):
    title: str = Field(min_length=1, max_length=200)
    text: str = Field(min_length=1, max_length=100_000)


class BuiltinRagSettings(StrictModel):
    entry_point_type: Literal["BUILTIN_RAG_APP"]
    provider_id: UUID
    model: str = Field(min_length=1, max_length=200)
    documents: list[RagDocument] = Field(min_length=1, max_length=100)
    chunk_size: int = Field(default=800, ge=100, le=10_000)
    chunk_overlap: int = Field(default=100, ge=0, le=9_999)
    top_k: int = Field(default=3, ge=1, le=10)
    prompt: str = Field(
        default="Answer the question using only the provided context.",
        min_length=1,
        max_length=20_000,
    )
    temperature: float = Field(default=0.0, ge=0, le=2)

    @field_validator("chunk_overlap")
    @classmethod
    def overlap_must_be_smaller_than_chunk(
        cls, value: int, info: ValidationInfo
    ) -> int:
        chunk_size = info.data.get("chunk_size", 800)
        if value >= chunk_size:
            raise ValueError("chunk_overlap must be smaller than chunk_size")
        return value


class AgentTool(StrictModel):
    name: str = Field(min_length=1, max_length=100)
    description: str = Field(min_length=1, max_length=1000)
    parameters: dict[str, object] = Field(default_factory=dict)
    mock_result: dict[str, object] = Field(default_factory=dict)


class BuiltinAgentSettings(StrictModel):
    entry_point_type: Literal["BUILTIN_AGENT_APP"]
    provider_id: UUID
    model: str = Field(min_length=1, max_length=200)
    tools: list[AgentTool] = Field(default_factory=list, max_length=20)
    max_steps: int = Field(default=5, ge=1, le=20)
    system_prompt: str = Field(
        default="You are a helpful assistant.", min_length=1, max_length=20_000
    )
    temperature: float = Field(default=0.0, ge=0, le=2)


class UploadOutputsSettings(StrictModel):
    entry_point_type: Literal["UPLOAD_OUTPUTS"]
    input_field: str = Field(default="input", min_length=1, max_length=100)
    output_field: str = Field(default="output", min_length=1, max_length=100)
    retrieved_contexts_field: str | None = Field(default=None, max_length=100)
    tool_calls_field: str | None = Field(default=None, max_length=100)


ConnectorSettings = Annotated[
    HttpEndpointSettings
    | PythonFunctionSettings
    | PythonSdkTracedSettings
    | PromptAppSettings
    | BuiltinRagSettings
    | BuiltinAgentSettings
    | UploadOutputsSettings,
    Field(discriminator="entry_point_type"),
]

CONNECTOR_SETTINGS_MODELS: dict[str, type[BaseModel]] = {
    "HTTP_ENDPOINT": HttpEndpointSettings,
    "PYTHON_FUNCTION": PythonFunctionSettings,
    "PYTHON_SDK_TRACED": PythonSdkTracedSettings,
    "PROMPT_APP": PromptAppSettings,
    "BUILTIN_RAG_APP": BuiltinRagSettings,
    "BUILTIN_AGENT_APP": BuiltinAgentSettings,
    "UPLOAD_OUTPUTS": UploadOutputsSettings,
}


class ConnectorTestCallRequest(StrictModel):
    entry_point_type: str
    settings: dict[str, object]
    credentials: dict[str, SecretStr] = Field(default_factory=dict)
    input: str = Field(min_length=1, max_length=20_000)


class ConnectorSaveRequest(StrictModel):
    entry_point_type: str
    settings: dict[str, object]
    credentials: dict[str, SecretStr] = Field(default_factory=dict)
    test_call_id: UUID


class ConnectorOut(BaseModel):
    id: UUID
    entry_point_type: str
    settings: dict[str, object]
    content_hash: str
    access_level: str
    app_version: int
    created_at: str
    has_credentials: bool


class JudgeProfileUpsert(StrictModel):
    role: Literal["dev", "final", "secondary"]
    provider_id: UUID
    model: str = Field(min_length=1, max_length=200)
    temperature: float = Field(default=0.0, ge=0, le=2)
    rubric_prompt: str = Field(default="", max_length=10_000)


class JudgeProfileOut(BaseModel):
    id: UUID
    role: str
    provider_id: UUID
    model: str
    temperature: float
    rubric_prompt: str
    rubric_version: int
