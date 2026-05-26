from __future__ import annotations

import uuid
from collections.abc import Mapping
from typing import Any, ClassVar

from pydantic import BaseModel, ConfigDict, Field

from msm.models import AssetTable
from msm.repositories.assets import (
    get_asset_by_uid as repository_get_asset_by_uid,
    get_asset_by_unique_identifier as repository_get_asset_by_unique_identifier,
    search_assets as repository_search_assets,
    upsert_asset as repository_upsert_asset,
)


class Asset(BaseModel):
    """User-facing asset row returned by typed markets API helpers."""

    model_config = ConfigDict(extra="ignore", frozen=True)

    __table__: ClassVar[type[AssetTable]] = AssetTable
    __required_tables__: ClassVar[list[type[AssetTable]]] = [AssetTable]

    uid: uuid.UUID
    unique_identifier: str
    asset_type: str | None = None

    @classmethod
    def create_schemas(cls, **kwargs: Any):
        """Create the MetaTable schemas required by asset row operations."""

        from msm.bootstrap import create_schemas

        requested_models = kwargs.pop("models", None)
        models = list(cls.__required_tables__)
        if requested_models is not None:
            models.extend(requested_models)
        return create_schemas(models=models, **kwargs)

    @classmethod
    def upsert(cls, payload: AssetUpsert | None = None, **kwargs: Any) -> Asset:
        """Upsert one asset through the active markets runtime."""

        return _upsert_asset_row(_active_asset_table(cls), payload or AssetUpsert(**kwargs))

    @classmethod
    def get_by_uid(cls, uid: uuid.UUID | str) -> Asset | None:
        """Return one asset by UID from the active markets runtime."""

        return _get_asset_row_by_uid(_active_asset_table(cls), uid=uid)

    @classmethod
    def get_by_unique_identifier(cls, unique_identifier: str) -> Asset | None:
        """Return one asset by stable business identifier."""

        return _get_asset_row_by_unique_identifier(
            _active_asset_table(cls),
            unique_identifier=unique_identifier,
        )

    @classmethod
    def filter(
        cls,
        *,
        unique_identifier_contains: str | None = None,
        asset_type: str | None = None,
        limit: int = 500,
    ) -> list[Asset]:
        """Filter assets through the active markets runtime."""

        return _search_asset_rows(
            _active_asset_table(cls),
            unique_identifier_contains=unique_identifier_contains,
            asset_type=asset_type,
            limit=limit,
        )


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


def _upsert_asset_row(
    asset_table: Any,
    asset: AssetUpsert,
) -> Asset:
    """Upsert one asset and return the typed row object."""

    result = repository_upsert_asset(
        asset_table,
        **asset.model_dump(exclude_unset=True),
    )
    return _asset_from_operation_result(result)


def _get_asset_row_by_uid(
    asset_table: Any,
    *,
    uid: uuid.UUID | str,
) -> Asset | None:
    """Return one typed asset row by UID, or None when no row is returned."""

    result = repository_get_asset_by_uid(asset_table, uid=uid)
    return _asset_from_operation_result(result, required=False)


def _get_asset_row_by_unique_identifier(
    asset_table: Any,
    *,
    unique_identifier: str,
) -> Asset | None:
    """Return one typed asset row by business identifier, or None."""

    result = repository_get_asset_by_unique_identifier(
        asset_table,
        unique_identifier=unique_identifier,
    )
    return _asset_from_operation_result(result, required=False)


def _search_asset_rows(
    asset_table: Any,
    *,
    unique_identifier_contains: str | None = None,
    asset_type: str | None = None,
    limit: int = 500,
) -> list[Asset]:
    """Search assets and return typed row objects."""

    result = repository_search_assets(
        asset_table,
        unique_identifier_contains=unique_identifier_contains,
        asset_type=asset_type,
        limit=limit,
    )
    return [Asset.model_validate(row) for row in _operation_result_rows(result)]


def _asset_from_operation_result(
    result: Mapping[str, Any],
    *,
    required: bool = True,
) -> Asset | None:
    """Extract one asset row from a platform MetaTable operation result."""

    rows = _operation_result_rows(result)
    if rows:
        return Asset.model_validate(rows[0])
    if required:
        raise LookupError("MetaTable operation result did not include an Asset row.")
    return None


def _operation_result_rows(result: Mapping[str, Any] | list[Any] | None) -> list[dict[str, Any]]:
    """Normalize common MetaTable operation result envelopes to row dictionaries."""

    if result is None:
        return []
    if isinstance(result, list):
        return [row for row in result if isinstance(row, dict)]
    if not isinstance(result, Mapping):
        return []

    for key in ("rows", "results"):
        rows = result.get(key)
        if isinstance(rows, list):
            return [row for row in rows if isinstance(row, dict)]

    for key in ("row", "data"):
        value = result.get(key)
        if isinstance(value, Mapping):
            nested_rows = _operation_result_rows(value)
            if nested_rows:
                return nested_rows
            if _looks_like_asset_row(value):
                return [dict(value)]
        if isinstance(value, list):
            return [row for row in value if isinstance(row, dict)]

    if _looks_like_asset_row(result):
        return [dict(result)]
    return []


def _looks_like_asset_row(value: Mapping[str, Any]) -> bool:
    return "uid" in value and "unique_identifier" in value


def _active_asset_table(asset_model: type[Asset]):
    from msm.bootstrap import get_runtime

    runtime = get_runtime()
    return runtime.table(asset_model.__table__)


__all__ = [
    "Asset",
    "AssetCreate",
    "AssetUpdate",
    "AssetUpsert",
]
