from __future__ import annotations

import uuid
from collections.abc import Sequence
from typing import Any

from metatables import MetaTableCompiledSQLDialect, MetaTableCompiledSQLOperation
from sqlalchemy import and_, func, literal, select

from msm.models import AssetTable
from msm.time_index.assets.storage import AssetSnapshotsStorage

from .base import (
    MarketsCompiledWrite,
    MarketsOperationContext,
    execute_markets_operation,
)
from .crud import (
    UpsertStatus,
    build_create_model_operation,
    build_delete_model_operation,
    build_get_model_by_uid_operation,
    build_get_model_by_unique_identifier_operation,
    build_search_model_operation,
    build_update_model_operation,
    build_upsert_model_operation,
    upsert_model,
)


def build_create_asset_operation(
    asset: MarketsOperationContext,
    *,
    unique_identifier: str,
    asset_type: str | None = None,
) -> MetaTableCompiledSQLOperation:
    return build_create_model_operation(
        asset,
        model=AssetTable,
        values={
            "unique_identifier": unique_identifier,
            "asset_type": asset_type,
        },
    )


def create_asset(asset: MarketsOperationContext, **kwargs: Any) -> dict[str, Any]:
    return execute_markets_operation(
        build_create_asset_operation(asset, **kwargs),
        context=asset,
    )


def build_upsert_asset_operation(
    asset: MarketsOperationContext,
    *,
    unique_identifier: str,
    asset_type: str | None = None,
    dialect: MetaTableCompiledSQLDialect | None = None,
    statuses: Sequence[UpsertStatus] | None = None,
) -> MarketsCompiledWrite:
    return build_upsert_model_operation(
        asset,
        model=AssetTable,
        values={"unique_identifier": unique_identifier, "asset_type": asset_type},
        conflict_columns=("unique_identifier",),
        dialect=dialect,
        statuses=statuses,
    )


def upsert_asset(
    asset: MarketsOperationContext,
    *,
    unique_identifier: str,
    asset_type: str | None = None,
) -> dict[str, Any]:
    return upsert_model(
        asset,
        model=AssetTable,
        values={"unique_identifier": unique_identifier, "asset_type": asset_type},
        conflict_columns=("unique_identifier",),
    )


def build_get_asset_by_uid_operation(
    asset: MarketsOperationContext,
    *,
    uid: uuid.UUID | str,
) -> MetaTableCompiledSQLOperation:
    return build_get_model_by_uid_operation(asset, model=AssetTable, uid=uid)


def get_asset_by_uid(
    asset: MarketsOperationContext,
    *,
    uid: uuid.UUID | str,
) -> dict[str, Any]:
    return execute_markets_operation(
        build_get_asset_by_uid_operation(asset, uid=uid),
        context=asset,
    )


def build_get_asset_by_unique_identifier_operation(
    asset: MarketsOperationContext,
    *,
    unique_identifier: str,
) -> MetaTableCompiledSQLOperation:
    return build_get_model_by_unique_identifier_operation(
        asset,
        model=AssetTable,
        unique_identifier=unique_identifier,
    )


def get_asset_by_unique_identifier(
    asset: MarketsOperationContext,
    *,
    unique_identifier: str,
) -> dict[str, Any]:
    return execute_markets_operation(
        build_get_asset_by_unique_identifier_operation(
            asset,
            unique_identifier=unique_identifier,
        ),
        context=asset,
    )


def build_search_assets_operation(
    asset: MarketsOperationContext,
    *,
    unique_identifier_contains: str | None = None,
    asset_type: str | None = None,
    uids: Sequence[uuid.UUID | str] | None = None,
    limit: int = 500,
) -> MetaTableCompiledSQLOperation:
    filters: dict[str, Any] = {}
    in_filters: dict[str, Sequence[uuid.UUID | str]] = {}
    if asset_type not in (None, ""):
        filters["asset_type"] = asset_type
    if uids:
        in_filters["uid"] = uids
    return build_search_model_operation(
        asset,
        model=AssetTable,
        filters=filters,
        in_filters=in_filters,
        contains_filters={"unique_identifier": unique_identifier_contains or ""},
        limit=limit,
    )


def search_assets(asset: MarketsOperationContext, **kwargs: Any) -> dict[str, Any]:
    return execute_markets_operation(
        build_search_assets_operation(asset, **kwargs),
        context=asset,
    )


def build_update_asset_operation(
    asset: MarketsOperationContext,
    *,
    uid: uuid.UUID | str,
    asset_type: str | None = None,
) -> MetaTableCompiledSQLOperation:
    return build_update_model_operation(
        asset,
        model=AssetTable,
        uid=uid,
        values={
            key: value
            for key, value in {
                "asset_type": asset_type,
            }.items()
            if value is not None
        },
    )


def update_asset(asset: MarketsOperationContext, **kwargs: Any) -> dict[str, Any]:
    return execute_markets_operation(
        build_update_asset_operation(asset, **kwargs),
        context=asset,
    )


def build_delete_asset_operation(
    asset: MarketsOperationContext,
    *,
    uid: uuid.UUID | str,
) -> MetaTableCompiledSQLOperation:
    return build_delete_model_operation(asset, model=AssetTable, uid=uid)


def delete_asset(
    asset: MarketsOperationContext,
    *,
    uid: uuid.UUID | str,
) -> dict[str, Any]:
    return execute_markets_operation(
        build_delete_asset_operation(asset, uid=uid),
        context=asset,
    )


def asset_reference_select(identifiers: Sequence[str], *, latest_snapshot: bool) -> Any:
    """The assets ``identifiers`` name, each with its latest snapshot's values."""

    if not latest_snapshot:
        return (
            select(
                AssetTable.uid.label("asset_uid"),
                AssetTable.unique_identifier.label("asset_identifier"),
                AssetTable.asset_type.label("asset_type"),
                literal(None).label("snapshot_time"),
                literal(None).label("time_index"),
                literal(None).label("name"),
                literal(None).label("ticker"),
                literal(None).label("exchange_code"),
                literal(None).label("asset_ticker_group_id"),
            )
            .select_from(AssetTable)
            .where(AssetTable.unique_identifier.in_(identifiers))
            .order_by(AssetTable.unique_identifier.asc())
        )

    latest_snapshots = (
        select(
            AssetSnapshotsStorage.asset_identifier.label("asset_identifier"),
            func.max(AssetSnapshotsStorage.time_index).label("snapshot_time"),
        )
        .where(AssetSnapshotsStorage.asset_identifier.in_(identifiers))
        .group_by(AssetSnapshotsStorage.asset_identifier)
        .subquery()
    )

    return (
        select(
            AssetTable.uid.label("asset_uid"),
            AssetTable.unique_identifier.label("asset_identifier"),
            AssetTable.asset_type.label("asset_type"),
            AssetSnapshotsStorage.time_index.label("snapshot_time"),
            AssetSnapshotsStorage.time_index.label("time_index"),
            AssetSnapshotsStorage.name.label("name"),
            AssetSnapshotsStorage.ticker.label("ticker"),
            AssetSnapshotsStorage.exchange_code.label("exchange_code"),
            AssetSnapshotsStorage.asset_ticker_group_id.label("asset_ticker_group_id"),
        )
        .select_from(AssetTable)
        .outerjoin(
            latest_snapshots,
            latest_snapshots.c.asset_identifier == AssetTable.unique_identifier,
        )
        .outerjoin(
            AssetSnapshotsStorage,
            and_(
                AssetSnapshotsStorage.asset_identifier == latest_snapshots.c.asset_identifier,
                AssetSnapshotsStorage.time_index == latest_snapshots.c.snapshot_time,
            ),
        )
        .where(AssetTable.unique_identifier.in_(identifiers))
        .order_by(AssetTable.unique_identifier.asc())
    )


__all__ = [
    "asset_reference_select",
    "build_create_asset_operation",
    "build_delete_asset_operation",
    "build_get_asset_by_uid_operation",
    "build_get_asset_by_unique_identifier_operation",
    "build_search_assets_operation",
    "build_update_asset_operation",
    "build_upsert_asset_operation",
    "create_asset",
    "delete_asset",
    "get_asset_by_uid",
    "get_asset_by_unique_identifier",
    "search_assets",
    "update_asset",
    "upsert_asset",
]
