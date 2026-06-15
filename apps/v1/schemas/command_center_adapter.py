from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict

from mainsequence.client.command_center.contracts.adapter_from_api import (
    AdapterFromApiAdapterMetadata as CommandCenterAdapterInfo,
    AdapterFromApiConfigVariable as CommandCenterConfigVariable,
    AdapterFromApiConnectionContract as CommandCenterConnectionContract,
    AdapterFromApiHealth as CommandCenterHealthOperation,
    AdapterFromApiOpenApiMetadata as CommandCenterOpenApiInfo,
    AdapterFromApiOperation as CommandCenterOperation,
    AdapterFromApiOperationCache as CommandCenterOperationCache,
    AdapterFromApiParameter as CommandCenterOperationParameter,
    AdapterFromApiRequestBody as CommandCenterOperationRequestBody,
    AdapterFromApiSecretInjection as CommandCenterSecretInjection,
    AdapterFromApiSecretVariable as CommandCenterSecretVariable,
)
from mainsequence.client.command_center.contracts.response_mapping import (
    AdapterResponseMapping as CommandCenterResponseMapping,
)


class ApiHealthResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    status: Literal["ok"]
    service: str
    version: str


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
    "CommandCenterOperationRequestBody",
    "CommandCenterResponseMapping",
    "CommandCenterSecretInjection",
    "CommandCenterSecretVariable",
]
