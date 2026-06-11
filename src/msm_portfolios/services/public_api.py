from __future__ import annotations

import datetime as dt
import uuid
from collections.abc import Mapping, Sequence
from typing import Any, Literal

from sqlalchemy import String, cast, delete, func, literal, or_, select

from msm.data_nodes.accounts.constants import TARGET_TYPE_PORTFOLIO
from msm.data_nodes.accounts.storage import TargetPositionsStorage
from msm.data_nodes.assets.storage import AssetSnapshotsStorage
from msm.data_nodes.accounts.virtual_funds.storage import VirtualFundHoldingsStorage
from msm.models import (
    AssetTable,
    CalendarTable,
    PortfolioTable,
    VirtualFundHoldingsSetTable,
    VirtualFundTable,
)
from msm.repositories import MarketsRepositoryContext
from msm.repositories.crud import (
    count_model,
    create_model,
    get_model_by_uid,
    search_model,
    update_model,
)
from msm.repositories.base import compile_markets_statement, execute_markets_operation
from msm_portfolios.data_nodes.portfolios.storage import PortfolioWeightsStorage, PortfoliosStorage
from msm_portfolios.data_nodes.signals.storage import SignalWeightsStorage
from msm_portfolios.models import PortfolioMetadataTable, SignalMetadataTable

DEFAULT_PORTFOLIO_PAGE_SIZE = 50
MAX_PORTFOLIO_SCAN_LIMIT = 500


class PortfolioDeleteConflictError(ValueError):
    """Raised when a portfolio cannot be deleted because protected rows reference it."""


class SignalDeleteConflictError(ValueError):
    """Raised when a signal cannot be deleted because protected rows reference it."""


def list_portfolio_rows_response(
    context: MarketsRepositoryContext,
    *,
    search: str = "",
    calendar_uid: str | uuid.UUID | None = None,
    limit: int = DEFAULT_PORTFOLIO_PAGE_SIZE,
    offset: int = 0,
) -> dict[str, Any]:
    """Return paginated core Portfolio rows with a total count."""

    filters = _portfolio_filter_args(
        search=search,
        calendar_uid=calendar_uid,
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
    calendar_uid = _string_or_none(portfolio.get("calendar_uid"))
    calendar = _get_calendar_row(context, uid=calendar_uid) if calendar_uid is not None else None
    portfolio_uid = str(portfolio["uid"])
    title = str(portfolio["unique_identifier"]) or portfolio_uid
    badges = []
    if portfolio.get("published_index_uid") not in (None, ""):
        published_index_uid = _string_or_none(portfolio.get("published_index_uid"))
        badges.append(
            {
                "key": "published_index",
                "label": "Published Index",
                "tone": "info",
                "link_url": f"/api/v1/index/{published_index_uid}/"
                if published_index_uid
                else None,
            }
        )
    calendar_reference = _portfolio_calendar_reference(portfolio=portfolio, calendar=calendar)
    node_references = _portfolio_node_references(portfolio=portfolio)

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
                "link_url": _string_or_none(calendar_reference.get("detail_url")),
            },
            {
                "key": "published_index_uid",
                "label": "Published Index UID",
                "value": _string_or_none(portfolio.get("published_index_uid")),
                "kind": "code",
                "link_url": f"/api/v1/index/{portfolio.get('published_index_uid')}/"
                if portfolio.get("published_index_uid") not in (None, "")
                else None,
            },
            {
                "key": "portfolio_weights_data_node_uid",
                "label": "Portfolio Weights Node",
                "value": _string_or_none(portfolio.get("portfolio_weights_data_node_uid")),
                "kind": "code",
                "link_url": _string_or_none(node_references["portfolio_weights"].get("url")),
            },
            {
                "key": "signal_weights_data_node_uid",
                "label": "Signal Weights Node",
                "value": _string_or_none(portfolio.get("signal_weights_data_node_uid")),
                "kind": "code",
                "link_url": _string_or_none(node_references["signal_weights"].get("url")),
            },
            {
                "key": "signal_uid",
                "label": "Signal UID",
                "value": _string_or_none(portfolio.get("signal_uid")),
                "kind": "code",
            },
            {
                "key": "portfolio_data_node_uid",
                "label": "Portfolio Values Node",
                "value": _string_or_none(portfolio.get("portfolio_data_node_uid")),
                "kind": "code",
                "link_url": _string_or_none(node_references["portfolio_values"].get("url")),
            },
        ],
        "highlight_fields": [
            {
                "key": "calendar",
                "label": "Calendar",
                "value": calendar_reference["label"],
                "kind": "text",
                "icon": "calendar",
                "link_url": _string_or_none(calendar_reference.get("detail_url")),
            }
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
            "calendar": calendar_reference,
            "nodes": node_references,
            "pointers": {
                "portfolio_weights_data_node_uid": _string_or_none(
                    portfolio.get("portfolio_weights_data_node_uid")
                ),
                "signal_weights_data_node_uid": _string_or_none(
                    portfolio.get("signal_weights_data_node_uid")
                ),
                "signal_uid": _string_or_none(portfolio.get("signal_uid")),
                "portfolio_data_node_uid": _string_or_none(
                    portfolio.get("portfolio_data_node_uid")
                ),
            },
        },
    }


def _portfolio_calendar_reference(
    *,
    portfolio: Mapping[str, Any],
    calendar: Mapping[str, Any] | None,
) -> dict[str, Any]:
    calendar_uid = _string_or_none(portfolio.get("calendar_uid"))
    display_name = _string_or_none(calendar.get("display_name")) if calendar else None
    unique_identifier = _string_or_none(calendar.get("unique_identifier")) if calendar else None
    label = display_name or unique_identifier or calendar_uid
    return {
        "uid": calendar_uid,
        "label": label,
        "display_name": display_name,
        "unique_identifier": unique_identifier,
        "detail_url": f"/api/v1/calendar/{calendar_uid}/" if calendar_uid else None,
        "dates_url": f"/api/v1/calendar/{calendar_uid}/dates/" if calendar_uid else None,
        "sessions_url": f"/api/v1/calendar/{calendar_uid}/sessions/" if calendar_uid else None,
        "events_url": f"/api/v1/calendar/{calendar_uid}/events/" if calendar_uid else None,
    }


def _portfolio_node_references(*, portfolio: Mapping[str, Any]) -> dict[str, Any]:
    portfolio_uid = _string_or_none(portfolio.get("uid"))
    return {
        "portfolio_weights": {
            "uid": _string_or_none(portfolio.get("portfolio_weights_data_node_uid")),
            "label": "Portfolio weights",
            "url": (
                f"/api/v1/portfolio/{portfolio_uid}/weights/"
                "?order=desc&limit=1&include_asset_detail=true"
                if portfolio_uid
                else None
            ),
        },
        "signal_weights": {
            "uid": _string_or_none(portfolio.get("signal_weights_data_node_uid")),
            "signal_uid": _string_or_none(portfolio.get("signal_uid")),
            "label": "Signal weights",
            "url": (
                f"/api/v1/portfolio/{portfolio_uid}/signals_weights/?order=desc&limit=100"
                if portfolio_uid
                else None
            ),
        },
        "portfolio_values": {
            "uid": _string_or_none(portfolio.get("portfolio_data_node_uid")),
            "label": "Portfolio values",
            "url": (
                f"/api/v1/portfolio/{portfolio_uid}/portfolio_values/?order=desc&limit=100"
                if portfolio_uid
                else None
            ),
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
    portfolio_identifier = _string_or_empty(portfolio.get("unique_identifier"))

    snapshot_time = weights_date or _portfolio_weights_snapshot_time(
        context,
        portfolio_identifier=portfolio_identifier,
        order=order,
    )
    if snapshot_time is None:
        return _empty_weights_snapshot(
            portfolio=portfolio,
            portfolio_identifier=portfolio_identifier,
            warning=None,
        )

    weight_rows = _portfolio_weights_rows(
        context,
        portfolio_identifier=portfolio_identifier,
        weights_date=snapshot_time,
    )
    if not weight_rows:
        return _empty_weights_snapshot(
            portfolio=portfolio,
            portfolio_identifier=portfolio_identifier,
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
        "published_index_uid": _string_or_none(portfolio.get("published_index_uid")),
        "portfolio_identifier": portfolio_identifier,
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


def get_portfolio_values_frame_response(
    context: MarketsRepositoryContext,
    *,
    uid: str,
    start_date: dt.datetime | None = None,
    end_date: dt.datetime | None = None,
    order: Literal["asc", "desc"] = "desc",
    limit: int = DEFAULT_PORTFOLIO_PAGE_SIZE,
) -> dict[str, Any] | None:
    """Return portfolio value rows as a Command Center tabular frame payload."""

    portfolio_row = _get_portfolio_row(context, uid=uid)
    if portfolio_row is None:
        return None

    portfolio = _build_portfolio_row(portfolio_row)
    portfolio_identifier = _string_or_empty(portfolio.get("unique_identifier"))
    rows = _portfolio_values_rows(
        context,
        portfolio_identifier=portfolio_identifier,
        start_date=start_date,
        end_date=end_date,
        order=order,
        limit=limit,
    )
    return _tabular_frame_response(
        status="ready",
        columns=[
            "time_index",
            "portfolio_identifier",
            "close",
            "return",
            "calculated_close",
            "close_time",
        ],
        rows=[
            {
                "time_index": _datetime_or_none(row.get("time_index")),
                "portfolio_identifier": _string_or_none(row.get("portfolio_identifier")),
                "close": row.get("close"),
                "return": row.get("return", row.get("return_")),
                "calculated_close": row.get("calculated_close"),
                "close_time": _datetime_or_none(row.get("close_time")),
            }
            for row in rows
        ],
        field_types={
            "time_index": "datetime",
            "portfolio_identifier": "string",
            "close": "number",
            "return": "number",
            "calculated_close": "number",
            "close_time": "datetime",
        },
        source_label="Portfolio values",
        source_context={
            "portfolio_uid": _string_or_none(portfolio.get("uid")),
            "portfolio_identifier": portfolio_identifier,
            "portfolio_data_node_uid": _string_or_none(portfolio.get("portfolio_data_node_uid")),
            "start_date": start_date,
            "end_date": end_date,
            "limit": limit,
            "order": order,
        },
    )


def get_portfolio_signal_weights_frame_response(
    context: MarketsRepositoryContext,
    *,
    uid: str,
    start_date: dt.datetime | None = None,
    end_date: dt.datetime | None = None,
    order: Literal["asc", "desc"] = "desc",
    limit: int = DEFAULT_PORTFOLIO_PAGE_SIZE,
) -> dict[str, Any] | None:
    """Return signal-weight rows as a Command Center tabular frame payload."""

    portfolio_row = _get_portfolio_row(context, uid=uid)
    if portfolio_row is None:
        return None

    portfolio = _build_portfolio_row(portfolio_row)
    data_node_uid = _string_or_none(portfolio.get("signal_weights_data_node_uid"))
    if data_node_uid is None:
        raise ValueError("Portfolio has no signal_weights_data_node_uid configured.")

    signal_uid = _resolve_portfolio_signal_uid(portfolio)
    rows = _portfolio_signal_weight_rows(
        context,
        signal_uid=signal_uid,
        start_date=start_date,
        end_date=end_date,
        order=order,
        limit=limit,
    )
    return _tabular_frame_response(
        status="ready",
        columns=[
            "time_index",
            "signal_uid",
            "asset_identifier",
            "signal_weight",
        ],
        rows=[
            {
                "time_index": _datetime_or_none(row.get("time_index")),
                "signal_uid": _string_or_none(row.get("signal_uid")),
                "asset_identifier": _string_or_none(row.get("asset_identifier")),
                "signal_weight": row.get("signal_weight"),
            }
            for row in rows
        ],
        field_types={
            "time_index": "datetime",
            "signal_uid": "string",
            "asset_identifier": "string",
            "signal_weight": "number",
        },
        source_label="Portfolio signal weights",
        source_context={
            "portfolio_uid": _string_or_none(portfolio.get("uid")),
            "portfolio_identifier": _string_or_none(portfolio.get("unique_identifier")),
            "signal_weights_data_node_uid": data_node_uid,
            "signal_uid": signal_uid,
            "start_date": start_date,
            "end_date": end_date,
            "limit": limit,
            "order": order,
        },
    )


def list_signal_metadata_response(
    context: MarketsRepositoryContext,
    *,
    search: str = "",
    signal_uid: str | None = None,
    limit: int = DEFAULT_PORTFOLIO_PAGE_SIZE,
    offset: int = 0,
) -> dict[str, Any]:
    """Return paginated SignalMetadata rows with a total count."""

    filters = _signal_metadata_filters(signal_uid=signal_uid)
    contains_filters = _signal_metadata_contains_filters(search=search)
    rows = _operation_result_rows(
        search_model(
            context,
            model=SignalMetadataTable,
            filters=filters,
            contains_filters=contains_filters,
            limit=limit,
            offset=offset,
        )
    )
    count = _count_from_result(
        count_model(
            context,
            model=SignalMetadataTable,
            filters=filters,
            contains_filters=contains_filters,
        )
    )
    return {
        "count": count,
        "results": [_build_signal_metadata_row(row) for row in rows],
    }


def get_signal_metadata_response(
    context: MarketsRepositoryContext,
    *,
    uid: str,
) -> dict[str, Any] | None:
    row = _get_signal_metadata_row(context, uid=uid)
    if row is None:
        return None
    return _build_signal_metadata_row(row)


def create_signal_metadata_response(
    context: MarketsRepositoryContext,
    *,
    signal_uid: str,
    signal_description: str | None = None,
) -> dict[str, Any]:
    row = _first_operation_row(
        create_model(
            context,
            model=SignalMetadataTable,
            values={
                "signal_uid": signal_uid,
                "signal_description": signal_description,
            },
        )
    )
    if row is None:
        raise ValueError("Signal metadata creation returned no row.")
    return _build_signal_metadata_row(row)


def update_signal_metadata_response(
    context: MarketsRepositoryContext,
    *,
    uid: str,
    signal_description: str | None = None,
) -> dict[str, Any] | None:
    existing = _get_signal_metadata_row(context, uid=uid)
    if existing is None:
        return None
    if signal_description is None:
        return _build_signal_metadata_row(existing)

    row = _first_operation_row(
        update_model(
            context,
            model=SignalMetadataTable,
            uid=uid,
            values={"signal_description": signal_description},
        )
    )
    if row is None:
        return None
    return _build_signal_metadata_row(row)


def delete_signal_metadata_record(
    context: MarketsRepositoryContext,
    *,
    uid: str,
) -> dict[str, Any] | None:
    existing = _get_signal_metadata_row(context, uid=uid)
    if existing is None:
        return None

    signal = _build_signal_metadata_row(existing)
    signal_metadata_uid = uuid.UUID(str(signal["uid"]))
    signal_uid = _string_or_empty(signal.get("signal_uid"))
    deleted_weights_count = _delete_signal_weight_rows(
        context,
        signal_uid=signal_uid,
        after_date=None,
    )

    try:
        rows = _operation_result_rows(
            execute_markets_operation(
                _compile_delete_signal_metadata_operation(
                    context,
                    signal_metadata_uid=signal_metadata_uid,
                ),
                context=context,
            )
        )
    except Exception as exc:
        if _is_delete_conflict(exc):
            raise SignalDeleteConflictError(
                "Signal metadata is referenced by protected rows and could not be deleted."
            ) from exc
        raise

    if not rows:
        raise SignalDeleteConflictError(
            "Signal metadata deletion was blocked by a concurrent protected reference."
        )

    return {
        "detail": "Signal metadata deleted.",
        "signal_metadata_uid": str(signal_metadata_uid),
        "signal_uid": signal_uid,
        "deleted_count": 1,
        "deleted_weights_count": deleted_weights_count,
    }


def delete_signal_weights(
    context: MarketsRepositoryContext,
    *,
    uid: str,
    weights_date: dt.datetime | None = None,
) -> dict[str, Any] | None:
    existing = _get_signal_metadata_row(context, uid=uid)
    if existing is None:
        return None

    signal = _build_signal_metadata_row(existing)
    signal_metadata_uid = str(signal["uid"])
    signal_uid = _string_or_empty(signal.get("signal_uid"))
    deleted_count = _delete_signal_weight_rows(
        context,
        signal_uid=signal_uid,
        after_date=weights_date,
    )
    return {
        "detail": "Signal weights deleted.",
        "signal_metadata_uid": signal_metadata_uid,
        "signal_uid": signal_uid,
        "weights_date": weights_date,
        "deleted_count": deleted_count,
    }


def delete_portfolio_record(
    context: MarketsRepositoryContext,
    *,
    uid: str,
) -> dict[str, Any] | None:
    existing = _get_portfolio_row(context, uid=uid)
    if existing is None:
        return None

    portfolio = _build_portfolio_row(existing)
    portfolio_uid = uuid.UUID(str(portfolio["uid"]))
    portfolio_identifier = _string_or_empty(portfolio.get("unique_identifier"))

    _raise_if_portfolio_delete_is_blocked(
        context,
        portfolio_uid=portfolio_uid,
    )
    deleted_weights_count = _delete_portfolio_weight_rows(
        context,
        portfolio_identifier=portfolio_identifier,
        after_date=None,
    )
    deleted_values_count = _delete_portfolio_value_rows(
        context,
        portfolio_identifier=portfolio_identifier,
        after_date=None,
    )

    try:
        rows = _operation_result_rows(
            execute_markets_operation(
                _compile_delete_portfolio_operation(
                    context,
                    portfolio_uid=portfolio_uid,
                ),
                context=context,
            )
        )
    except Exception as exc:
        if _is_delete_conflict(exc):
            blockers = _portfolio_delete_blockers(context, portfolio_uid=portfolio_uid)
            if blockers:
                raise PortfolioDeleteConflictError(
                    _format_portfolio_delete_blockers(blockers)
                ) from exc
            raise PortfolioDeleteConflictError(
                "Portfolio deletion was blocked by a database foreign-key reference "
                f"not covered by preflight checks. Backend error: {exc}"
            ) from exc
        raise

    if not rows:
        blockers = _portfolio_delete_blockers(context, portfolio_uid=portfolio_uid)
        if blockers:
            raise PortfolioDeleteConflictError(_format_portfolio_delete_blockers(blockers))
        raise PortfolioDeleteConflictError(
            "Portfolio deletion was blocked by a concurrent protected reference."
        )

    return {
        "detail": "Portfolio deleted.",
        "deleted_count": 1,
        "deleted_weights_count": deleted_weights_count,
        "deleted_values_count": deleted_values_count,
    }


def cascade_delete_portfolio_record(
    context: MarketsRepositoryContext,
    *,
    uid: str,
) -> dict[str, Any] | None:
    existing = _get_portfolio_row(context, uid=uid)
    if existing is None:
        return None

    portfolio = _build_portfolio_row(existing)
    portfolio_uid = uuid.UUID(str(portfolio["uid"]))
    portfolio_identifier = _string_or_empty(portfolio.get("unique_identifier"))
    virtual_fund_uids = _virtual_fund_uids_for_portfolio(context, portfolio_uid=portfolio_uid)
    deleted_virtual_fund_holdings_count = _delete_virtual_fund_holding_rows(
        context,
        virtual_fund_uids=virtual_fund_uids,
    )
    deleted_target_positions_count = _delete_portfolio_target_position_rows(
        context,
        portfolio_uid=portfolio_uid,
    )
    deleted_weights_count = _delete_portfolio_weight_rows(
        context,
        portfolio_identifier=portfolio_identifier,
        after_date=None,
    )
    deleted_values_count = _delete_portfolio_value_rows(
        context,
        portfolio_identifier=portfolio_identifier,
        after_date=None,
    )

    rows = _operation_result_rows(
        execute_markets_operation(
            _compile_cascade_delete_portfolio_operation(
                context,
                portfolio_uid=portfolio_uid,
            ),
            context=context,
        )
    )
    if not rows:
        raise PortfolioDeleteConflictError(
            "Portfolio cascade delete did not delete the portfolio row."
        )

    row = rows[0]
    return {
        "detail": "Portfolio cascade deleted.",
        "deleted_count": 1,
        "deleted_weights_count": deleted_weights_count,
        "deleted_values_count": deleted_values_count,
        "deleted_target_positions_count": deleted_target_positions_count,
        "deleted_virtual_funds_count": _int_or_zero(row.get("deleted_virtual_funds_count")),
        "deleted_virtual_fund_holdings_sets_count": _int_or_zero(
            row.get("deleted_virtual_fund_holdings_sets_count")
        ),
        "deleted_virtual_fund_holdings_count": deleted_virtual_fund_holdings_count,
    }


def delete_portfolio_weights(
    context: MarketsRepositoryContext,
    *,
    uid: str,
    weights_date: dt.datetime | None = None,
) -> dict[str, Any] | None:
    existing = _get_portfolio_row(context, uid=uid)
    if existing is None:
        return None

    portfolio = _build_portfolio_row(existing)
    portfolio_uid = uuid.UUID(str(portfolio["uid"]))
    portfolio_identifier = _string_or_empty(portfolio.get("unique_identifier"))

    deleted_count = _delete_portfolio_weight_rows(
        context,
        portfolio_identifier=portfolio_identifier,
        after_date=weights_date,
    )
    return {
        "detail": "Portfolio weights deleted.",
        "portfolio_uid": str(portfolio_uid),
        "portfolio_identifier": portfolio_identifier,
        "weights_date": weights_date,
        "deleted_count": deleted_count,
    }


def bulk_delete_portfolio_records(
    context: MarketsRepositoryContext,
    *,
    uids: Sequence[str],
) -> dict[str, Any]:
    deleted_count = 0
    deleted_weights_count = 0
    deleted_values_count = 0
    failed: list[dict[str, str]] = []

    for uid in dict.fromkeys(str(value) for value in uids if str(value).strip()):
        try:
            deleted = delete_portfolio_record(context, uid=uid)
        except PortfolioDeleteConflictError as exc:
            failed.append({"uid": uid, "reason": str(exc)})
            continue
        if deleted:
            deleted_count += int(deleted.get("deleted_count", 1))
            deleted_weights_count += _int_or_zero(deleted.get("deleted_weights_count"))
            deleted_values_count += _int_or_zero(deleted.get("deleted_values_count"))
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
        "deleted_weights_count": deleted_weights_count,
        "deleted_values_count": deleted_values_count,
        "failed": failed,
    }


def bulk_cascade_delete_portfolio_records(
    context: MarketsRepositoryContext,
    *,
    uids: Sequence[str],
) -> dict[str, Any]:
    totals = {
        "deleted_count": 0,
        "deleted_weights_count": 0,
        "deleted_values_count": 0,
        "deleted_target_positions_count": 0,
        "deleted_virtual_funds_count": 0,
        "deleted_virtual_fund_holdings_sets_count": 0,
        "deleted_virtual_fund_holdings_count": 0,
    }
    failed: list[dict[str, str]] = []

    for uid in dict.fromkeys(str(value) for value in uids if str(value).strip()):
        try:
            deleted = cascade_delete_portfolio_record(context, uid=uid)
        except PortfolioDeleteConflictError as exc:
            failed.append({"uid": uid, "reason": str(exc)})
            continue
        if deleted:
            for key in totals:
                totals[key] += _int_or_zero(deleted.get(key))
        else:
            failed.append({"uid": uid, "reason": "Portfolio was not found."})

    if failed and totals["deleted_count"]:
        detail = (
            f"Cascade deleted {totals['deleted_count']} "
            f"portfolio{'s' if totals['deleted_count'] != 1 else ''}; "
            f"{len(failed)} portfolio{'s' if len(failed) != 1 else ''} could not be deleted."
        )
    elif failed:
        detail = f"No portfolios were cascade deleted; {len(failed)} portfolio deletion failed."
    else:
        detail = (
            f"Cascade deleted {totals['deleted_count']} "
            f"portfolio{'s' if totals['deleted_count'] != 1 else ''}."
        )

    return {
        "detail": detail,
        **totals,
        "failed": failed,
    }


def _raise_if_portfolio_delete_is_blocked(
    context: MarketsRepositoryContext,
    *,
    portfolio_uid: uuid.UUID,
) -> None:
    blockers = _portfolio_delete_blockers(context, portfolio_uid=portfolio_uid)
    if blockers:
        raise PortfolioDeleteConflictError(_format_portfolio_delete_blockers(blockers))


def _portfolio_delete_blockers(
    context: MarketsRepositoryContext,
    *,
    portfolio_uid: uuid.UUID,
) -> list[str]:
    blockers: list[str] = []
    virtual_fund_count = _virtual_fund_reference_count(context, portfolio_uid=portfolio_uid)
    if virtual_fund_count:
        blockers.append(
            "VirtualFundTable.target_portfolio_uid references this portfolio "
            f"(count={virtual_fund_count}). Delete or retarget those virtual funds first."
        )

    target_position_count = _target_position_reference_count(
        context,
        portfolio_uid=portfolio_uid,
    )
    if target_position_count:
        blockers.append(
            "TargetPositionsStorage.portfolio_uid references this portfolio "
            f"(count={target_position_count}). Delete or retarget account target positions first."
        )
    return blockers


def _format_portfolio_delete_blockers(blockers: Sequence[str]) -> str:
    return "Portfolio delete is blocked. " + " ".join(blockers)


def _virtual_fund_reference_count(
    context: MarketsRepositoryContext,
    *,
    portfolio_uid: uuid.UUID,
) -> int:
    statement = (
        select(func.count().label("count"))
        .select_from(VirtualFundTable)
        .where(VirtualFundTable.target_portfolio_uid == portfolio_uid)
    )
    return _count_from_result(
        execute_markets_operation(
            compile_markets_statement(
                statement,
                context=context,
                operation="select",
                models=[VirtualFundTable],
                access="read",
            ),
            context=context,
        )
    )


def _target_position_reference_count(
    context: MarketsRepositoryContext,
    *,
    portfolio_uid: uuid.UUID,
) -> int:
    statement = (
        select(func.count().label("count"))
        .select_from(TargetPositionsStorage)
        .where(TargetPositionsStorage.portfolio_uid == portfolio_uid)
    )
    return _count_from_result(
        execute_markets_operation(
            compile_markets_statement(
                statement,
                context=context,
                operation="select",
                models=[TargetPositionsStorage],
                access="read",
            ),
            context=context,
        )
    )


def _virtual_fund_uids_for_portfolio(
    context: MarketsRepositoryContext,
    *,
    portfolio_uid: uuid.UUID,
) -> list[uuid.UUID]:
    rows = _operation_result_rows(
        search_model(
            context,
            model=VirtualFundTable,
            filters={"target_portfolio_uid": portfolio_uid},
            limit=MAX_PORTFOLIO_SCAN_LIMIT,
        )
    )
    return [uuid.UUID(str(row["uid"])) for row in rows]


def _delete_signal_weight_rows(
    context: MarketsRepositoryContext,
    *,
    signal_uid: str,
    after_date: dt.datetime | None,
) -> int:
    return _time_index_delete_count(
        _delete_time_index_storage_after_date(
            SignalWeightsStorage,
            after_date=after_date,
            dimension_filters={"signal_uid": [signal_uid]},
            context=context,
        )
    )


def _delete_portfolio_weight_rows(
    context: MarketsRepositoryContext,
    *,
    portfolio_identifier: str,
    after_date: dt.datetime | None,
) -> int:
    return _time_index_delete_count(
        _delete_time_index_storage_after_date(
            PortfolioWeightsStorage,
            after_date=after_date,
            dimension_filters={"portfolio_identifier": [portfolio_identifier]},
            context=context,
        )
    )


def _delete_portfolio_value_rows(
    context: MarketsRepositoryContext,
    *,
    portfolio_identifier: str,
    after_date: dt.datetime | None,
) -> int:
    return _time_index_delete_count(
        _delete_time_index_storage_after_date(
            PortfoliosStorage,
            after_date=after_date,
            dimension_filters={"portfolio_identifier": [portfolio_identifier]},
            context=context,
        )
    )


def _delete_portfolio_target_position_rows(
    context: MarketsRepositoryContext,
    *,
    portfolio_uid: uuid.UUID,
) -> int:
    return _time_index_delete_count(
        _delete_time_index_storage_after_date(
            TargetPositionsStorage,
            after_date=None,
            dimension_filters={
                "target_type": [TARGET_TYPE_PORTFOLIO],
                "target_uid": [str(portfolio_uid)],
            },
            context=context,
        )
    )


def _delete_virtual_fund_holding_rows(
    context: MarketsRepositoryContext,
    *,
    virtual_fund_uids: Sequence[uuid.UUID],
) -> int:
    if not virtual_fund_uids:
        return 0
    return _time_index_delete_count(
        _delete_time_index_storage_after_date(
            VirtualFundHoldingsStorage,
            after_date=None,
            dimension_filters={"virtual_fund_uid": [str(uid) for uid in virtual_fund_uids]},
            context=context,
        )
    )


def _delete_time_index_storage_after_date(
    storage_model: type,
    *,
    after_date: dt.datetime | None,
    dimension_filters: dict[str, list[Any]],
    context: MarketsRepositoryContext,
) -> dict[str, Any]:
    if after_date is None and not dimension_filters:
        raise ValueError("delete_after_date(None) requires a dimension scope.")

    time_index_meta_table = storage_model.get_time_index_meta_table()
    if time_index_meta_table is None:
        raise RuntimeError(
            f"{storage_model.__name__} is not attached to a backend TimeIndexMetaTable. "
            "Run msm_portfolios.start_engine(...) with the required storage models first."
        )

    return time_index_meta_table.delete_after_date(
        after_date,
        dimension_filters=dimension_filters,
        timeout=context.timeout,
    )


def _time_index_delete_count(result: Mapping[str, Any]) -> int:
    return int(result["deleted_count"])


def _compile_delete_signal_metadata_operation(
    context: MarketsRepositoryContext,
    *,
    signal_metadata_uid: uuid.UUID,
):
    statement = (
        delete(SignalMetadataTable)
        .where(SignalMetadataTable.uid == signal_metadata_uid)
        .returning(
            SignalMetadataTable.uid.label("uid"),
            SignalMetadataTable.signal_uid.label("signal_uid"),
        )
    )
    return compile_markets_statement(
        statement,
        context=context,
        operation="delete",
        models=[SignalMetadataTable],
        access="write",
    )


def _compile_delete_portfolio_operation(
    context: MarketsRepositoryContext,
    *,
    portfolio_uid: uuid.UUID,
):
    virtual_fund_reference = (
        select(literal(1))
        .select_from(VirtualFundTable)
        .where(VirtualFundTable.target_portfolio_uid == PortfolioTable.uid)
        .exists()
    )
    target_position_reference = (
        select(literal(1))
        .select_from(TargetPositionsStorage)
        .where(TargetPositionsStorage.portfolio_uid == PortfolioTable.uid)
        .exists()
    )
    portfolio_scope = (
        select(
            PortfolioTable.uid.label("uid"),
        )
        .select_from(PortfolioTable)
        .where(PortfolioTable.uid == portfolio_uid)
        .where(~virtual_fund_reference)
        .where(~target_position_reference)
        .cte("portfolio_scope")
    )
    statement = (
        delete(PortfolioTable)
        .where(PortfolioTable.uid.in_(select(portfolio_scope.c.uid)))
        .returning(
            PortfolioTable.uid.label("uid"),
        )
        .add_cte(portfolio_scope)
    )
    return compile_markets_statement(
        statement,
        context=context,
        operation="delete",
        models=[
            PortfolioTable,
            TargetPositionsStorage,
            VirtualFundTable,
        ],
        access="write",
    )


def _compile_cascade_delete_portfolio_operation(
    context: MarketsRepositoryContext,
    *,
    portfolio_uid: uuid.UUID,
):
    portfolio_scope = (
        select(
            PortfolioTable.uid.label("uid"),
        )
        .select_from(PortfolioTable)
        .where(PortfolioTable.uid == portfolio_uid)
        .cte("portfolio_scope")
    )
    virtual_fund_scope = (
        select(VirtualFundTable.uid.label("uid"))
        .select_from(VirtualFundTable)
        .where(VirtualFundTable.target_portfolio_uid.in_(select(portfolio_scope.c.uid)))
        .cte("virtual_fund_scope")
    )

    deleted_virtual_fund_holdings_sets = (
        delete(VirtualFundHoldingsSetTable)
        .where(VirtualFundHoldingsSetTable.virtual_fund_uid.in_(select(virtual_fund_scope.c.uid)))
        .returning(literal(1).label("deleted_virtual_fund_holdings_set"))
        .cte("deleted_virtual_fund_holdings_sets")
    )
    deleted_virtual_fund_holdings_sets_count = (
        select(func.count()).select_from(deleted_virtual_fund_holdings_sets).scalar_subquery()
    )

    deleted_virtual_funds = (
        delete(VirtualFundTable)
        .where(VirtualFundTable.uid.in_(select(virtual_fund_scope.c.uid)))
        .returning(literal(1).label("deleted_virtual_fund"))
        .cte("deleted_virtual_funds")
    )
    deleted_virtual_funds_count = (
        select(func.count()).select_from(deleted_virtual_funds).scalar_subquery()
    )

    statement = (
        delete(PortfolioTable)
        .where(PortfolioTable.uid.in_(select(portfolio_scope.c.uid)))
        .returning(
            PortfolioTable.uid.label("uid"),
            deleted_virtual_funds_count.label("deleted_virtual_funds_count"),
            deleted_virtual_fund_holdings_sets_count.label(
                "deleted_virtual_fund_holdings_sets_count"
            ),
        )
        .add_cte(portfolio_scope)
        .add_cte(virtual_fund_scope)
        .add_cte(deleted_virtual_fund_holdings_sets)
        .add_cte(deleted_virtual_funds)
    )
    return compile_markets_statement(
        statement,
        context=context,
        operation="delete",
        models=[
            PortfolioTable,
            VirtualFundHoldingsSetTable,
            VirtualFundTable,
        ],
        access="write",
    )


def _portfolio_filter_args(
    *,
    search: str,
    calendar_uid: str | uuid.UUID | None,
) -> dict[str, Any]:
    return {
        "search": search.strip(),
        "calendar_uid": None if calendar_uid in (None, "") else calendar_uid,
    }


def _portfolio_select(
    *,
    search: str,
    calendar_uid: str | uuid.UUID | None,
):
    statement = select(PortfolioTable)
    if calendar_uid is not None:
        statement = statement.where(PortfolioTable.calendar_uid == calendar_uid)

    normalized_search = search.strip().lower()
    if normalized_search:
        needle = f"%{normalized_search}%"
        statement = statement.where(
            or_(
                func.lower(cast(PortfolioTable.uid, String)).like(needle),
                func.lower(PortfolioTable.unique_identifier).like(needle),
                func.lower(cast(PortfolioTable.calendar_uid, String)).like(needle),
                func.lower(cast(PortfolioTable.published_index_uid, String)).like(needle),
                func.lower(PortfolioTable.signal_uid).like(needle),
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


def _get_calendar_row(
    context: MarketsRepositoryContext,
    *,
    uid: str,
) -> dict[str, Any] | None:
    return _first_operation_row(get_model_by_uid(context, model=CalendarTable, uid=uid))


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
    portfolio_identifier: str,
    order: Literal["asc", "desc"],
) -> dt.datetime | None:
    aggregate = (
        func.min(PortfolioWeightsStorage.time_index)
        if order == "asc"
        else func.max(PortfolioWeightsStorage.time_index)
    )
    statement = select(aggregate.label("time_index")).where(
        PortfolioWeightsStorage.portfolio_identifier == portfolio_identifier
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
    portfolio_identifier: str,
    weights_date: dt.datetime,
) -> list[dict[str, Any]]:
    return _operation_result_rows(
        search_model(
            context,
            model=PortfolioWeightsStorage,
            filters={
                "portfolio_identifier": portfolio_identifier,
                "time_index": weights_date,
            },
            limit=MAX_PORTFOLIO_SCAN_LIMIT,
        )
    )


def _portfolio_values_rows(
    context: MarketsRepositoryContext,
    *,
    portfolio_identifier: str,
    start_date: dt.datetime | None,
    end_date: dt.datetime | None,
    order: Literal["asc", "desc"],
    limit: int,
) -> list[dict[str, Any]]:
    statement = select(PortfoliosStorage).where(
        PortfoliosStorage.portfolio_identifier == portfolio_identifier
    )
    statement = _apply_time_range(
        statement,
        time_column=PortfoliosStorage.time_index,
        start_date=start_date,
        end_date=end_date,
    )
    statement = statement.order_by(
        PortfoliosStorage.time_index.asc()
        if order == "asc"
        else PortfoliosStorage.time_index.desc()
    )
    statement = statement.limit(limit)
    return _operation_result_rows(
        execute_markets_operation(
            compile_markets_statement(
                statement,
                context=context,
                operation="select",
                models=[PortfoliosStorage],
                access="read",
            ),
            context=context,
        )
    )


def _portfolio_signal_weight_rows(
    context: MarketsRepositoryContext,
    *,
    signal_uid: str,
    start_date: dt.datetime | None,
    end_date: dt.datetime | None,
    order: Literal["asc", "desc"],
    limit: int,
) -> list[dict[str, Any]]:
    statement = select(SignalWeightsStorage).where(SignalWeightsStorage.signal_uid == signal_uid)
    statement = _apply_time_range(
        statement,
        time_column=SignalWeightsStorage.time_index,
        start_date=start_date,
        end_date=end_date,
    )
    statement = statement.order_by(
        SignalWeightsStorage.time_index.asc()
        if order == "asc"
        else SignalWeightsStorage.time_index.desc()
    )
    statement = statement.limit(limit)
    return _operation_result_rows(
        execute_markets_operation(
            compile_markets_statement(
                statement,
                context=context,
                operation="select",
                models=[SignalWeightsStorage],
                access="read",
            ),
            context=context,
        )
    )


def _apply_time_range(
    statement,
    *,
    time_column,
    start_date: dt.datetime | None,
    end_date: dt.datetime | None,
):
    if start_date is not None:
        statement = statement.where(time_column >= start_date)
    if end_date is not None:
        statement = statement.where(time_column <= end_date)
    return statement


def _resolve_portfolio_signal_uid(
    portfolio: Mapping[str, Any],
) -> str:
    signal_uid = _string_or_none(portfolio.get("signal_uid"))
    if signal_uid is not None:
        return signal_uid

    raise ValueError(
        "Portfolio has no signal_uid configured. Run the portfolio graph with "
        "update_pointers=True so PortfolioTable.signal_uid is populated from "
        "the persisted signal metadata."
    )


def _tabular_frame_response(
    *,
    status: str,
    columns: list[str],
    rows: list[dict[str, Any]],
    field_types: dict[str, str],
    source_label: str,
    source_context: dict[str, Any],
) -> dict[str, Any]:
    return {
        "status": status,
        "columns": columns,
        "rows": rows,
        "fields": [
            {
                "key": column,
                "label": column.replace("_", " ").title(),
                "type": field_types.get(column, "unknown"),
                "provenance": "backend",
            }
            for column in columns
        ],
        "source": {
            "kind": "api",
            "label": source_label,
            "context": source_context,
        },
    }


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
    portfolio_identifier: str | None,
    warning: str | None,
) -> dict[str, Any]:
    return {
        "portfolio_uid": _string_or_none(portfolio.get("uid")),
        "portfolio_unique_identifier": _string_or_none(portfolio.get("unique_identifier")),
        "published_index_uid": _string_or_none(portfolio.get("published_index_uid")),
        "portfolio_identifier": portfolio_identifier,
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
        "portfolio_identifier": _string_or_none(row.get("portfolio_identifier")),
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
        "calendar_uid": _string_or_none(row.get("calendar_uid")),
        "published_index_uid": _string_or_none(row.get("published_index_uid")),
        "portfolio_weights_data_node_uid": _string_or_none(
            row.get("portfolio_weights_data_node_uid")
        ),
        "signal_weights_data_node_uid": _string_or_none(row.get("signal_weights_data_node_uid")),
        "signal_uid": _string_or_none(row.get("signal_uid")),
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


def _get_signal_metadata_row(
    context: MarketsRepositoryContext,
    *,
    uid: str,
) -> dict[str, Any] | None:
    return _first_operation_row(
        get_model_by_uid(
            context,
            model=SignalMetadataTable,
            uid=uid,
        )
    )


def _build_signal_metadata_row(row: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "uid": row.get("uid"),
        "signal_uid": _string_or_empty(row.get("signal_uid")),
        "signal_description": _string_or_none(row.get("signal_description")),
    }


def _signal_metadata_filters(*, signal_uid: str | None) -> dict[str, Any]:
    filters: dict[str, Any] = {}
    if signal_uid not in (None, ""):
        filters["signal_uid"] = signal_uid
    return filters


def _signal_metadata_contains_filters(*, search: str) -> dict[str, str]:
    search_text = search.strip()
    if not search_text:
        return {}
    return {"signal_uid": search_text}


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


def _int_or_zero(value: Any) -> int:
    if value in (None, ""):
        return 0
    return int(value)


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


def _uuid_or_none(value: Any) -> uuid.UUID | None:
    if value in (None, ""):
        return None
    if isinstance(value, uuid.UUID):
        return value
    return uuid.UUID(str(value))


def _datetime_or_none(value: Any) -> dt.datetime | None:
    if value in (None, ""):
        return None
    if isinstance(value, dt.datetime):
        return value
    return dt.datetime.fromisoformat(str(value).replace("Z", "+00:00"))


__all__ = [
    "PortfolioDeleteConflictError",
    "SignalDeleteConflictError",
    "bulk_cascade_delete_portfolio_records",
    "bulk_delete_portfolio_records",
    "cascade_delete_portfolio_record",
    "delete_portfolio_record",
    "delete_portfolio_weights",
    "delete_signal_metadata_record",
    "delete_signal_weights",
    "create_signal_metadata_response",
    "get_portfolio_detail_response",
    "get_portfolio_frontend_detail_summary",
    "get_portfolio_signal_weights_frame_response",
    "get_portfolio_values_frame_response",
    "get_portfolio_weights_snapshot_response",
    "get_signal_metadata_response",
    "list_signal_metadata_response",
    "list_portfolio_rows_response",
    "update_signal_metadata_response",
]
