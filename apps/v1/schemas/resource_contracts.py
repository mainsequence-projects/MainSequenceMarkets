"""Command Center resource collection and discovery HTTP contracts."""

from __future__ import annotations

from collections.abc import Sequence
from typing import Annotated, Any, Generic, Literal, TypeVar

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from apps.v1.schemas.bulk_actions import BulkActionDefinition

RESOURCE_COLLECTION_CONTRACT = "command-center.resource_collection@v1"
RESOURCE_DISCOVERY_CONTRACT = "command-center.resource_discovery@v1"

ResourceT = TypeVar("ResourceT")
FilterValue = str | int | float | bool


class ResourceContractModel(BaseModel):
    model_config = ConfigDict(extra="forbid", populate_by_name=True)


class ResourcePageInfo(ResourceContractModel):
    page_index: int = Field(alias="pageIndex", ge=0)
    page_size: int = Field(alias="pageSize", ge=1)
    total_items: int = Field(alias="totalItems", ge=0)
    has_next_page: bool = Field(alias="hasNextPage")
    has_previous_page: bool = Field(alias="hasPreviousPage")


class ResourceCollection(ResourceContractModel, Generic[ResourceT]):
    items: list[ResourceT]
    page_info: ResourcePageInfo = Field(alias="pageInfo")
    controls: ResourceListControls | None = Field(
        default=None,
        exclude_if=lambda value: value is None,
    )
    bulk_actions: list[BulkActionDefinition] | None = Field(
        default=None,
        alias="bulkActions",
        exclude_if=lambda value: value is None,
    )


def build_resource_collection(
    *,
    items: Sequence[ResourceT],
    limit: int,
    offset: int,
    total_items: int,
) -> ResourceCollection[ResourceT]:
    """Build one exact page from an already paginated result set."""

    if limit < 1:
        raise ValueError("limit must be greater than or equal to 1.")
    if offset < 0:
        raise ValueError("offset must be greater than or equal to 0.")
    if offset % limit:
        raise ValueError("offset must be aligned to the requested page size.")
    if total_items < 0:
        raise ValueError("total_items must be greater than or equal to 0.")

    page_items = list(items)
    if len(page_items) > limit:
        raise ValueError("items must contain at most one requested page.")
    return ResourceCollection[ResourceT](
        items=page_items,
        pageInfo=ResourcePageInfo(
            pageIndex=offset // limit,
            pageSize=limit,
            totalItems=total_items,
            hasNextPage=offset + len(page_items) < total_items,
            hasPreviousPage=offset > 0,
        ),
    )


class ResourceSearchControl(ResourceContractModel):
    placeholder: str = Field(pattern=r".*\S.*")
    fields: list[str] = Field(min_length=1)

    @field_validator("fields")
    @classmethod
    def validate_unique_fields(cls, value: list[str]) -> list[str]:
        if len(value) != len(set(value)):
            raise ValueError("Resource discovery search fields must be unique.")
        return value


class ResourceFilterOption(ResourceContractModel):
    value: FilterValue
    label: str = Field(pattern=r".*\S.*")


class ResourceTextFilter(ResourceContractModel):
    key: str = Field(pattern=r".*\S.*")
    label: str = Field(pattern=r".*\S.*")
    type: Literal["text"] = "text"


class ResourceBooleanFilter(ResourceContractModel):
    key: str = Field(pattern=r".*\S.*")
    label: str = Field(pattern=r".*\S.*")
    type: Literal["boolean"] = "boolean"


class ResourceSelectFilter(ResourceContractModel):
    key: str = Field(pattern=r".*\S.*")
    label: str = Field(pattern=r".*\S.*")
    type: Literal["select"] = "select"
    options: list[ResourceFilterOption] = Field(min_length=1)

    @model_validator(mode="after")
    def validate_unique_options(self) -> ResourceSelectFilter:
        values = [(type(option.value).__name__, option.value) for option in self.options]
        if len(values) != len(set(values)):
            raise ValueError("Resource discovery select option values must be unique.")
        return self


ResourceFilter = Annotated[
    ResourceTextFilter | ResourceBooleanFilter | ResourceSelectFilter,
    Field(discriminator="type"),
]


class ResourceListControls(ResourceContractModel):
    search: ResourceSearchControl | None
    filters: list[ResourceFilter]
    ordering: list[str]

    @model_validator(mode="after")
    def validate_unique_controls(self) -> ResourceListControls:
        filter_keys = [item.key for item in self.filters]
        if len(filter_keys) != len(set(filter_keys)):
            raise ValueError("Resource discovery filter keys must be unique.")
        if len(self.ordering) != len(set(self.ordering)):
            raise ValueError("Resource discovery ordering values must be unique.")
        return self


class ResourceIdentity(ResourceContractModel):
    fields: list[str] = Field(min_length=1)

    @field_validator("fields")
    @classmethod
    def validate_identity_paths(cls, value: list[str]) -> list[str]:
        _validate_unique_safe_paths(value, label="identity fields")
        return value


class ResourceDescriptor(ResourceContractModel):
    id: str = Field(pattern=r"^[a-z][a-z0-9-]*$")
    label: str = Field(pattern=r".*\S.*")
    item_label: str = Field(pattern=r".*\S.*")
    identity: ResourceIdentity
    extensions: dict[str, Any] | None = Field(
        default=None,
        exclude_if=lambda value: value is None,
    )


class ResourceColumn(ResourceContractModel):
    id: str = Field(pattern=r"^[a-z][a-z0-9-]*$")
    header: str = Field(pattern=r".*\S.*")
    value_path: str | None = Field(default=None, exclude_if=lambda value: value is None)
    data_type: (
        Literal["text", "number", "boolean", "date", "datetime", "badge", "list", "json"] | None
    ) = Field(default=None, exclude_if=lambda value: value is None)
    default_visible: bool = True
    hideable: bool = True
    sortable_key: str | None = Field(default=None, exclude_if=lambda value: value is None)
    filter_key: str | None = Field(default=None, exclude_if=lambda value: value is None)
    importance: Literal["primary", "secondary", "tertiary"] | None = Field(
        default=None,
        exclude_if=lambda value: value is None,
    )
    align: Literal["start", "center", "end"] | None = Field(
        default=None,
        exclude_if=lambda value: value is None,
    )
    extensions: dict[str, Any] | None = Field(
        default=None,
        exclude_if=lambda value: value is None,
    )

    @field_validator("value_path")
    @classmethod
    def validate_value_path(cls, value: str | None) -> str | None:
        if value is not None:
            _validate_unique_safe_paths([value], label="column value paths")
        return value

    @model_validator(mode="after")
    def validate_generic_column_pair(self) -> ResourceColumn:
        if (self.value_path is None) != (self.data_type is None):
            raise ValueError("value_path and data_type must be provided together.")
        return self


class ResourceListDiscovery(ResourceContractModel):
    controls: ResourceListControls
    columns: list[ResourceColumn] = Field(min_length=1)

    @model_validator(mode="after")
    def validate_column_references(self) -> ResourceListDiscovery:
        column_ids = [column.id for column in self.columns]
        if len(column_ids) != len(set(column_ids)):
            raise ValueError("Resource discovery column ids must be unique.")
        ordering = set(self.controls.ordering)
        filter_keys = {item.key for item in self.controls.filters}
        for column in self.columns:
            if column.sortable_key is not None and column.sortable_key not in ordering:
                raise ValueError(
                    f"Column {column.id!r} references undeclared ordering key "
                    f"{column.sortable_key!r}."
                )
            if column.filter_key is not None and column.filter_key not in filter_keys:
                raise ValueError(
                    f"Column {column.id!r} references undeclared filter key {column.filter_key!r}."
                )
        return self


class ResourceDiscovery(ResourceContractModel):
    contract: Literal["command-center.resource_discovery@v1"] = RESOURCE_DISCOVERY_CONTRACT
    resource: ResourceDescriptor
    list: ResourceListDiscovery
    bulk_actions: list[BulkActionDefinition]
    extensions: dict[str, Any] | None = Field(
        default=None,
        exclude_if=lambda value: value is None,
    )

    @model_validator(mode="after")
    def validate_unique_action_ids(self) -> ResourceDiscovery:
        action_ids = [action.id for action in self.bulk_actions]
        if len(action_ids) != len(set(action_ids)):
            raise ValueError("Resource discovery bulk-action ids must be unique.")
        return self


def _validate_unique_safe_paths(paths: Sequence[str], *, label: str) -> None:
    if len(paths) != len(set(paths)):
        raise ValueError(f"Resource discovery {label} must be unique.")
    blocked = {"__proto__", "prototype", "constructor"}
    for path in paths:
        segments = path.split(".")
        if not segments or any(segment in blocked for segment in segments):
            raise ValueError(f"Unsafe resource discovery path {path!r}.")
        for segment in segments:
            if not segment or not (segment[0].isalpha() or segment[0] == "_"):
                raise ValueError(f"Invalid resource discovery path {path!r}.")
            if not all(character.isalnum() or character == "_" for character in segment):
                raise ValueError(f"Invalid resource discovery path {path!r}.")


ResourceCollection.model_rebuild()


__all__ = [
    "RESOURCE_COLLECTION_CONTRACT",
    "RESOURCE_DISCOVERY_CONTRACT",
    "ResourceBooleanFilter",
    "ResourceCollection",
    "ResourceColumn",
    "ResourceDescriptor",
    "ResourceDiscovery",
    "ResourceFilter",
    "ResourceFilterOption",
    "ResourceIdentity",
    "ResourceListControls",
    "ResourceListDiscovery",
    "ResourcePageInfo",
    "ResourceSearchControl",
    "ResourceSelectFilter",
    "ResourceTextFilter",
    "build_resource_collection",
]
