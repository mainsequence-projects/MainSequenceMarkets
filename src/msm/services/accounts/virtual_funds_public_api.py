from __future__ import annotations

import datetime as dt
import uuid
from collections.abc import Mapping, Sequence
from decimal import Decimal
from typing import Any, Literal

from sqlalchemy import String, cast, func, or_, select

from msm.data_nodes.accounts.storage import AccountHoldingsStorage
from msm.data_nodes.accounts.virtual_funds.storage import VirtualFundHoldingsStorage
from msm.data_nodes.assets.storage import AssetSnapshotsStorage
from msm.models import (
    AccountHoldingsSetTable,
    AccountTable,
    AssetTable,
    VirtualFundHoldingsSetTable,
    VirtualFundTable,
)
from msm.repositories import MarketsRepositoryContext
from msm.repositories.base import compile_markets_statement, execute_markets_operation
from msm.repositories.crud import get_model_by_uid, search_model

DEFAULT_VIRTUAL_FUND_PAGE_SIZE = 25
MAX_VIRTUAL_FUND_SCAN_LIMIT = 500


def list_virtual_fund_rows_response(
    context: MarketsRepositoryContext,
    *,
    search: str = "",
    account_uid: str | uuid.UUID | None = None,
    portfolio_uid: str | uuid.UUID | None = None,
    limit: int = DEFAULT_VIRTUAL_FUND_PAGE_SIZE,
    offset: int = 0,
) -> dict[str, Any]:
    """Return paginated core VirtualFund rows with a total count."""

    filters = _virtual_fund_filter_args(
        search=search,
        account_uid=account_uid,
        portfolio_uid=portfolio_uid,
    )
    rows = _operation_result_rows(
        _execute_virtual_fund_select(
            context,
            _virtual_fund_select(**filters)
            .order_by(VirtualFundTable.unique_identifier, VirtualFundTable.uid)
            .limit(limit)
            .offset(offset),
        )
    )
    count = _count_from_result(
        _execute_virtual_fund_select(
            context,
            select(func.count().label("count")).select_from(
                _virtual_fund_select(**filters).subquery()
            ),
        )
    )
    return {
        "count": count,
        "results": [_build_virtual_fund_row(row) for row in rows],
    }


def get_virtual_fund_detail_response(
    context: MarketsRepositoryContext,
    *,
    uid: str,
) -> dict[str, Any] | None:
    virtual_fund_row = _get_virtual_fund_row(context, uid=uid)
    if virtual_fund_row is None:
        return None

    virtual_fund = _build_virtual_fund_row(virtual_fund_row)
    virtual_fund_uid = str(virtual_fund["uid"])
    account_uid = str(virtual_fund["account_uid"])
    portfolio_uid = str(virtual_fund["target_portfolio_uid"])
    return {
        "virtual_fund": virtual_fund,
        "tabs": [
            {
                "key": "latest_holdings",
                "label": "Latest Holdings",
                "url": (
                    f"/api/v1/virtualfund/{virtual_fund_uid}/holdings/"
                    "?order=desc&limit=1&include_asset_detail=true"
                ),
            }
        ],
        "links": {
            "summary": f"/api/v1/virtualfund/{virtual_fund_uid}/summary/",
            "latest_holdings": f"/api/v1/virtualfund/{virtual_fund_uid}/holdings/",
            "account": f"/api/v1/account/{account_uid}/summary/",
            "portfolio": f"/api/v1/portfolio/{portfolio_uid}/",
        },
    }


def get_virtual_fund_frontend_detail_summary(
    context: MarketsRepositoryContext,
    *,
    uid: str,
) -> dict[str, Any] | None:
    virtual_fund_row = _get_virtual_fund_row(context, uid=uid)
    if virtual_fund_row is None:
        return None

    virtual_fund = _build_virtual_fund_row(virtual_fund_row)
    virtual_fund_uid = str(virtual_fund["uid"])
    title = str(virtual_fund["unique_identifier"]) or virtual_fund_uid
    return {
        "entity": {
            "id": virtual_fund_uid,
            "type": "virtual_fund",
            "title": title,
        },
        "badges": [],
        "inline_fields": [
            {
                "key": "uid",
                "label": "UID",
                "value": virtual_fund_uid,
                "kind": "code",
            },
            {
                "key": "unique_identifier",
                "label": "Identifier",
                "value": virtual_fund["unique_identifier"],
                "kind": "code",
            },
            {
                "key": "account_uid",
                "label": "Account UID",
                "value": str(virtual_fund["account_uid"]),
                "kind": "code",
            },
            {
                "key": "target_portfolio_uid",
                "label": "Portfolio UID",
                "value": str(virtual_fund["target_portfolio_uid"]),
                "kind": "code",
            },
        ],
        "highlight_fields": [],
        "stats": [],
        "label_management": {
            "labels": [],
            "add_label_url": None,
            "remove_label_url": None,
        },
        "summary_warning": None,
        "extensions": {
            "detail_url": f"/api/v1/virtualfund/{virtual_fund_uid}/",
            "latest_holdings_url": f"/api/v1/virtualfund/{virtual_fund_uid}/holdings/",
            "account_summary_url": f"/api/v1/account/{virtual_fund['account_uid']}/summary/",
            "portfolio_detail_url": f"/api/v1/portfolio/{virtual_fund['target_portfolio_uid']}/",
        },
    }


def get_virtual_fund_holdings_snapshot_response(
    context: MarketsRepositoryContext,
    *,
    uid: str,
    order: Literal["asc", "desc"] = "desc",
    limit: int = 1,
    include_asset_detail: bool = True,
    holdings_date: dt.datetime | None = None,
) -> dict[str, Any] | None:
    if limit != 1:
        raise ValueError("Virtual fund holdings endpoint currently supports limit=1.")

    virtual_fund_row = _get_virtual_fund_row(context, uid=uid)
    if virtual_fund_row is None:
        return None

    virtual_fund = _build_virtual_fund_row(virtual_fund_row)
    snapshot_time = holdings_date or _virtual_fund_holdings_snapshot_time(
        context,
        virtual_fund_uid=uid,
        order=order,
    )
    if snapshot_time is None:
        return _empty_holdings_snapshot(virtual_fund=virtual_fund)

    holdings_set_row = _virtual_fund_holdings_set_row(
        context,
        virtual_fund_uid=uid,
        holdings_date=snapshot_time,
    )
    holding_rows = _virtual_fund_holdings_rows(
        context,
        virtual_fund_uid=uid,
        holdings_date=snapshot_time,
    )
    if not holding_rows:
        return _empty_holdings_snapshot(
            virtual_fund=virtual_fund,
            holdings_set_row=holdings_set_row,
            holdings_date=snapshot_time,
        )

    asset_references = (
        _asset_references_by_unique_identifier(context, rows=holding_rows)
        if include_asset_detail
        else {}
    )
    return {
        "virtual_fund_uid": str(virtual_fund["uid"]),
        "virtual_fund_unique_identifier": str(virtual_fund["unique_identifier"]),
        "holdings_set_uid": _string_or_none(
            holdings_set_row.get("uid")
            if holdings_set_row
            else holding_rows[0].get("virtual_fund_holdings_set_uid")
        ),
        "source_account_holdings_set_uid": _string_or_none(
            holdings_set_row.get("source_account_holdings_set_uid")
            if holdings_set_row
            else holding_rows[0].get("source_account_holdings_set_uid")
        ),
        "holdings_date": snapshot_time,
        "holdings": [
            _build_virtual_fund_holding_row(
                row=row,
                asset_reference=asset_references.get(str(row.get("asset_identifier"))),
                include_asset_detail=include_asset_detail,
            )
            for row in sorted(holding_rows, key=lambda row: str(row.get("asset_identifier", "")))
        ],
    }


def get_account_holdings_by_fund_response(
    context: MarketsRepositoryContext,
    *,
    account_uid: str,
    order: Literal["asc", "desc"] = "desc",
    limit: int = 1,
    include_asset_detail: bool = True,
    holdings_date: dt.datetime | None = None,
) -> dict[str, Any] | None:
    if limit != 1:
        raise ValueError("Account holdings by fund endpoint currently supports limit=1.")
    if order not in {"asc", "desc"}:
        raise ValueError("order must be 'asc' or 'desc'.")

    account_row = _get_account_row(context, uid=account_uid)
    if account_row is None:
        return None

    resolved_account_uid = str(account_row["uid"])
    holdings_set_row = _account_holdings_set_row(
        context,
        account_uid=resolved_account_uid,
        order=order,
        holdings_date=holdings_date,
    )
    if holdings_set_row is None:
        return _empty_account_holdings_by_fund(account_uid=resolved_account_uid)

    source_account_holdings_set_uid = _string_or_none(holdings_set_row.get("uid"))
    if source_account_holdings_set_uid is None:
        return _empty_account_holdings_by_fund(account_uid=resolved_account_uid)

    source_rows = _account_holdings_rows_for_set(
        context,
        account_uid=resolved_account_uid,
        holdings_set_uid=source_account_holdings_set_uid,
    )
    virtual_fund_rows = _virtual_fund_rows_for_account(
        context,
        account_uid=resolved_account_uid,
    )
    virtual_fund_uids = [
        str(row["uid"])
        for row in virtual_fund_rows
        if isinstance(row, Mapping) and row.get("uid") not in (None, "")
    ]
    holdings_set_rows = _virtual_fund_holdings_set_rows_for_source(
        context,
        source_account_holdings_set_uid=source_account_holdings_set_uid,
        virtual_fund_uids=virtual_fund_uids,
    )
    allocation_rows = _virtual_fund_holdings_rows_for_source(
        context,
        source_account_holdings_set_uid=source_account_holdings_set_uid,
        virtual_fund_uids=virtual_fund_uids,
    )
    asset_references = (
        _asset_references_by_unique_identifier(
            context,
            rows=[*source_rows, *allocation_rows],
        )
        if include_asset_detail
        else {}
    )

    return {
        "account_uid": resolved_account_uid,
        "source_account_holdings_set_uid": source_account_holdings_set_uid,
        "holdings_date": _datetime_or_none(holdings_set_row.get("time_index")),
        "funds": _build_account_holdings_by_fund_groups(
            virtual_fund_rows=virtual_fund_rows,
            holdings_set_rows=holdings_set_rows,
            allocation_rows=allocation_rows,
            asset_references=asset_references,
            include_asset_detail=include_asset_detail,
        ),
        "residuals": _build_account_holdings_by_fund_residuals(
            source_rows=source_rows,
            allocation_rows=allocation_rows,
            asset_references=asset_references,
            include_asset_detail=include_asset_detail,
        ),
        "allocation_warnings": _build_account_holdings_by_fund_warnings(
            source_rows=source_rows,
            allocation_rows=allocation_rows,
        ),
    }


def _virtual_fund_filter_args(
    *,
    search: str,
    account_uid: str | uuid.UUID | None,
    portfolio_uid: str | uuid.UUID | None,
) -> dict[str, Any]:
    return {
        "search": search.strip(),
        "account_uid": None if account_uid in (None, "") else account_uid,
        "portfolio_uid": None if portfolio_uid in (None, "") else portfolio_uid,
    }


def _virtual_fund_select(
    *,
    search: str,
    account_uid: str | uuid.UUID | None,
    portfolio_uid: str | uuid.UUID | None,
):
    statement = select(VirtualFundTable)
    if account_uid is not None:
        statement = statement.where(VirtualFundTable.account_uid == account_uid)
    if portfolio_uid is not None:
        statement = statement.where(VirtualFundTable.target_portfolio_uid == portfolio_uid)

    normalized_search = search.strip().lower()
    if normalized_search:
        needle = f"%{normalized_search}%"
        statement = statement.where(
            or_(
                func.lower(cast(VirtualFundTable.uid, String)).like(needle),
                func.lower(VirtualFundTable.unique_identifier).like(needle),
                func.lower(cast(VirtualFundTable.account_uid, String)).like(needle),
                func.lower(cast(VirtualFundTable.target_portfolio_uid, String)).like(needle),
            )
        )
    return statement


def _execute_virtual_fund_select(context: MarketsRepositoryContext, statement) -> dict[str, Any]:
    return execute_markets_operation(
        compile_markets_statement(
            statement,
            context=context,
            operation="select",
            models=[VirtualFundTable],
            access="read",
        ),
        context=context,
    )


def _get_virtual_fund_row(
    context: MarketsRepositoryContext,
    *,
    uid: str,
) -> dict[str, Any] | None:
    return _first_operation_row(get_model_by_uid(context, model=VirtualFundTable, uid=uid))


def _get_account_row(
    context: MarketsRepositoryContext,
    *,
    uid: str,
) -> dict[str, Any] | None:
    return _first_operation_row(get_model_by_uid(context, model=AccountTable, uid=uid))


def _account_holdings_set_row(
    context: MarketsRepositoryContext,
    *,
    account_uid: str,
    order: Literal["asc", "desc"],
    holdings_date: dt.datetime | None,
) -> dict[str, Any] | None:
    rows = _operation_result_rows(
        search_model(
            context,
            model=AccountHoldingsSetTable,
            filters={"account_uid": account_uid},
            limit=MAX_VIRTUAL_FUND_SCAN_LIMIT,
        )
    )
    if holdings_date is not None:
        normalized_date = _datetime_or_none(holdings_date)
        rows = [row for row in rows if _datetime_or_none(row.get("time_index")) == normalized_date]
    rows = sorted(
        rows,
        key=lambda row: (
            _datetime_or_none(row.get("time_index")) or dt.datetime.min.replace(tzinfo=dt.UTC)
        ),
        reverse=order == "desc",
    )
    return rows[0] if rows else None


def _account_holdings_rows_for_set(
    context: MarketsRepositoryContext,
    *,
    account_uid: str,
    holdings_set_uid: str,
) -> list[dict[str, Any]]:
    return _operation_result_rows(
        search_model(
            context,
            model=AccountHoldingsStorage,
            filters={
                "account_uid": account_uid,
                "holdings_set_uid": holdings_set_uid,
            },
            limit=MAX_VIRTUAL_FUND_SCAN_LIMIT,
        )
    )


def _virtual_fund_rows_for_account(
    context: MarketsRepositoryContext,
    *,
    account_uid: str,
) -> list[dict[str, Any]]:
    return _operation_result_rows(
        search_model(
            context,
            model=VirtualFundTable,
            filters={"account_uid": account_uid},
            limit=MAX_VIRTUAL_FUND_SCAN_LIMIT,
        )
    )


def _virtual_fund_holdings_set_rows_for_source(
    context: MarketsRepositoryContext,
    *,
    source_account_holdings_set_uid: str,
    virtual_fund_uids: Sequence[str],
) -> list[dict[str, Any]]:
    if not virtual_fund_uids:
        return []
    return _operation_result_rows(
        search_model(
            context,
            model=VirtualFundHoldingsSetTable,
            filters={"source_account_holdings_set_uid": source_account_holdings_set_uid},
            in_filters={"virtual_fund_uid": sorted(virtual_fund_uids)},
            limit=MAX_VIRTUAL_FUND_SCAN_LIMIT,
        )
    )


def _virtual_fund_holdings_rows_for_source(
    context: MarketsRepositoryContext,
    *,
    source_account_holdings_set_uid: str,
    virtual_fund_uids: Sequence[str],
) -> list[dict[str, Any]]:
    if not virtual_fund_uids:
        return []
    return _operation_result_rows(
        search_model(
            context,
            model=VirtualFundHoldingsStorage,
            filters={"source_account_holdings_set_uid": source_account_holdings_set_uid},
            in_filters={"virtual_fund_uid": sorted(virtual_fund_uids)},
            limit=MAX_VIRTUAL_FUND_SCAN_LIMIT,
        )
    )


def _virtual_fund_holdings_snapshot_time(
    context: MarketsRepositoryContext,
    *,
    virtual_fund_uid: str,
    order: Literal["asc", "desc"],
) -> dt.datetime | None:
    aggregate = (
        func.min(VirtualFundHoldingsSetTable.time_index)
        if order == "asc"
        else func.max(VirtualFundHoldingsSetTable.time_index)
    )
    statement = select(aggregate.label("time_index")).where(
        VirtualFundHoldingsSetTable.virtual_fund_uid == virtual_fund_uid
    )
    result = execute_markets_operation(
        compile_markets_statement(
            statement,
            context=context,
            operation="select",
            models=[VirtualFundHoldingsSetTable],
            access="read",
        ),
        context=context,
    )
    row = _first_operation_row(result)
    if row is None:
        return None
    return _datetime_or_none(row.get("time_index"))


def _virtual_fund_holdings_set_row(
    context: MarketsRepositoryContext,
    *,
    virtual_fund_uid: str,
    holdings_date: dt.datetime,
) -> dict[str, Any] | None:
    rows = _operation_result_rows(
        search_model(
            context,
            model=VirtualFundHoldingsSetTable,
            filters={
                "virtual_fund_uid": virtual_fund_uid,
                "time_index": holdings_date,
            },
            limit=1,
        )
    )
    return rows[0] if rows else None


def _virtual_fund_holdings_rows(
    context: MarketsRepositoryContext,
    *,
    virtual_fund_uid: str,
    holdings_date: dt.datetime,
) -> list[dict[str, Any]]:
    return _operation_result_rows(
        search_model(
            context,
            model=VirtualFundHoldingsStorage,
            filters={
                "virtual_fund_uid": virtual_fund_uid,
                "time_index": holdings_date,
            },
            limit=MAX_VIRTUAL_FUND_SCAN_LIMIT,
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
            limit=MAX_VIRTUAL_FUND_SCAN_LIMIT,
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
            limit=MAX_VIRTUAL_FUND_SCAN_LIMIT,
        )
    )
    snapshots = _latest_asset_snapshots_by_unique_identifier(snapshot_rows)

    references: dict[str, dict[str, Any]] = {}
    for unique_identifier in unique_identifiers:
        asset_row = assets_by_identifier.get(unique_identifier)
        snapshot_row = snapshots.get(unique_identifier)
        references[unique_identifier] = {
            "uid": _string_or_none(asset_row.get("uid")) if asset_row else None,
            "asset_identifier": unique_identifier,
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


def _empty_account_holdings_by_fund(*, account_uid: str) -> dict[str, Any]:
    return {
        "account_uid": account_uid,
        "source_account_holdings_set_uid": None,
        "holdings_date": None,
        "funds": [],
        "residuals": [],
        "allocation_warnings": [],
    }


def _empty_holdings_snapshot(
    *,
    virtual_fund: Mapping[str, Any],
    holdings_set_row: Mapping[str, Any] | None = None,
    holdings_date: dt.datetime | None = None,
) -> dict[str, Any]:
    return {
        "virtual_fund_uid": _string_or_none(virtual_fund.get("uid")),
        "virtual_fund_unique_identifier": _string_or_none(virtual_fund.get("unique_identifier")),
        "holdings_set_uid": _string_or_none(holdings_set_row.get("uid"))
        if holdings_set_row
        else None,
        "source_account_holdings_set_uid": _string_or_none(
            holdings_set_row.get("source_account_holdings_set_uid")
        )
        if holdings_set_row
        else None,
        "holdings_date": holdings_date,
        "holdings": [],
    }


def _build_account_holdings_by_fund_groups(
    *,
    virtual_fund_rows: Sequence[Mapping[str, Any]],
    holdings_set_rows: Sequence[Mapping[str, Any]],
    allocation_rows: Sequence[Mapping[str, Any]],
    asset_references: Mapping[str, dict[str, Any]],
    include_asset_detail: bool,
) -> list[dict[str, Any]]:
    virtual_funds_by_uid = {
        str(row["uid"]): row for row in virtual_fund_rows if row.get("uid") not in (None, "")
    }
    holdings_sets_by_fund_uid = {
        str(row["virtual_fund_uid"]): row
        for row in holdings_set_rows
        if row.get("virtual_fund_uid") not in (None, "")
    }
    allocation_rows_by_fund_uid: dict[str, list[Mapping[str, Any]]] = {}
    for row in allocation_rows:
        virtual_fund_uid = _string_or_none(row.get("virtual_fund_uid"))
        if virtual_fund_uid is None:
            continue
        allocation_rows_by_fund_uid.setdefault(virtual_fund_uid, []).append(row)

    group_uids = sorted(
        set(holdings_sets_by_fund_uid) | set(allocation_rows_by_fund_uid),
        key=lambda uid: str(
            virtual_funds_by_uid.get(uid, {}).get("unique_identifier") or uid
        ).lower(),
    )
    groups: list[dict[str, Any]] = []
    for virtual_fund_uid in group_uids:
        virtual_fund = virtual_funds_by_uid.get(virtual_fund_uid)
        if virtual_fund is None:
            continue
        holdings_set = holdings_sets_by_fund_uid.get(virtual_fund_uid)
        rows = sorted(
            allocation_rows_by_fund_uid.get(virtual_fund_uid, []),
            key=lambda row: str(row.get("asset_identifier", "")).lower(),
        )
        groups.append(
            {
                "virtual_fund_uid": virtual_fund_uid,
                "virtual_fund_unique_identifier": _string_or_none(
                    virtual_fund.get("unique_identifier")
                ),
                "target_portfolio_uid": _string_or_none(virtual_fund.get("target_portfolio_uid")),
                "holdings_set_uid": _string_or_none(
                    holdings_set.get("uid") if holdings_set else None
                )
                or _first_string(rows, "virtual_fund_holdings_set_uid"),
                "holdings": [
                    _build_account_holdings_by_fund_holding_row(
                        row=row,
                        asset_reference=asset_references.get(str(row.get("asset_identifier"))),
                        include_asset_detail=include_asset_detail,
                    )
                    for row in rows
                ],
            }
        )
    return groups


def _build_account_holdings_by_fund_holding_row(
    *,
    row: Mapping[str, Any],
    asset_reference: dict[str, Any] | None,
    include_asset_detail: bool,
) -> dict[str, Any]:
    direction = int(row.get("direction", 1))
    allocated_quantity = _decimal_or_none(row.get("allocated_quantity"))
    signed_quantity = None
    if allocated_quantity is not None:
        signed_quantity = allocated_quantity * Decimal(direction)
    extra_details = dict(row.get("extra_details") or {})
    return {
        "time_index": _datetime_or_none(row.get("time_index")),
        "asset_identifier": _string_or_empty(row.get("asset_identifier")),
        "asset": asset_reference if include_asset_detail else None,
        "quantity": _number_string_or_none(allocated_quantity),
        "direction": direction,
        "signed_quantity": _number_string_or_none(signed_quantity),
        "target_trade_time": _datetime_or_none(row.get("target_trade_time")),
        "extra_details": extra_details,
        "allocation": {
            "target_gap_signed_quantity": _number_string_or_none(
                extra_details.get("target_gap_signed_quantity")
            ),
            "scale": _number_string_or_none(extra_details.get("scale")),
            "target_row_key": _string_or_none(extra_details.get("target_row_key")),
            "position_set_uid": _string_or_none(extra_details.get("position_set_uid")),
        },
    }


def _build_account_holdings_by_fund_residuals(
    *,
    source_rows: Sequence[Mapping[str, Any]],
    allocation_rows: Sequence[Mapping[str, Any]],
    asset_references: Mapping[str, dict[str, Any]],
    include_asset_detail: bool,
) -> list[dict[str, Any]]:
    source_quantities = _signed_quantities_by_asset(source_rows, quantity_field="quantity")
    allocated_quantities = _signed_quantities_by_asset(
        allocation_rows,
        quantity_field="allocated_quantity",
    )
    residuals: list[dict[str, Any]] = []
    for asset_identifier in sorted(set(source_quantities) | set(allocated_quantities)):
        source_quantity = source_quantities.get(asset_identifier, Decimal("0"))
        allocated_quantity = allocated_quantities.get(asset_identifier, Decimal("0"))
        residual_quantity = source_quantity - allocated_quantity
        if residual_quantity == 0:
            continue
        residuals.append(
            {
                "asset_identifier": asset_identifier,
                "source_signed_quantity": _number_string_or_none(source_quantity),
                "allocated_signed_quantity": _number_string_or_none(allocated_quantity),
                "residual_signed_quantity": _number_string_or_none(residual_quantity),
                "asset": asset_references.get(asset_identifier) if include_asset_detail else None,
            }
        )
    return residuals


def _build_account_holdings_by_fund_warnings(
    *,
    source_rows: Sequence[Mapping[str, Any]],
    allocation_rows: Sequence[Mapping[str, Any]],
) -> list[str]:
    source_assets = {
        str(row["asset_identifier"])
        for row in source_rows
        if row.get("asset_identifier") not in (None, "")
    }
    allocated_assets = {
        str(row["asset_identifier"])
        for row in allocation_rows
        if row.get("asset_identifier") not in (None, "")
    }
    return [
        "Virtual-fund allocation references asset_identifier "
        f"{asset_identifier!r} that is not present in the source account holdings set."
        for asset_identifier in sorted(allocated_assets - source_assets)
    ]


def _signed_quantities_by_asset(
    rows: Sequence[Mapping[str, Any]],
    *,
    quantity_field: str,
) -> dict[str, Decimal]:
    quantities: dict[str, Decimal] = {}
    for row in rows:
        asset_identifier = _string_or_none(row.get("asset_identifier"))
        quantity = _decimal_or_none(row.get(quantity_field))
        if asset_identifier is None or quantity is None:
            continue
        direction = int(row.get("direction", 1))
        quantities[asset_identifier] = quantities.get(
            asset_identifier,
            Decimal("0"),
        ) + (quantity * Decimal(direction))
    return quantities


def _build_virtual_fund_holding_row(
    *,
    row: Mapping[str, Any],
    asset_reference: dict[str, Any] | None,
    include_asset_detail: bool,
) -> dict[str, Any]:
    direction = int(row.get("direction", 1))
    allocated_quantity = _decimal_or_none(row.get("allocated_quantity"))
    signed_quantity = None
    if allocated_quantity is not None:
        signed_quantity = allocated_quantity * Decimal(direction)
    return {
        "time_index": _datetime_or_none(row.get("time_index")),
        "asset_identifier": _string_or_empty(row.get("asset_identifier")),
        "virtual_fund_holdings_set_uid": _string_or_none(row.get("virtual_fund_holdings_set_uid")),
        "source_account_holdings_set_uid": _string_or_none(
            row.get("source_account_holdings_set_uid")
        ),
        "quantity": _number_string_or_none(row.get("allocated_quantity")),
        "direction": direction,
        "signed_quantity": _number_string_or_none(signed_quantity),
        "target_trade_time": _datetime_or_none(row.get("target_trade_time")),
        "extra_details": dict(row.get("extra_details") or {}),
        "asset": asset_reference if include_asset_detail else None,
    }


def _first_string(rows: Sequence[Mapping[str, Any]], key: str) -> str | None:
    for row in rows:
        value = _string_or_none(row.get(key))
        if value is not None:
            return value
    return None


def _build_virtual_fund_row(row: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "uid": row.get("uid"),
        "unique_identifier": _string_or_empty(row.get("unique_identifier")),
        "account_uid": _string_or_empty(row.get("account_uid")),
        "target_portfolio_uid": _string_or_empty(row.get("target_portfolio_uid")),
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


def _decimal_or_none(value: Any) -> Decimal | None:
    if value in (None, ""):
        return None
    return Decimal(str(value))


def _datetime_or_none(value: Any) -> dt.datetime | None:
    if value in (None, ""):
        return None
    if isinstance(value, dt.datetime):
        return value
    return dt.datetime.fromisoformat(str(value).replace("Z", "+00:00"))


__all__ = [
    "get_account_holdings_by_fund_response",
    "get_virtual_fund_detail_response",
    "get_virtual_fund_frontend_detail_summary",
    "get_virtual_fund_holdings_snapshot_response",
    "list_virtual_fund_rows_response",
]
