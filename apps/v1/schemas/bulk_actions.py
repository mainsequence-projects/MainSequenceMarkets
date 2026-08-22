"""Command Center bulk-action request and response models owned by apps/v1."""

from __future__ import annotations

from typing import Annotated, Any, Literal

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    StrictFloat,
    StrictInt,
    field_validator,
    model_validator,
)

BULK_ACTION_EXECUTION_CONTRACT = "command-center.bulk_action_execution@v1"
BULK_ACTION_PREFLIGHT_CONTRACT = "command-center.bulk_action_preflight@v1"

_PRESENTATION_FILTER_KEYS = frozenset(
    {"light", "limit", "offset", "ordering", "page", "page_size", "search", "sort"}
)


class BulkActionContractModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


BulkActionResourceId = str | StrictInt | StrictFloat


class BulkActionExplicitSelection(BulkActionContractModel):
    mode: Literal["explicit"]
    uids: list[BulkActionResourceId] = Field(min_length=1)

    @field_validator("uids")
    @classmethod
    def validate_uids(
        cls,
        value: list[BulkActionResourceId],
    ) -> list[BulkActionResourceId]:
        normalized_keys: list[tuple[str, object]] = []
        for resource_id in value:
            if isinstance(resource_id, str):
                if not resource_id.strip():
                    raise ValueError("Bulk-action resource string ids must not be blank.")
                normalized_keys.append(("string", resource_id))
            else:
                normalized_keys.append(("number", float(resource_id)))
        if len(normalized_keys) != len(set(normalized_keys)):
            raise ValueError("Bulk-action resource ids must be unique.")
        return value


class BulkActionAllMatchingQuery(BulkActionContractModel):
    filters: dict[str, Any]
    search: str | None = None

    @field_validator("filters")
    @classmethod
    def reject_presentation_filters(cls, value: dict[str, Any]) -> dict[str, Any]:
        invalid = sorted(_PRESENTATION_FILTER_KEYS.intersection(value))
        if invalid:
            joined = ", ".join(invalid)
            raise ValueError(f"Bulk-action filters contain presentation keys: {joined}.")
        return value


class BulkActionAllMatchingSelection(BulkActionContractModel):
    mode: Literal["all_matching"]
    query: BulkActionAllMatchingQuery


BulkActionSelection = Annotated[
    BulkActionExplicitSelection | BulkActionAllMatchingSelection,
    Field(discriminator="mode"),
]


class BulkActionExecutionRequest(BulkActionContractModel):
    selection: BulkActionSelection
    options: dict[str, Any]


class BulkActionConfirmation(BulkActionContractModel):
    title: str
    word: str
    button_label: str
    warning: str


class BulkActionOption(BulkActionContractModel):
    key: str = Field(pattern=r".*\S.*")
    type: Literal["boolean"]
    default: bool
    label: str
    description: str


class BulkActionDefinition(BulkActionContractModel):
    id: str = Field(pattern=r".*\S.*")
    label: str = Field(pattern=r".*\S.*")
    endpoint: str
    method: Literal["POST"]
    selection_modes: list[Literal["explicit", "all_matching"]] = Field(min_length=1)
    options: list[BulkActionOption]
    tone: Literal["default", "primary", "warning", "danger"] | None = None
    confirmation: BulkActionConfirmation | None = None
    preflight_endpoint: str | None = None

    @field_validator("endpoint", "preflight_endpoint")
    @classmethod
    def validate_safe_relative_path(cls, value: str | None) -> str | None:
        if value is None:
            return None
        if (
            not value.startswith("/")
            or value.startswith("//")
            or any(character in value for character in ("\\", "#", "?"))
            or any(character.isspace() for character in value)
        ):
            raise ValueError("Bulk-action endpoints must be safe relative paths.")
        return value

    @model_validator(mode="after")
    def validate_unique_values(self) -> BulkActionDefinition:
        if len(self.selection_modes) != len(set(self.selection_modes)):
            raise ValueError("Bulk-action selection modes must be unique.")
        option_keys = [option.key for option in self.options]
        if len(option_keys) != len(set(option_keys)):
            raise ValueError("Bulk-action option keys must be unique.")
        return self


class BulkActionPreflightResponse(BaseModel):
    model_config = ConfigDict(extra="allow")

    allowed: bool
    detail: str | None = None
    matched_count: int | None = Field(default=None, ge=0)
    blockers: list[str] | None = None
    warnings: list[str] | None = None


__all__ = [
    "BULK_ACTION_EXECUTION_CONTRACT",
    "BULK_ACTION_PREFLIGHT_CONTRACT",
    "BulkActionAllMatchingQuery",
    "BulkActionAllMatchingSelection",
    "BulkActionConfirmation",
    "BulkActionDefinition",
    "BulkActionExecutionRequest",
    "BulkActionExplicitSelection",
    "BulkActionOption",
    "BulkActionPreflightResponse",
    "BulkActionResourceId",
    "BulkActionSelection",
]
