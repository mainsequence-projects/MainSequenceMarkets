from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field


class ApiHealthResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    status: Literal["ok"]
    service: str
    version: str


class CommandCenterAdapterInfo(BaseModel):
    model_config = ConfigDict(extra="forbid")

    type: Literal["adapter-from-api"]
    id: str
    title: str
    description: str


class CommandCenterOpenApiInfo(BaseModel):
    model_config = ConfigDict(extra="forbid")

    url: str
    version: str
    checksum: str | None = None


class CommandCenterSecretInjection(BaseModel):
    model_config = ConfigDict(extra="forbid")

    type: str
    name: str


class CommandCenterConfigVariable(BaseModel):
    model_config = ConfigDict(extra="forbid")

    key: str
    label: str
    type: Literal["string", "number", "boolean", "select", "json"]
    required: bool = False
    description: str | None = None
    default: Any = None
    choices: list[dict[str, Any]] | None = None


class CommandCenterSecretVariable(BaseModel):
    model_config = ConfigDict(extra="forbid")

    key: str
    label: str
    type: Literal["secret"]
    required: bool = True
    description: str | None = None
    injection: CommandCenterSecretInjection


class CommandCenterHealthOperation(BaseModel):
    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    operation_id: str = Field(alias="operationId")
    expected_status: int = Field(alias="expectedStatus")
    timeout_ms: int = Field(alias="timeoutMs")


class CommandCenterOperationCache(BaseModel):
    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    enabled: bool
    ttl_seconds: int | None = Field(alias="ttlSeconds")


class CommandCenterOperationParameter(BaseModel):
    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    name: str
    in_: str = Field(alias="in")
    required: bool
    type: str | None = None
    description: str | None = None
    schema_: dict[str, Any] | None = Field(default=None, alias="schema")


class CommandCenterOperationRequestBody(BaseModel):
    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    required: bool
    content_types: list[str] = Field(alias="contentTypes")
    schema_: dict[str, Any] | None = Field(default=None, alias="schema")
    schema_ref: str | None = Field(default=None, alias="schemaRef")


class CommandCenterResponseMapping(BaseModel):
    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    id: str
    label: str
    contract: str
    status_code: str = Field(alias="statusCode")
    content_type: str = Field(alias="contentType")
    rows_path: str | None = Field(default=None, alias="rowsPath")
    field_types: dict[str, str] | None = Field(default=None, alias="fieldTypes")
    time_series: dict[str, Any] | None = Field(default=None, alias="timeSeries")


class CommandCenterOperation(BaseModel):
    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    operation_id: str = Field(alias="operationId")
    label: str
    description: str
    method: str
    path: str
    kind: Literal["health", "query", "mutation"]
    capabilities: list[str]
    requires_time_range: bool = Field(alias="requiresTimeRange")
    supports_variables: bool = Field(alias="supportsVariables")
    supports_max_rows: bool = Field(alias="supportsMaxRows")
    parameters: list[CommandCenterOperationParameter] = Field(default_factory=list)
    request_body: CommandCenterOperationRequestBody | None = Field(
        default=None,
        alias="requestBody",
    )
    response_mappings: list[CommandCenterResponseMapping] = Field(
        default_factory=list,
        alias="responseMappings",
    )
    cache: CommandCenterOperationCache
    response_contract: str = Field(alias="responseContract")
    response_model: str | None = Field(default=None, alias="responseModel")


class CommandCenterConnectionContract(BaseModel):
    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    contract_version: int = Field(alias="contractVersion")
    adapter: CommandCenterAdapterInfo
    openapi: CommandCenterOpenApiInfo
    config_variables: list[CommandCenterConfigVariable] = Field(
        default_factory=list,
        alias="configVariables",
    )
    secret_variables: list[CommandCenterSecretVariable] = Field(
        default_factory=list,
        alias="secretVariables",
    )
    available_operations: list[CommandCenterOperation] = Field(
        default_factory=list,
        alias="availableOperations",
    )
    health: CommandCenterHealthOperation
