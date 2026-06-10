from __future__ import annotations

from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator

from apps.v1.runtime_bootstrap import prepare_apps_v1_import_namespace


def _asset_category_contract():
    prepare_apps_v1_import_namespace()
    from msm.api.assets import AssetCategory

    return AssetCategory


AssetCategory = _asset_category_contract()


class CreateAssetCategoryRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    display_name: str = Field(min_length=1, max_length=255)
    description: str | None = None
    unique_identifier: str | None = None
    assets: list[UUID] | None = None

    @field_validator("display_name")
    @classmethod
    def _validate_display_name(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("display_name must not be blank.")
        return normalized

    @field_validator("unique_identifier")
    @classmethod
    def _normalize_unique_identifier(cls, value: str | None) -> str | None:
        if value is None:
            return None
        normalized = value.strip()
        return normalized or None

    @field_validator("description")
    @classmethod
    def _normalize_description(cls, value: str | None) -> str | None:
        if value is None:
            return None
        normalized = value.strip()
        return normalized or None


class PatchAssetCategoryRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    display_name: str | None = Field(default=None, max_length=255)
    description: str | None = None
    assets: list[UUID] | None = None

    @field_validator("display_name")
    @classmethod
    def _validate_display_name(cls, value: str | None) -> str | None:
        if value is None:
            return None
        normalized = value.strip()
        if not normalized:
            raise ValueError("display_name must not be blank.")
        return normalized

    @field_validator("description")
    @classmethod
    def _normalize_description(cls, value: str | None) -> str | None:
        if value is None:
            return None
        normalized = value.strip()
        return normalized or None


class AssetCategoryDetailSelectedCategory(BaseModel):
    model_config = ConfigDict(extra="forbid")

    text: str
    sub_text: str


class AssetCategoryDetailField(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str
    label: str
    value_type: str
    value: str | int | float | bool | None


class AssetCategoryDetailActions(BaseModel):
    model_config = ConfigDict(extra="forbid")

    can_edit: bool
    can_delete: bool
    update_endpoint: str
    delete_endpoint: str


class AssetCategoryDetailAssetsList(BaseModel):
    model_config = ConfigDict(extra="forbid")

    list_endpoint: str
    query_endpoint: str
    response_format: str
    default_filters: dict[str, Any]


class AssetCategoryDetailResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    uid: UUID
    title: str
    selected_category: AssetCategoryDetailSelectedCategory
    details: list[AssetCategoryDetailField]
    actions: AssetCategoryDetailActions
    assets_list: AssetCategoryDetailAssetsList


class BulkDeleteAssetCategoriesRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    uids: list[UUID] | None = None
    select_all: bool = False
    current_url: str | None = None
    search: str | None = None
    display_name: str | None = None
    display_name_contains: str | None = Field(default=None, alias="display_name__contains")
    unique_identifier: str | None = None
    unique_identifier_contains: str | None = Field(default=None, alias="unique_identifier__contains")
    description: str | None = None
    description_contains: str | None = Field(default=None, alias="description__contains")
    organization_owner_uid: UUID | None = Field(default=None, alias="organization_owner__uid")

    @field_validator(
        "current_url",
        "search",
        "display_name",
        "display_name_contains",
        "unique_identifier",
        "unique_identifier_contains",
        "description",
        "description_contains",
    )
    @classmethod
    def _normalize_optional_strings(cls, value: str | None) -> str | None:
        if value is None:
            return None
        normalized = value.strip()
        return normalized or None


class BulkDeleteAssetCategoriesResponse(BaseModel):
    model_config = ConfigDict(extra="ignore")

    detail: str
    deleted_count: int
