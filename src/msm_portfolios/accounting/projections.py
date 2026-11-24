"""Deterministic read projections derived only from the canonical ledger."""

from __future__ import annotations

import json

import numpy as np
import pandas as pd

from .reducer import _validate_ledger_record_identities


def project_state(ledger: pd.DataFrame) -> pd.DataFrame:
    """Project end-of-timestamp position, cash, and obligation quantities."""

    flat = ledger.copy().reset_index()
    _validate_ledger_record_identities(flat)
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
        flat["record_kind"].isin({"position_delta", "cash_delta", "cost", "obligation_delta"})
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
    changes["quantity_delta"] = pd.to_numeric(changes["quantity_delta"], errors="raise").astype(
        "float64"
    )

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
        .sort_values(["portfolio_identifier", "event_sequence", "state_identifier"], kind="stable")
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
    _validate_ledger_record_identities(flat)
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
    """Project the portfolio's close, return and stale flag at each ledger time.

    ``close`` is the NAV after the last event at a time over ``initial_nav``, so a
    portfolio starts at 1. ``valuation_stale`` is set when that event's valuation used a
    price or rate past the valuation model's ``maximum_staleness`` (ADR 0058).
    """

    flat = ledger.copy().reset_index()
    _validate_ledger_record_identities(flat)
    columns = ["close", "return", "calculated_close", "close_time", "valuation_stale"]
    summaries = flat[flat["record_kind"] == "valuation_summary"].copy()
    if summaries.empty:
        return _empty(columns, ["time_index", "portfolio_identifier"])
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
    summaries["valuation_stale"] = [
        bool(_payload(value).get("stale_sources")) for value in summaries["extension_payload"]
    ]
    return (
        summaries[["time_index", "portfolio_identifier", *columns]]
        .set_index(["time_index", "portfolio_identifier"])
        .sort_index()
    )


def project_portfolio_weights(ledger: pd.DataFrame) -> pd.DataFrame:
    """Project the weights of the assets the ledger's events changed at each time (ADR 0065).

    An event that changes a position records every held asset's value before and after
    it in its valuation summary. At a time with such events, each asset they changed gets
    a row: ``weight`` is its value over the NAV after the last of them, ``weight_before``
    its value over the NAV before the first, and ``price_current`` the price the last
    event that traded it booked.
    """

    flat = ledger.copy().reset_index()
    _validate_ledger_record_identities(flat)
    columns = ["weight", "weight_before", "price_current"]
    index = ["time_index", "portfolio_identifier", "asset_identifier"]
    if flat.empty:
        return _empty(columns, index)
    deltas = flat[flat["record_kind"] == "position_delta"]
    if deltas.empty:
        return _empty(columns, index)
    summaries = flat[flat["record_kind"] == "valuation_summary"].set_index(
        ["portfolio_identifier", "event_identifier"]
    )
    rows: list[dict] = []
    for (portfolio, time_index), changed in deltas.sort_values(
        ["portfolio_identifier", "event_sequence", "record_sequence"], kind="stable"
    ).groupby(["portfolio_identifier", "time_index"], sort=True):
        events = list(dict.fromkeys(changed["event_identifier"]))
        first = _summary(summaries, portfolio, events[0])
        last = _summary(summaries, portfolio, events[-1])
        before = first["payload"].get("position_values_before", {})
        after = last["payload"]["position_values"]
        prices = changed.groupby(changed["asset_identifier"].astype(str), sort=False)["price"].last()
        for asset in dict.fromkeys(changed["asset_identifier"].astype(str)):
            price = prices.get(asset)
            rows.append(
                {
                    "time_index": time_index,
                    "portfolio_identifier": portfolio,
                    "asset_identifier": asset,
                    "weight": _share(after.get(asset, 0.0), last["nav_after"]),
                    "weight_before": _share(before.get(asset, 0.0), first["nav_before"]),
                    "price_current": None if price is None or pd.isna(price) else float(price),
                }
            )
    return pd.DataFrame(rows).set_index(index)[columns].sort_index()


def _summary(summaries: pd.DataFrame, portfolio: str, event_identifier: str) -> dict:
    """An event's valuation summary: its NAV before and after, and its payload."""
    key = (portfolio, event_identifier)
    if key not in summaries.index:
        raise ValueError(f"Ledger event {event_identifier!r} has no valuation summary.")
    summary = summaries.loc[key]
    payload = _payload(summary["extension_payload"])
    if "position_values" not in payload:
        raise ValueError(
            f"Ledger event {event_identifier!r} changes a position but records no "
            "position values."
        )
    return {
        "nav_before": float(summary["nav_before"]),
        "nav_after": float(summary["nav_after"]),
        "payload": payload,
    }


def _empty(columns: list[str], index: list[str]) -> pd.DataFrame:
    return pd.DataFrame(
        columns=columns,
        index=pd.MultiIndex.from_arrays([[] for _ in index], names=index),
    )


def _share(value: float, nav: float) -> float:
    if not np.isfinite(nav) or nav == 0.0:
        raise ValueError("A weight needs a finite, non-zero NAV.")
    return float(value) / nav


def _payload(value) -> dict:
    if value is None or (not isinstance(value, (str, dict)) and pd.isna(value)):
        return {}
    if isinstance(value, dict):
        return value
    return json.loads(value) if value else {}


__all__ = [
    "project_cash_flows",
    "project_portfolio_values",
    "project_portfolio_weights",
    "project_state",
]
