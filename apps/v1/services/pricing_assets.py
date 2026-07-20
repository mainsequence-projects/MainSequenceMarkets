from __future__ import annotations

import datetime as dt
from typing import Any

from apps.v1.schemas.command_center import (
    TabularFrameFieldResponse,
    TabularFrameResponse,
    TabularFrameSourceResponse,
)


def execute_pricing_asset_operation(
    *,
    asset_uid: str,
    operation: str,
    valuation_date: dt.datetime,
    market_data_set: str | None,
    parameters: dict[str, Any],
) -> dict[str, Any]:
    if market_data_set in (None, ""):
        raise ValueError(f"market_data_set is required for {operation}.")
    _ensure_pricing_runtime()
    return _execute_asset_pricing_operation(
        asset_uid=asset_uid,
        operation=operation,
        valuation_date=valuation_date,
        market_data_set=market_data_set,
        parameters=parameters,
    )


def execute_pricing_asset_cashflows_frame(
    *,
    asset_uid: str,
    valuation_date: dt.datetime,
    market_data_set: str | None,
    parameters: dict[str, Any],
) -> TabularFrameResponse:
    payload = execute_pricing_asset_operation(
        asset_uid=asset_uid,
        operation="cashflows",
        valuation_date=valuation_date,
        market_data_set=market_data_set,
        parameters=parameters,
    )
    rows = _cashflow_rows_by_leg(payload.get("legs", {}))
    columns = _ordered_columns(rows, preferred=["leg", "payment_date", "amount", "rate"])
    return _tabular_frame(
        payload=payload,
        label="Fixed income cashflows",
        columns=columns,
        rows=rows,
        field_types={
            "leg": "string",
            "payment_date": "date",
            "amount": "number",
            "rate": "number",
        },
    )


def execute_pricing_asset_net_cashflows_frame(
    *,
    asset_uid: str,
    valuation_date: dt.datetime,
    market_data_set: str | None,
    parameters: dict[str, Any],
) -> TabularFrameResponse:
    payload = execute_pricing_asset_operation(
        asset_uid=asset_uid,
        operation="net-cashflows",
        valuation_date=valuation_date,
        market_data_set=market_data_set,
        parameters=parameters,
    )
    rows = list(payload.get("cashflows", []))
    columns = _ordered_columns(rows, preferred=["payment_date", "net_cashflow"])
    return _tabular_frame(
        payload=payload,
        label="Fixed income net cashflows",
        columns=columns,
        rows=rows,
        field_types={
            "payment_date": "date",
            "net_cashflow": "number",
        },
    )


def _cashflow_rows_by_leg(legs: Any) -> list[dict[str, Any]]:
    if not isinstance(legs, dict):
        return []

    rows: list[dict[str, Any]] = []
    for leg, leg_rows in legs.items():
        if not isinstance(leg_rows, list):
            continue
        for row in leg_rows:
            if isinstance(row, dict):
                rows.append({"leg": str(leg), **row})
    return rows


def _ordered_columns(rows: list[dict[str, Any]], *, preferred: list[str]) -> list[str]:
    keys = {key for row in rows for key in row}
    ordered = [key for key in preferred if key in keys]
    ordered.extend(sorted(keys.difference(ordered)))
    return ordered


def _tabular_frame(
    *,
    payload: dict[str, Any],
    label: str,
    columns: list[str],
    rows: list[dict[str, Any]],
    field_types: dict[str, str],
) -> TabularFrameResponse:
    return TabularFrameResponse(
        status="ready",
        columns=columns,
        rows=rows,
        fields=[
            TabularFrameFieldResponse(
                key=column,
                label=column.replace("_", " ").title(),
                type=field_types.get(column, "unknown"),
                provenance="manual",
            )
            for column in columns
        ],
        source=TabularFrameSourceResponse(
            kind="api",
            label=label,
            context={
                "asset_uid": str(payload["asset_uid"]),
                "instrument_type": payload["instrument_type"],
                "operation": payload["operation"],
                "valuation_date": payload["valuation_date"],
                "market_data_set": payload.get("market_data_set"),
            },
        ),
    )


def _ensure_pricing_runtime() -> None:
    from apps.v1.runtime_bootstrap import ensure_apps_v1_pricing_runtime

    ensure_apps_v1_pricing_runtime()


def _execute_asset_pricing_operation(**kwargs):
    from msm_pricing.api import execute_asset_pricing_operation

    return execute_asset_pricing_operation(**kwargs)
