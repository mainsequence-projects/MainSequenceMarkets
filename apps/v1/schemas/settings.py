from __future__ import annotations

from pydantic import BaseModel, ConfigDict


class ApiSettingsApp(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str
    scope: str
    version: str


class ApiSettingsRuntime(BaseModel):
    model_config = ConfigDict(extra="forbid")

    namespace: str
    namespace_source: str
    default_namespace: str
    auto_register_enabled: bool
    management_mode: str
    schema_mutation_allowed: bool
    requires_migrations: bool


class ApiSettingsDocumentation(BaseModel):
    model_config = ConfigDict(extra="forbid")

    openapi_url: str
    swagger_url: str
    redoc_url: str


class ApiSettingsAssumption(BaseModel):
    model_config = ConfigDict(extra="forbid")

    key: str
    label: str
    value: str | int | float | bool | None
    source: str
    description: str


class ApiSettingsResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    app: ApiSettingsApp
    runtime: ApiSettingsRuntime
    documentation: ApiSettingsDocumentation
    assumptions: list[ApiSettingsAssumption]
