"""Deterministic read projections derived only from the canonical ledger."""

from __future__ import annotations

import pandas as pd
import numpy as np


def project_state(ledger: pd.DataFrame) -> pd.DataFrame:
    """Project end-of-timestamp position, cash, and obligation quantities."""

    flat = ledger.copy().reset_index()
    columns = [
        "time_index",
        "portfolio_identifier",
        "state_identifier",
        "ledger_state_identifier",
        "originating_event_identifier",
        "state_kind",
        "asset_identifier",
        "balance_role",
        "quantity",
        "quantity_unit",
        "value",
        "valuation_asset_identifier",
        "is_closed",
        "extension_payload",
    ]
    if flat.empty:
        return pd.DataFrame(columns=columns).set_index(columns[:3])

    changes = flat[
        flat["record_kind"].isin(
            {"position_delta", "cash_delta", "cost", "obligation_delta"}
        )
    ].copy()
    if changes.empty:
        return pd.DataFrame(columns=columns).set_index(columns[:3])
    is_position = changes["record_kind"].eq("position_delta")
    is_obligation = changes["record_kind"].eq("obligation_delta")
    changes["state_identifier"] = np.select(
        [is_position, is_obligation],
        [
            changes["position_identifier"].astype("string"),
            changes["obligation_identifier"].astype("string"),
        ],
        default=(
            "cash:"
            + changes["balance_role"].fillna("settled_cash").astype(str)
            + ":"
            + changes["asset_identifier"].astype(str)
        ),
    )
    changes["state_kind"] = np.select(
        [is_position, is_obligation],
        ["position", "obligation"],
        default="cash",
    )
    changes["quantity_delta"] = pd.to_numeric(
        changes["quantity_delta"], errors="raise"
    ).astype("float64")

    event_keys = [
        "time_index",
        "portfolio_identifier",
        "event_sequence",
        "state_identifier",
        "asset_identifier",
        "balance_role",
        "quantity_unit",
        "state_kind",
        "ledger_state_identifier",
        "event_identifier",
    ]
    event_changes = (
        changes.groupby(event_keys, sort=False, dropna=False, as_index=False)["quantity_delta"]
        .sum()
        .sort_values(
            ["portfolio_identifier", "event_sequence", "state_identifier"], kind="stable"
        )
    )
    state_keys = ["portfolio_identifier", "state_identifier"]
    event_changes["quantity"] = event_changes.groupby(state_keys, sort=False)[
        "quantity_delta"
    ].cumsum()
    final_at_time = (
        event_changes.sort_values(
            ["portfolio_identifier", "time_index", "event_sequence"], kind="stable"
        )
        .groupby(["time_index", *state_keys], sort=False, dropna=False)
        .tail(1)
        .copy()
    )
    final_at_time["originating_event_identifier"] = final_at_time["event_identifier"]
    final_at_time["value"] = pd.NA
    final_at_time["valuation_asset_identifier"] = pd.NA
    final_at_time["is_closed"] = np.isclose(
        final_at_time["quantity"].to_numpy(dtype="float64"), 0.0, rtol=0.0, atol=1e-12
    )
    final_at_time["extension_payload"] = pd.NA
    return final_at_time[columns].set_index(columns[:3]).sort_index()


def project_cash_flows(ledger: pd.DataFrame) -> pd.DataFrame:
    """Project completed cash movements; obligations remain outside this view."""

    flat = ledger.copy().reset_index()
    if flat.empty:
        return pd.DataFrame(
            columns=[
                "time_index",
                "portfolio_identifier",
                "cash_flow_identifier",
                "ledger_state_identifier",
                "event_identifier",
                "cash_flow_type",
                "asset_identifier",
                "amount",
                "valuation_amount",
                "valuation_asset_identifier",
            ]
        )
    cash = flat[flat["record_kind"].isin({"cash_delta", "cost"})].copy()
    cash["cash_flow_identifier"] = cash["record_identifier"].astype(str)
    cash["cash_flow_type"] = np.select(
        [
            cash["record_kind"].eq("cost"),
            cash["event_type"].eq("execution"),
            cash["event_type"].eq("settlement"),
            cash["event_type"].eq("opening_state"),
        ],
        ["cost", "trade_consideration", "obligation_settlement", "opening_balance"],
        default=cash["event_type"].astype(str),
    )
    cash["amount"] = cash["quantity_delta"].astype("float64")
    cash["valuation_amount"] = pd.NA
    cash["valuation_asset_identifier"] = pd.NA
    columns = [
        "time_index",
        "portfolio_identifier",
        "cash_flow_identifier",
        "ledger_state_identifier",
        "event_identifier",
        "cash_flow_type",
        "asset_identifier",
        "amount",
        "valuation_amount",
        "valuation_asset_identifier",
    ]
    return cash[columns].set_index(columns[:3]).sort_index()


def project_portfolio_values(ledger: pd.DataFrame, *, initial_nav: float) -> pd.DataFrame:
    """Project normalized portfolio close and linked returns from summary records."""

    flat = ledger.copy().reset_index()
    summaries = flat[flat["record_kind"] == "valuation_summary"].copy()
    if summaries.empty:
        return pd.DataFrame(
            columns=["close", "return", "calculated_close", "close_time"]
        ).rename_axis(index=["time_index", "portfolio_identifier"])
    summaries = (
        summaries.sort_values(
            ["portfolio_identifier", "time_index", "event_sequence"], kind="stable"
        )
        .groupby(["portfolio_identifier", "time_index"], sort=False)
        .tail(1)
    )
    summaries["close"] = summaries["nav_after"].astype("float64") / float(initial_nav)
    summaries["return"] = summaries.groupby("portfolio_identifier", sort=False)[
        "nav_after"
    ].pct_change()
    summaries["calculated_close"] = summaries["close"]
    summaries["close_time"] = summaries["time_index"]
    return (
        summaries[
            [
                "time_index",
                "portfolio_identifier",
                "close",
                "return",
                "calculated_close",
                "close_time",
            ]
        ]
        .set_index(["time_index", "portfolio_identifier"])
        .sort_index()
    )


__all__ = ["project_cash_flows", "project_portfolio_values", "project_state"]
