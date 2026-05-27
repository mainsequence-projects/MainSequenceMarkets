from __future__ import annotations

import uuid
from typing import Any, ClassVar

from pydantic import AliasChoices, BaseModel, ConfigDict, Field

from msm.api.base import MarketsRow, operation_result_rows
from msm.models import (
    AssetCategoryMembershipTable,
    AssetCategoryTable,
    AssetTypeTable,
    AssetTable,
    OpenFigiDetailsTable,
)

_operation_result_rows = operation_result_rows


class Asset(MarketsRow):
    """User-facing asset row returned by typed markets API helpers."""

    __table__: ClassVar[type[AssetTable]] = AssetTable
    __required_tables__: ClassVar[list[type[AssetTable]]] = [AssetTable]
    __upsert_keys__: ClassVar[tuple[str, ...]] = ("unique_identifier",)

    unique_identifier: str
    asset_type: str | None = None


class AssetCreate(BaseModel):
    """Payload for creating an asset row."""

    model_config = ConfigDict(extra="forbid")

    unique_identifier: str = Field(min_length=1, max_length=255)
    asset_type: str | None = Field(default=None, max_length=64)


class AssetUpsert(AssetCreate):
    """Payload for inserting or updating an asset row by unique identifier."""


class AssetUpdate(BaseModel):
    """Payload for updating mutable asset fields."""

    model_config = ConfigDict(extra="forbid")

    asset_type: str | None = Field(default=None, max_length=64)


class AssetType(MarketsRow):
    """Typed row for the asset type registry."""

    __table__: ClassVar[type[AssetTypeTable]] = AssetTypeTable
    __required_tables__: ClassVar[list[type[AssetTypeTable]]] = [AssetTypeTable]
    __upsert_keys__: ClassVar[tuple[str, ...]] = ("asset_type",)

    asset_type: str
    display_name: str | None = None
    description: str | None = None
    metadata_json: dict[str, Any] | None = None


class AssetTypeCreate(BaseModel):
    """Payload for creating an asset type registry row."""

    model_config = ConfigDict(extra="forbid")

    asset_type: str = Field(min_length=1, max_length=64)
    display_name: str | None = Field(default=None, max_length=255)
    description: str | None = None
    metadata_json: dict[str, Any] | None = None


class AssetTypeUpsert(AssetTypeCreate):
    """Payload for inserting or updating an asset type by registry key."""


class AssetTypeUpdate(BaseModel):
    """Payload for updating mutable asset type fields."""

    model_config = ConfigDict(extra="forbid")

    display_name: str | None = Field(default=None, max_length=255)
    description: str | None = None
    metadata_json: dict[str, Any] | None = None


class AssetCategory(MarketsRow):
    """Typed asset universe row."""

    __table__: ClassVar[type[AssetCategoryTable]] = AssetCategoryTable
    __required_tables__: ClassVar[list[type[AssetCategoryTable]]] = [AssetCategoryTable]
    __upsert_keys__: ClassVar[tuple[str, ...]] = ("unique_identifier",)

    unique_identifier: str
    display_name: str
    description: str | None = None
    metadata_json: dict[str, Any] | None = None

    @classmethod
    def replace_memberships(
        cls,
        *,
        category_uid: uuid.UUID | str,
        asset_uids: list[uuid.UUID | str],
    ) -> list[AssetCategoryMembership]:
        """Replace the asset membership set for one category."""

        from msm.repositories.asset_categories import (
            replace_asset_category_memberships,
        )

        context = AssetCategoryMembership._active_context()
        results = replace_asset_category_memberships(
            context,
            category_uid=category_uid,
            asset_uids=asset_uids,
        )
        rows: list[AssetCategoryMembership] = []
        for result in results:
            row = AssetCategoryMembership._from_operation_result(
                result,
                required=False,
            )
            if row is not None:
                rows.append(row)
        return rows


class AssetCategoryCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    unique_identifier: str = Field(min_length=1, max_length=255)
    display_name: str = Field(min_length=1, max_length=255)
    description: str | None = None
    metadata_json: dict[str, Any] | None = None


class AssetCategoryUpsert(AssetCategoryCreate):
    """Payload for inserting or updating an asset category row."""


class AssetCategoryUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    display_name: str | None = Field(default=None, max_length=255)
    description: str | None = None
    metadata_json: dict[str, Any] | None = None


class AssetCategoryMembership(MarketsRow):
    """Typed membership row between an asset category and an asset."""

    __table__: ClassVar[type[AssetCategoryMembershipTable]] = AssetCategoryMembershipTable
    __required_tables__: ClassVar[list[type[Any]]] = [
        AssetTable,
        AssetCategoryTable,
        AssetCategoryMembershipTable,
    ]
    __upsert_keys__: ClassVar[tuple[str, ...]] = ("category_uid", "asset_uid")

    category_uid: uuid.UUID
    asset_uid: uuid.UUID


class AssetCategoryMembershipCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    category_uid: uuid.UUID | str
    asset_uid: uuid.UUID | str


class AssetCategoryMembershipUpsert(AssetCategoryMembershipCreate):
    """Payload for inserting or updating an asset category membership row."""


class OpenFigiDetails(MarketsRow):
    """Typed OpenFIGI/provider detail row linked to an asset."""

    __table__: ClassVar[type[OpenFigiDetailsTable]] = OpenFigiDetailsTable
    __required_tables__: ClassVar[list[type[Any]]] = [AssetTable, OpenFigiDetailsTable]
    __upsert_keys__: ClassVar[tuple[str, ...]] = ("asset_uid",)

    uid: uuid.UUID = Field(validation_alias=AliasChoices("uid", "asset_uid"))
    asset_uid: uuid.UUID
    figi: str | None = None
    composite: str | None = None
    share_class: str | None = None
    isin: str | None = None
    ticker: str | None = None
    name: str | None = None
    exchange_code: str | None = None
    security_type: str | None = None
    security_type_2: str | None = None
    security_market_sector: str | None = None
    security_description: str | None = None
    unique_id: str | None = None
    unique_id_fut_opt: str | None = None
    metadata_text: str | None = None
    raw_payload: dict[str, Any] | None = None


class OpenFigiDetailsCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    asset_uid: uuid.UUID | str
    figi: str | None = Field(default=None, max_length=12)
    composite: str | None = Field(default=None, max_length=12)
    share_class: str | None = Field(default=None, max_length=12)
    isin: str | None = Field(default=None, max_length=12)
    ticker: str | None = Field(default=None, max_length=50)
    name: str | None = Field(default=None, max_length=255)
    exchange_code: str | None = Field(default=None, max_length=50)
    security_type: str | None = Field(default=None, max_length=50)
    security_type_2: str | None = Field(default=None, max_length=50)
    security_market_sector: str | None = Field(default=None, max_length=50)
    security_description: str | None = Field(default=None, max_length=255)
    unique_id: str | None = Field(default=None, max_length=255)
    unique_id_fut_opt: str | None = Field(default=None, max_length=255)
    metadata_text: str | None = None
    raw_payload: dict[str, Any] | None = None


class OpenFigiDetailsUpsert(OpenFigiDetailsCreate):
    """Payload for inserting or updating OpenFIGI details by asset UID."""


class OpenFigiDetailsUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    figi: str | None = Field(default=None, max_length=12)
    composite: str | None = Field(default=None, max_length=12)
    share_class: str | None = Field(default=None, max_length=12)
    isin: str | None = Field(default=None, max_length=12)
    ticker: str | None = Field(default=None, max_length=50)
    name: str | None = Field(default=None, max_length=255)
    exchange_code: str | None = Field(default=None, max_length=50)
    security_type: str | None = Field(default=None, max_length=50)
    security_type_2: str | None = Field(default=None, max_length=50)
    security_market_sector: str | None = Field(default=None, max_length=50)
    security_description: str | None = Field(default=None, max_length=255)
    unique_id: str | None = Field(default=None, max_length=255)
    unique_id_fut_opt: str | None = Field(default=None, max_length=255)
    metadata_text: str | None = None
    raw_payload: dict[str, Any] | None = None


__all__ = [
    "Asset",
    "AssetCategory",
    "AssetCategoryCreate",
    "AssetCategoryMembership",
    "AssetCategoryMembershipCreate",
    "AssetCategoryMembershipUpsert",
    "AssetCategoryUpdate",
    "AssetCategoryUpsert",
    "AssetCreate",
    "AssetType",
    "AssetTypeCreate",
    "AssetTypeUpdate",
    "AssetTypeUpsert",
    "AssetUpdate",
    "AssetUpsert",
    "OpenFigiDetails",
    "OpenFigiDetailsCreate",
    "OpenFigiDetailsUpdate",
    "OpenFigiDetailsUpsert",
]
