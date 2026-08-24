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
    """Create one named grouping and optionally establish its initial Asset membership."""

    model_config = ConfigDict(extra="forbid")

    display_name: str = Field(
        min_length=1,
        max_length=255,
        description="Human-readable category name shown in Markets.",
    )
    description: str | None = Field(
        default=None,
        description="Optional explanation of the category's intended membership or use.",
    )
    unique_identifier: str | None = Field(
        default=None,
        description="Optional stable business identifier; the service derives one when omitted.",
    )
    assets: list[UUID] | None = Field(
        default=None,
        description="Optional complete initial set of canonical Asset uids assigned to the category.",
    )

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
    """Update category display fields or replace its complete Asset membership set."""

    model_config = ConfigDict(extra="forbid")

    display_name: str | None = Field(
        default=None,
        max_length=255,
        description="Replacement human-readable category name.",
    )
    description: str | None = Field(
        default=None,
        description="Replacement category description; null clears the existing description.",
    )
    assets: list[UUID] | None = Field(
        default=None,
        description=(
            "Replacement complete set of canonical Asset uids. Omit the field to preserve current "
            "membership; pass an empty list to remove all memberships."
        ),
    )

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
    """Display label and supporting text for the selected Asset category."""

    model_config = ConfigDict(extra="forbid")

    text: str
    sub_text: str


class AssetCategoryDetailField(BaseModel):
    """One labeled category fact rendered by the generic detail surface."""

    model_config = ConfigDict(extra="forbid")

    name: str
    label: str
    value_type: str
    value: str | int | float | bool | None


class AssetCategoryDetailActions(BaseModel):
    """Mutation capabilities and endpoints authorized for the category detail surface."""

    model_config = ConfigDict(extra="forbid")

    can_edit: bool
    can_delete: bool
    update_endpoint: str
    delete_endpoint: str


class AssetCategoryDetailAssetsList(BaseModel):
    """Nested Asset collection configuration scoped to the selected category."""

    model_config = ConfigDict(extra="forbid")

    list_endpoint: str
    query_endpoint: str
    default_filters: dict[str, Any]


class AssetCategoryDetailResponse(BaseModel):
    """Composed category detail with facts, actions, and membership-scoped Asset list."""

    model_config = ConfigDict(extra="forbid")

    uid: UUID
    title: str
    selected_category: AssetCategoryDetailSelectedCategory
    details: list[AssetCategoryDetailField]
    actions: AssetCategoryDetailActions
    assets_list: AssetCategoryDetailAssetsList


class BulkDeleteAssetCategoriesResponse(BaseModel):
    """Result of deleting an explicitly selected set of Asset categories."""

    model_config = ConfigDict(extra="ignore")

    detail: str
    deleted_count: int
