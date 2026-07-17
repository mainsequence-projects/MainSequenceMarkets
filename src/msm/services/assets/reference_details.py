"""Reusable read services for canonical asset reference details."""

from __future__ import annotations

import uuid
from collections.abc import Callable, Mapping, Sequence
from typing import Any

from sqlalchemy import and_, func, literal, select

from msm.base import MarketsBase
from msm.data_nodes.assets.storage import AssetSnapshotsStorage
from msm.models import AssetTable
from msm.repositories.base import (
    MarketsOperationContext,
    compile_markets_statement,
    execute_markets_operation,
)

AssetReferenceExecutor = Callable[
    [Any, Sequence[type[MarketsBase]]],
    Mapping[str, Any] | list[Any] | None,
]


def asset_reference_details(
    asset_identifiers: str | Sequence[str],
    *,
    latest_snapshot: bool = True,
    repository_context: MarketsOperationContext | None = None,
    executor: AssetReferenceExecutor | None = None,
) -> list[dict[str, Any]]:
    """Return asset identity rows with optional latest display snapshot details.

    ``asset_identifiers`` are canonical ``AssetTable.unique_identifier`` values.
    Snapshot data is read from ``AssetSnapshotsStorage`` using the same
    identifier as its storage-facing ``asset_identifier`` dimension.
    """

    identifiers = _normalize_identifiers(asset_identifiers, field_name="asset_identifiers")
    if not identifiers:
        return []

    statement = _asset_reference_select(identifiers, latest_snapshot=latest_snapshot)
    rows = _execute_statement(
        repository_context=repository_context,
        statement=statement,
        models=(AssetTable, AssetSnapshotsStorage) if latest_snapshot else (AssetTable,),
        executor=executor,
    )
    return _order_rows_by_identifier(rows, identifiers=identifiers)


def asset_reference_details_by_uids(
    asset_uids: str | uuid.UUID | Sequence[str | uuid.UUID],
    *,
    latest_snapshot: bool = True,
    repository_context: MarketsOperationContext | None = None,
    executor: AssetReferenceExecutor | None = None,
) -> list[dict[str, Any]]:
    """Return asset reference rows for canonical ``AssetTable.uid`` values."""

    requested_uids = _normalize_uids(asset_uids, field_name="asset_uids")
    if not requested_uids:
        return []

    statement = _asset_reference_select_by_uids(requested_uids, latest_snapshot=latest_snapshot)
    rows = _execute_statement(
        repository_context=repository_context,
        statement=statement,
        models=(AssetTable, AssetSnapshotsStorage) if latest_snapshot else (AssetTable,),
        executor=executor,
    )
    return _order_rows_by_key(rows, values=requested_uids, key="asset_uid")


def _asset_reference_select(identifiers: Sequence[str], *, latest_snapshot: bool):
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


def _asset_reference_select_by_uids(asset_uids: Sequence[uuid.UUID], *, latest_snapshot: bool):
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
            .where(AssetTable.uid.in_(asset_uids))
            .order_by(AssetTable.uid.asc())
        )

    requested_assets = (
        select(
            AssetTable.uid.label("asset_uid"),
            AssetTable.unique_identifier.label("asset_identifier"),
        )
        .where(AssetTable.uid.in_(asset_uids))
        .subquery("requested_assets")
    )
    latest_snapshots = (
        select(
            AssetSnapshotsStorage.asset_identifier.label("asset_identifier"),
            func.max(AssetSnapshotsStorage.time_index).label("snapshot_time"),
        )
        .select_from(AssetSnapshotsStorage)
        .join(
            requested_assets,
            requested_assets.c.asset_identifier == AssetSnapshotsStorage.asset_identifier,
        )
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
        .where(AssetTable.uid.in_(asset_uids))
        .order_by(AssetTable.uid.asc())
    )


def _execute_statement(
    *,
    repository_context: MarketsOperationContext | None,
    statement: Any,
    models: Sequence[type[MarketsBase]],
    executor: AssetReferenceExecutor | None,
) -> list[dict[str, Any]]:
    if executor is not None:
        return _operation_result_rows(executor(statement, tuple(models)))
    if repository_context is None:
        raise ValueError("repository_context is required when executor is not provided.")

    return _operation_result_rows(
        execute_markets_operation(
            compile_markets_statement(
                statement,
                context=repository_context,
                operation="select",
                models=models,
                access="read",
            ),
            context=repository_context,
        )
    )


def _normalize_identifiers(
    identifiers: str | Sequence[str],
    *,
    field_name: str,
) -> tuple[str, ...]:
    raw_values: Sequence[str]
    if isinstance(identifiers, str):
        raw_values = [identifiers]
    else:
        raw_values = identifiers

    normalized: list[str] = []
    seen: set[str] = set()
    for raw_value in raw_values:
        value = str(raw_value).strip()
        if not value:
            raise ValueError(f"{field_name} entries must be non-empty strings.")
        if value in seen:
            continue
        normalized.append(value)
        seen.add(value)
    return tuple(normalized)


def _normalize_uids(
    identifiers: str | uuid.UUID | Sequence[str | uuid.UUID],
    *,
    field_name: str,
) -> tuple[uuid.UUID, ...]:
    raw_values: Sequence[str | uuid.UUID]
    if isinstance(identifiers, str | uuid.UUID):
        raw_values = [identifiers]
    else:
        raw_values = identifiers

    normalized: list[uuid.UUID] = []
    seen: set[uuid.UUID] = set()
    for raw_value in raw_values:
        try:
            value = raw_value if isinstance(raw_value, uuid.UUID) else uuid.UUID(str(raw_value))
        except (TypeError, ValueError) as exc:
            raise ValueError(f"{field_name} entries must be valid UUIDs.") from exc
        if value in seen:
            continue
        normalized.append(value)
        seen.add(value)
    return tuple(normalized)


def _order_rows_by_identifier(
    rows: Sequence[Mapping[str, Any]],
    *,
    identifiers: Sequence[str],
) -> list[dict[str, Any]]:
    identifier_order = {identifier: index for index, identifier in enumerate(identifiers)}
    return sorted(
        [dict(row) for row in rows],
        key=lambda row: (
            identifier_order.get(str(row.get("asset_identifier")), len(identifier_order)),
            str(row.get("asset_identifier") or ""),
        ),
    )


def _order_rows_by_key(
    rows: Sequence[Mapping[str, Any]],
    *,
    values: Sequence[Any],
    key: str,
) -> list[dict[str, Any]]:
    value_order = {str(value): index for index, value in enumerate(values)}
    return sorted(
        [dict(row) for row in rows],
        key=lambda row: (
            value_order.get(str(row.get(key)), len(value_order)),
            str(row.get(key) or ""),
        ),
    )


def _operation_result_rows(result: Mapping[str, Any] | list[Any] | None) -> list[dict[str, Any]]:
    if result is None:
        return []
    if isinstance(result, list):
        return [dict(row) for row in result if isinstance(row, Mapping)]
    if not isinstance(result, Mapping):
        return []
    for key in ("rows", "results"):
        rows = result.get(key)
        if isinstance(rows, list):
            return [dict(row) for row in rows if isinstance(row, Mapping)]
    for key in ("row", "data"):
        value = result.get(key)
        if isinstance(value, Mapping):
            return [dict(value)]
        if isinstance(value, list):
            return [dict(row) for row in value if isinstance(row, Mapping)]
    return []


__all__ = [
    "AssetReferenceExecutor",
    "asset_reference_details",
    "asset_reference_details_by_uids",
]
