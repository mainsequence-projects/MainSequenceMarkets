from __future__ import annotations

import datetime as dt
import uuid
from collections.abc import Mapping, Sequence
from typing import Any, Literal

from sqlalchemy import String, cast, func, or_, select

from msm.data_nodes.assets.storage import AssetSnapshotsStorage
from msm.models import AssetTable, IndexTable, PortfolioTable
from msm.repositories import MarketsRepositoryContext
from msm.repositories.crud import delete_model, get_model_by_uid, search_model
from msm.repositories.base import compile_markets_statement, execute_markets_operation
from msm_portfolios.data_nodes.portfolios.storage import PortfolioWeightsStorage
from msm_portfolios.models import PortfolioMetadataTable

DEFAULT_PORTFOLIO_PAGE_SIZE = 50
MAX_PORTFOLIO_SCAN_LIMIT = 500


class PortfolioDeleteConflictError(ValueError):
    """Raised when a portfolio cannot be deleted because protected rows reference it."""


def list_portfolio_rows_response(
    context: MarketsRepositoryContext,
    *,
    search: str = "",
    calendar_uid: str | uuid.UUID | None = None,
    calendar_name: str | None = None,
    limit: int = DEFAULT_PORTFOLIO_PAGE_SIZE,
    offset: int = 0,
) -> dict[str, Any]:
    """Return paginated core Portfolio rows with a total count."""

    filters = _portfolio_filter_args(
        search=search,
        calendar_uid=calendar_uid,
        calendar_name=calendar_name,
    )
    rows = _operation_result_rows(
        _execute_portfolio_select(
            context,
            _portfolio_select(**filters)
            .order_by(PortfolioTable.unique_identifier, PortfolioTable.uid)
            .limit(limit)
            .offset(offset),
        )
    )
    count = _count_from_result(
        _execute_portfolio_select(
            context,
            select(func.count().label("count")).select_from(
                _portfolio_select(**filters).subquery()
            ),
        )
    )
    return {
        "count": count,
        "results": [_build_portfolio_row(row) for row in rows],
    }


def get_portfolio_detail_response(
    context: MarketsRepositoryContext,
    *,
    uid: str,
) -> dict[str, Any] | None:
    portfolio_row = _get_portfolio_row(context, uid=uid)
    if portfolio_row is None:
        return None

    portfolio = _build_portfolio_row(portfolio_row)
    portfolio_uid = str(portfolio["uid"])
    metadata = _get_portfolio_metadata_row(
        context,
        unique_identifier=str(portfolio["unique_identifier"]),
    )
    return {
        "portfolio": portfolio,
        "metadata": _build_portfolio_metadata_row(metadata) if metadata is not None else None,
        "tabs": [
            {
                "key": "latest_weights",
                "label": "Latest Weights",
                "url": (
                    f"/api/v1/portfolio/{portfolio_uid}/weights/"
                    "?order=desc&limit=1&include_asset_detail=true"
                ),
            }
        ],
        "links": {
            "summary": f"/api/v1/portfolio/{portfolio_uid}/summary/",
            "latest_weights": f"/api/v1/portfolio/{portfolio_uid}/weights/",
            "delete": f"/api/v1/portfolio/{portfolio_uid}/",
        },
    }


def get_portfolio_frontend_detail_summary(
    context: MarketsRepositoryContext,
    *,
    uid: str,
) -> dict[str, Any] | None:
    portfolio_row = _get_portfolio_row(context, uid=uid)
    if portfolio_row is None:
        return None

    portfolio = _build_portfolio_row(portfolio_row)
    metadata = _get_portfolio_metadata_row(
        context,
        unique_identifier=str(portfolio["unique_identifier"]),
    )
    portfolio_uid = str(portfolio["uid"])
    title = str(portfolio["unique_identifier"]) or portfolio_uid
    badges = []
    if portfolio.get("portfolio_index_uid") not in (None, ""):
        badges.append({"key": "portfolio_index", "label": "Indexed", "tone": "info"})

    return {
        "entity": {
            "id": portfolio_uid,
            "type": "portfolio",
            "title": title,
        },
        "badges": badges,
        "inline_fields": [
            {
                "key": "uid",
                "label": "UID",
                "value": portfolio_uid,
                "kind": "code",
            },
            {
                "key": "unique_identifier",
                "label": "Identifier",
                "value": portfolio["unique_identifier"],
                "kind": "code",
            },
            {
                "key": "calendar_uid",
                "label": "Calendar UID",
                "value": _string_or_none(portfolio.get("calendar_uid")),
                "kind": "code",
            },
            {
                "key": "portfolio_index_uid",
                "label": "Portfolio Index UID",
                "value": _string_or_none(portfolio.get("portfolio_index_uid")),
                "kind": "code",
            },
        ],
        "highlight_fields": [
            {
                "key": "calendar_name",
                "label": "Calendar",
                "value": _string_or_none(portfolio.get("calendar_name")),
                "kind": "text",
                "icon": "calendar",
            },
        ],
        "stats": [],
        "label_management": {
            "labels": [],
            "add_label_url": None,
            "remove_label_url": None,
        },
        "summary_warning": None,
        "extensions": {
            "description": _string_or_none(metadata.get("description")) if metadata else None,
            "detail_url": f"/api/v1/portfolio/{portfolio_uid}/",
            "latest_weights_url": f"/api/v1/portfolio/{portfolio_uid}/weights/",
            "delete_url": f"/api/v1/portfolio/{portfolio_uid}/",
        },
    }


def get_portfolio_weights_snapshot_response(
    context: MarketsRepositoryContext,
    *,
    uid: str,
    order: Literal["asc", "desc"] = "desc",
    limit: int = 1,
    include_asset_detail: bool = True,
    weights_date: dt.datetime | None = None,
) -> dict[str, Any] | None:
    if limit != 1:
        raise ValueError("Portfolio weights endpoint currently supports limit=1.")

    portfolio_row = _get_portfolio_row(context, uid=uid)
    if portfolio_row is None:
        return None

    portfolio = _build_portfolio_row(portfolio_row)
    portfolio_index_uid = _string_or_none(portfolio.get("portfolio_index_uid"))
    if portfolio_index_uid is None:
        return _empty_weights_snapshot(
            portfolio=portfolio,
            portfolio_index_identifier=None,
            warning="Portfolio has no portfolio_index_uid; latest weights cannot be resolved.",
        )

    index_row = _first_operation_row(
        get_model_by_uid(context, model=IndexTable, uid=portfolio_index_uid)
    )
    if index_row is None:
        return _empty_weights_snapshot(
            portfolio=portfolio,
            portfolio_index_identifier=None,
            warning=(
                "Portfolio portfolio_index_uid could not be resolved to an Index row; "
                "latest weights cannot be resolved."
            ),
        )

    portfolio_index_identifier = _string_or_none(index_row.get("unique_identifier"))
    if portfolio_index_identifier is None:
        return _empty_weights_snapshot(
            portfolio=portfolio,
            portfolio_index_identifier=None,
            warning="Resolved portfolio index row has no unique_identifier.",
        )

    snapshot_time = weights_date or _portfolio_weights_snapshot_time(
        context,
        portfolio_index_identifier=portfolio_index_identifier,
        order=order,
    )
    if snapshot_time is None:
        return _empty_weights_snapshot(
            portfolio=portfolio,
            portfolio_index_identifier=portfolio_index_identifier,
            warning=None,
        )

    weight_rows = _portfolio_weights_rows(
        context,
        portfolio_index_identifier=portfolio_index_identifier,
        weights_date=snapshot_time,
    )
    if not weight_rows:
        return _empty_weights_snapshot(
            portfolio=portfolio,
            portfolio_index_identifier=portfolio_index_identifier,
            warning=None,
        )

    asset_references = (
        _asset_references_by_unique_identifier(context, rows=weight_rows)
        if include_asset_detail
        else {}
    )
    return {
        "portfolio_uid": _string_or_none(portfolio["uid"]),
        "portfolio_unique_identifier": _string_or_none(portfolio["unique_identifier"]),
        "portfolio_index_uid": portfolio_index_uid,
        "portfolio_index_identifier": portfolio_index_identifier,
        "weights_date": snapshot_time,
        "resolution_warning": None,
        "weights": [
            _build_weight_row(
                row=row,
                asset_reference=asset_references.get(str(row.get("asset_identifier"))),
                include_asset_detail=include_asset_detail,
            )
            for row in sorted(weight_rows, key=lambda row: str(row.get("asset_identifier", "")))
        ],
    }


def delete_portfolio_record(
    context: MarketsRepositoryContext,
    *,
    uid: str,
) -> bool:
    existing = _get_portfolio_row(context, uid=uid)
    if existing is None:
        return False

    try:
        delete_model(context, model=PortfolioTable, uid=uid)
    except Exception as exc:
        if _is_delete_conflict(exc):
            raise PortfolioDeleteConflictError(
                "Portfolio is referenced by target positions or other protected rows."
            ) from exc
        raise
    return True


def bulk_delete_portfolio_records(
    context: MarketsRepositoryContext,
    *,
    uids: Sequence[str],
) -> dict[str, Any]:
    deleted_count = 0
    failed: list[dict[str, str]] = []

    for uid in dict.fromkeys(str(value) for value in uids if str(value).strip()):
        try:
            deleted = delete_portfolio_record(context, uid=uid)
        except PortfolioDeleteConflictError as exc:
            failed.append({"uid": uid, "reason": str(exc)})
            continue
        if deleted:
            deleted_count += 1
        else:
            failed.append({"uid": uid, "reason": "Portfolio was not found."})

    if failed and deleted_count:
        detail = (
            f"Deleted {deleted_count} portfolio{'s' if deleted_count != 1 else ''}; "
            f"{len(failed)} portfolio{'s' if len(failed) != 1 else ''} could not be deleted."
        )
    elif failed:
        detail = f"No portfolios were deleted; {len(failed)} portfolio deletion failed."
    else:
        detail = f"Deleted {deleted_count} portfolio{'s' if deleted_count != 1 else ''}."

    return {
        "detail": detail,
        "deleted_count": deleted_count,
        "failed": failed,
    }


def _portfolio_filter_args(
    *,
    search: str,
    calendar_uid: str | uuid.UUID | None,
    calendar_name: str | None,
) -> dict[str, Any]:
    return {
        "search": search.strip(),
        "calendar_uid": None if calendar_uid in (None, "") else calendar_uid,
        "calendar_name": _string_or_none(calendar_name),
    }


def _portfolio_select(
    *,
    search: str,
    calendar_uid: str | uuid.UUID | None,
    calendar_name: str | None,
):
    statement = select(PortfolioTable)
    if calendar_uid is not None:
        statement = statement.where(PortfolioTable.calendar_uid == calendar_uid)
    if calendar_name is not None:
        statement = statement.where(PortfolioTable.calendar_name == calendar_name)

    normalized_search = search.strip().lower()
    if normalized_search:
        needle = f"%{normalized_search}%"
        statement = statement.where(
            or_(
                func.lower(cast(PortfolioTable.uid, String)).like(needle),
                func.lower(PortfolioTable.unique_identifier).like(needle),
                func.lower(PortfolioTable.calendar_name).like(needle),
                func.lower(cast(PortfolioTable.calendar_uid, String)).like(needle),
                func.lower(cast(PortfolioTable.portfolio_index_uid, String)).like(needle),
            )
        )
    return statement


def _execute_portfolio_select(context: MarketsRepositoryContext, statement) -> dict[str, Any]:
    return execute_markets_operation(
        compile_markets_statement(
            statement,
            context=context,
            operation="select",
            models=[PortfolioTable],
            access="read",
        ),
        context=context,
    )


def _get_portfolio_row(
    context: MarketsRepositoryContext,
    *,
    uid: str,
) -> dict[str, Any] | None:
    return _first_operation_row(get_model_by_uid(context, model=PortfolioTable, uid=uid))


def _get_portfolio_metadata_row(
    context: MarketsRepositoryContext,
    *,
    unique_identifier: str,
) -> dict[str, Any] | None:
    rows = _operation_result_rows(
        search_model(
            context,
            model=PortfolioMetadataTable,
            filters={"unique_identifier": unique_identifier},
            limit=1,
        )
    )
    return rows[0] if rows else None


def _portfolio_weights_snapshot_time(
    context: MarketsRepositoryContext,
    *,
    portfolio_index_identifier: str,
    order: Literal["asc", "desc"],
) -> dt.datetime | None:
    aggregate = (
        func.min(PortfolioWeightsStorage.time_index)
        if order == "asc"
        else func.max(PortfolioWeightsStorage.time_index)
    )
    statement = select(aggregate.label("time_index")).where(
        PortfolioWeightsStorage.portfolio_index_identifier == portfolio_index_identifier
    )
    result = execute_markets_operation(
        compile_markets_statement(
            statement,
            context=context,
            operation="select",
            models=[PortfolioWeightsStorage],
            access="read",
        ),
        context=context,
    )
    row = _first_operation_row(result)
    if row is None:
        return None
    return _datetime_or_none(row.get("time_index"))


def _portfolio_weights_rows(
    context: MarketsRepositoryContext,
    *,
    portfolio_index_identifier: str,
    weights_date: dt.datetime,
) -> list[dict[str, Any]]:
    return _operation_result_rows(
        search_model(
            context,
            model=PortfolioWeightsStorage,
            filters={
                "portfolio_index_identifier": portfolio_index_identifier,
                "time_index": weights_date,
            },
            limit=MAX_PORTFOLIO_SCAN_LIMIT,
        )
    )


def _asset_references_by_unique_identifier(
    context: MarketsRepositoryContext,
    *,
    rows: Sequence[Mapping[str, Any]],
) -> dict[str, dict[str, Any]]:
    unique_identifiers = {
        str(row["asset_identifier"])
        for row in rows
        if row.get("asset_identifier") not in (None, "")
    }
    if not unique_identifiers:
        return {}

    asset_rows = _operation_result_rows(
        search_model(
            context,
            model=AssetTable,
            in_filters={"unique_identifier": sorted(unique_identifiers)},
            limit=MAX_PORTFOLIO_SCAN_LIMIT,
        )
    )
    assets_by_identifier = {
        str(row["unique_identifier"]): row
        for row in asset_rows
        if isinstance(row, Mapping) and row.get("unique_identifier") not in (None, "")
    }
    snapshot_rows = _operation_result_rows(
        search_model(
            context,
            model=AssetSnapshotsStorage,
            in_filters={"asset_identifier": sorted(unique_identifiers)},
            limit=MAX_PORTFOLIO_SCAN_LIMIT,
        )
    )
    snapshots = _latest_asset_snapshots_by_unique_identifier(snapshot_rows)

    references: dict[str, dict[str, Any]] = {}
    for unique_identifier in unique_identifiers:
        asset_row = assets_by_identifier.get(unique_identifier)
        snapshot_row = snapshots.get(unique_identifier)
        references[unique_identifier] = {
            "uid": _string_or_none(asset_row.get("uid")) if asset_row else None,
            "unique_identifier": unique_identifier,
            "current_snapshot": {
                "name": _string_or_none(snapshot_row.get("name")) if snapshot_row else None,
                "ticker": _string_or_none(snapshot_row.get("ticker")) if snapshot_row else None,
            },
        }
    return references


def _latest_asset_snapshots_by_unique_identifier(
    rows: Sequence[Mapping[str, Any]],
) -> dict[str, dict[str, Any]]:
    latest_rows: dict[str, dict[str, Any]] = {}
    latest_times: dict[str, dt.datetime] = {}
    for row in rows:
        if not isinstance(row, Mapping):
            continue
        unique_identifier = _string_or_none(row.get("asset_identifier"))
        snapshot_time = _datetime_or_none(row.get("time_index"))
        if unique_identifier is None or snapshot_time is None:
            continue
        current_time = latest_times.get(unique_identifier)
        if current_time is not None and snapshot_time <= current_time:
            continue
        latest_rows[unique_identifier] = dict(row)
        latest_times[unique_identifier] = snapshot_time
    return latest_rows


def _empty_weights_snapshot(
    *,
    portfolio: Mapping[str, Any],
    portfolio_index_identifier: str | None,
    warning: str | None,
) -> dict[str, Any]:
    return {
        "portfolio_uid": _string_or_none(portfolio.get("uid")),
        "portfolio_unique_identifier": _string_or_none(portfolio.get("unique_identifier")),
        "portfolio_index_uid": _string_or_none(portfolio.get("portfolio_index_uid")),
        "portfolio_index_identifier": portfolio_index_identifier,
        "weights_date": None,
        "resolution_warning": warning,
        "weights": [],
    }


def _build_weight_row(
    *,
    row: Mapping[str, Any],
    asset_reference: dict[str, Any] | None,
    include_asset_detail: bool,
) -> dict[str, Any]:
    return {
        "time_index": _datetime_or_none(row.get("time_index")),
        "portfolio_index_identifier": _string_or_none(row.get("portfolio_index_identifier")),
        "asset_identifier": _string_or_empty(row.get("asset_identifier")),
        "weight": _number_string_or_none(row.get("weight")),
        "weight_before": _number_string_or_none(row.get("weight_before")),
        "price_current": _number_string_or_none(row.get("price_current")),
        "price_before": _number_string_or_none(row.get("price_before")),
        "volume_current": _number_string_or_none(row.get("volume_current")),
        "volume_before": _number_string_or_none(row.get("volume_before")),
        "asset": asset_reference if include_asset_detail else None,
    }


def _build_portfolio_row(row: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "uid": row.get("uid"),
        "unique_identifier": _string_or_empty(row.get("unique_identifier")),
        "calendar_name": _string_or_none(row.get("calendar_name")),
        "calendar_uid": _string_or_none(row.get("calendar_uid")),
        "portfolio_index_uid": _string_or_none(row.get("portfolio_index_uid")),
        "portfolio_weights_data_node_uid": _string_or_none(
            row.get("portfolio_weights_data_node_uid")
        ),
        "signal_weights_data_node_uid": _string_or_none(row.get("signal_weights_data_node_uid")),
        "portfolio_data_node_uid": _string_or_none(row.get("portfolio_data_node_uid")),
        "backtest_table_price_column_name": _string_or_empty(
            row.get("backtest_table_price_column_name")
        )
        or "close",
    }


def _build_portfolio_metadata_row(row: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "uid": row.get("uid"),
        "unique_identifier": _string_or_empty(row.get("unique_identifier")),
        "description": _string_or_none(row.get("description")),
    }


def _operation_result_rows(result: Mapping[str, Any] | list[Any] | None) -> list[dict[str, Any]]:
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
            if key == "row" or "uid" in value:
                return [dict(value)]
        if isinstance(value, list):
            return [row for row in value if isinstance(row, dict)]
    if "uid" in result:
        return [dict(result)]
    return []


def _first_operation_row(result: Mapping[str, Any] | list[Any] | None) -> dict[str, Any] | None:
    rows = _operation_result_rows(result)
    return rows[0] if rows else None


def _count_from_result(result: Mapping[str, Any] | list[Any] | None) -> int:
    row = _first_operation_row(result)
    if row is None:
        return 0
    for key in ("count", "count_1"):
        if key in row:
            return int(row[key] or 0)
    for value in row.values():
        if isinstance(value, int):
            return value
    return 0


def _is_delete_conflict(exc: Exception) -> bool:
    text = str(exc).lower()
    return any(
        marker in text
        for marker in (
            "foreign key",
            "violates",
            "referenced",
            "restrict",
            "constraint",
        )
    )


def _string_or_none(value: Any) -> str | None:
    if value in (None, ""):
        return None
    return str(value)


def _string_or_empty(value: Any) -> str:
    return "" if value in (None, "") else str(value)


def _number_string_or_none(value: Any) -> str | None:
    if value in (None, ""):
        return None
    return str(value)


def _datetime_or_none(value: Any) -> dt.datetime | None:
    if value in (None, ""):
        return None
    if isinstance(value, dt.datetime):
        return value
    return dt.datetime.fromisoformat(str(value).replace("Z", "+00:00"))


__all__ = [
    "PortfolioDeleteConflictError",
    "bulk_delete_portfolio_records",
    "delete_portfolio_record",
    "get_portfolio_detail_response",
    "get_portfolio_frontend_detail_summary",
    "get_portfolio_weights_snapshot_response",
    "list_portfolio_rows_response",
]
