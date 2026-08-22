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
    default_filters: dict[str, Any]


class AssetCategoryDetailResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    uid: UUID
    title: str
    selected_category: AssetCategoryDetailSelectedCategory
    details: list[AssetCategoryDetailField]
    actions: AssetCategoryDetailActions
    assets_list: AssetCategoryDetailAssetsList


class BulkDeleteAssetCategoriesResponse(BaseModel):
    model_config = ConfigDict(extra="ignore")

    detail: str
    deleted_count: int
