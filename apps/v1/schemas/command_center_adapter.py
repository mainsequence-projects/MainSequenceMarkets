"""Pydantic implementation of the Command Center Adapter From API v1 contract."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class CommandCenterContractModel(BaseModel):
    model_config = ConfigDict(extra="forbid", populate_by_name=True)


class ApiHealthResponse(CommandCenterContractModel):
    status: Literal["ok"]
    service: str
    version: str


class CommandCenterAdapterInfo(CommandCenterContractModel):
    type: Literal["adapter-from-api"] = "adapter-from-api"
    id: str
    title: str
    description: str


class CommandCenterOpenApiInfo(CommandCenterContractModel):
    url: str
    version: str | None = None
    checksum: str | None = None

    @field_validator("url")
    @classmethod
    def validate_url(cls, value: str) -> str:
        if not value.startswith(("/", "http://", "https://")):
            raise ValueError("OpenAPI URL must be absolute HTTP(S) or root-relative.")
        return value


class CommandCenterFieldOption(CommandCenterContractModel):
    label: str
    value: str


class CommandCenterFieldValidation(CommandCenterContractModel):
    pattern: str | None = None
    min: float | None = None
    max: float | None = None
    minLength: int | None = Field(default=None, ge=0)
    maxLength: int | None = Field(default=None, ge=0)


class CommandCenterConfigVariable(CommandCenterContractModel):
    key: str
    label: str
    type: Literal["string", "number", "boolean", "select", "json"]
    description: str | None = None
    required: bool | None = None
    defaultValue: Any | None = None
    example: Any | None = None
    renderAs: str | None = None
    options: list[CommandCenterFieldOption] | None = None
    validation: CommandCenterFieldValidation | None = None
    name: str | None = None


class CommandCenterSecretInjection(CommandCenterContractModel):
    type: Literal["header", "query", "basic", "bearer"]
    name: str | None = None
    template: str | None = None


class CommandCenterSecretVariable(CommandCenterContractModel):
    key: str
    label: str
    type: Literal["secret"] = "secret"
    injection: CommandCenterSecretInjection
    description: str | None = None
    required: bool | None = None
    defaultValue: Any | None = None
    example: Any | None = None
    renderAs: str | None = None
    options: list[CommandCenterFieldOption] | None = None
    validation: CommandCenterFieldValidation | None = None


class CommandCenterOperationParameter(CommandCenterContractModel):
    key: str
    label: str
    type: Literal["string", "number", "boolean", "select", "json"]
    name: str | None = None
    description: str | None = None
    required: bool | None = None
    defaultValue: Any | None = None
    example: Any | None = None
    renderAs: str | None = None
    options: list[CommandCenterFieldOption] | None = None
    validation: CommandCenterFieldValidation | None = None


class CommandCenterOperationParameters(CommandCenterContractModel):
    path: list[CommandCenterOperationParameter] = Field(default_factory=list)
    query: list[CommandCenterOperationParameter] = Field(default_factory=list)
    headers: list[CommandCenterOperationParameter] = Field(default_factory=list)


class CommandCenterOperationRequestBody(CommandCenterContractModel):
    required: bool | None = None
    contentType: str | None = None
    schema_: Any | None = Field(default=None, alias="schema")
    description: str | None = None


class CommandCenterOperationCache(CommandCenterContractModel):
    policy: Literal["safe", "disabled"] | None = None
    ttlMs: int | None = Field(default=None, ge=0)
    dedupeInFlight: bool | None = None


class CommandCenterOperation(CommandCenterContractModel):
    operationId: str
    method: Literal["GET", "POST", "PUT", "PATCH", "DELETE"]
    path: str
    kind: Literal["query", "resource", "mutation"]
    capabilities: list[Literal["query", "resource", "mutation"]]
    label: str | None = None
    description: str | None = None
    requiresTimeRange: bool | None = None
    supportsVariables: bool | None = None
    supportsMaxRows: bool | None = None
    parameters: CommandCenterOperationParameters | None = None
    requestBody: CommandCenterOperationRequestBody | None = None
    responseContract: str | None = None
    responseModel: str | None = None
    cache: CommandCenterOperationCache | None = None

    @model_validator(mode="after")
    def validate_query_contract(self) -> CommandCenterOperation:
        if "query" in self.capabilities and not self.responseContract:
            raise ValueError("Query operations must declare responseContract.")
        if len(self.capabilities) != len(set(self.capabilities)):
            raise ValueError("Operation capabilities must be unique.")
        if not self.path.startswith("/"):
            raise ValueError("Operation paths must be root-relative.")
        return self


class CommandCenterHealthOperation(CommandCenterContractModel):
    operationId: str
    expectedStatus: int | None = Field(default=None, ge=100, le=599)
    timeoutMs: int | None = Field(default=None, ge=1)


class CommandCenterConnectionContract(CommandCenterContractModel):
    contractVersion: Literal[1] = 1
    adapter: CommandCenterAdapterInfo
    openapi: CommandCenterOpenApiInfo
    configVariables: list[CommandCenterConfigVariable]
    secretVariables: list[CommandCenterSecretVariable]
    availableOperations: list[CommandCenterOperation] = Field(min_length=1)
    health: CommandCenterHealthOperation
    apiBaseUrl: str | None = None
    checksum: str | None = None

    @model_validator(mode="after")
    def validate_semantics(self) -> CommandCenterConnectionContract:
        operation_ids = [operation.operationId for operation in self.availableOperations]
        if len(operation_ids) != len(set(operation_ids)):
            raise ValueError("availableOperations operationId values must be unique.")
        matches = [
            operation
            for operation in self.availableOperations
            if operation.operationId == self.health.operationId
        ]
        if len(matches) != 1 or matches[0].method != "GET":
            raise ValueError("health.operationId must reference one safe GET operation.")
        public_keys = {variable.key for variable in self.configVariables}
        secret_keys = {variable.key for variable in self.secretVariables}
        if public_keys & secret_keys:
            raise ValueError("Public and secret configuration keys must not overlap.")
        return self


__all__ = [
    "ApiHealthResponse",
    "CommandCenterAdapterInfo",
    "CommandCenterConfigVariable",
    "CommandCenterConnectionContract",
    "CommandCenterHealthOperation",
    "CommandCenterOpenApiInfo",
    "CommandCenterOperation",
    "CommandCenterOperationCache",
    "CommandCenterOperationParameter",
    "CommandCenterOperationParameters",
    "CommandCenterOperationRequestBody",
    "CommandCenterSecretInjection",
    "CommandCenterSecretVariable",
]
