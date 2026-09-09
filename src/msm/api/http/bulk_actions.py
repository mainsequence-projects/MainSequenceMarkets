"""Provider-neutral Command Center bulk-action contracts and helpers."""

from __future__ import annotations

from typing import Annotated, Any, Literal
from uuid import UUID

from pydantic import Field, StrictFloat, StrictInt, field_validator, model_validator

from ._base import HttpContractModel

BULK_ACTION_EXECUTION_CONTRACT = "command-center.bulk_action_execution@v1"
BULK_ACTION_PREFLIGHT_CONTRACT = "command-center.bulk_action_preflight@v1"

_PRESENTATION_FILTER_KEYS = frozenset(
    {"light", "limit", "offset", "ordering", "page", "page_size", "search", "sort"}
)

BulkActionResourceId = str | StrictInt | StrictFloat


class BulkActionExplicitSelection(HttpContractModel):
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


class BulkActionAllMatchingQuery(HttpContractModel):
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


class BulkActionAllMatchingSelection(HttpContractModel):
    mode: Literal["all_matching"]
    query: BulkActionAllMatchingQuery


BulkActionSelection = Annotated[
    BulkActionExplicitSelection | BulkActionAllMatchingSelection,
    Field(discriminator="mode"),
]


class BulkActionExecutionRequest(HttpContractModel):
    selection: BulkActionSelection
    options: dict[str, Any]


class BulkActionConfirmation(HttpContractModel):
    title: str
    word: str
    button_label: str
    warning: str


class BulkActionOption(HttpContractModel):
    key: str = Field(pattern=r".*\S.*")
    type: Literal["boolean"]
    default: bool
    label: str
    description: str


class BulkActionDefinition(HttpContractModel):
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


class BulkActionPreflightResponse(HttpContractModel):
    """Extensible preflight response compatible with the Command Center contract."""

    model_config = HttpContractModel.model_config | {"extra": "allow"}

    allowed: bool
    detail: str | None = None
    matched_count: int | None = Field(default=None, ge=0)
    blockers: list[str] | None = None
    warnings: list[str] | None = None


def build_bulk_delete_action(
    *,
    action_id: str,
    label: str,
    endpoint: str,
    preflight_endpoint: str,
    confirmation_title: str,
    confirmation_warning: str,
) -> BulkActionDefinition:
    """Build the standard explicit-selection destructive action descriptor."""

    return BulkActionDefinition(
        id=action_id,
        label=label,
        endpoint=endpoint,
        preflight_endpoint=preflight_endpoint,
        method="POST",
        tone="danger",
        selection_modes=["explicit"],
        confirmation=BulkActionConfirmation(
            title=confirmation_title,
            word="DELETE",
            button_label=label,
            warning=confirmation_warning,
        ),
        options=[],
    )


def explicit_uuid_selection(request: BulkActionExecutionRequest) -> list[str]:
    """Validate and normalize an explicit UUID-only bulk selection."""

    if not isinstance(request.selection, BulkActionExplicitSelection):
        raise ValueError("This bulk action supports only explicit UID selection.")
    if request.options:
        unsupported = ", ".join(sorted(request.options))
        raise ValueError(f"This bulk action does not support options: {unsupported}.")

    normalized: list[str] = []
    for resource_id in request.selection.uids:
        try:
            normalized.append(str(UUID(str(resource_id))))
        except (TypeError, ValueError) as exc:
            raise ValueError(f"Bulk-action resource id {resource_id!r} is not a UUID.") from exc
    return normalized


def blocked_preflight_detail(preflight: BulkActionPreflightResponse) -> str:
    """Render a stable error detail from a blocked preflight response."""

    messages = list(preflight.blockers or [])
    if messages:
        return " ".join(messages)
    return preflight.detail or "The bulk action is not allowed."


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
    "blocked_preflight_detail",
    "build_bulk_delete_action",
    "explicit_uuid_selection",
]
