from __future__ import annotations

import datetime as dt
from typing import Any, Literal

import pandas as pd
from pydantic import Field

from metatables import TimeIndexTableRef, TimeIndexTableUpdater
from msm.settings import ASSET_IDENTIFIER_DIMENSION
from msm_portfolios.rebalance_strategy.bars import SizedBarStrategy
from msm_portfolios.rebalance_strategy.base import (
    BarSlice,
    RebalanceInputContract,
    dependency_events,
)
from msm_portfolios.rebalance_strategy.execution_policy import RebalanceBook


class LiquidityConstrained(SizedBarStrategy):
    """Fill each order in slices within each observation's available liquidity.

    The order is fixed at the decision (#90). An observation's slice is at most
    ``max_liquidity_fraction`` of its available liquidity: an amount in the portfolio's
    currency, or a quantity of the asset, turned into shares of the book with the book's
    unit, the portfolio's initial NAV.
    """

    timing_mode: Literal["liquidity_constrained"] = "liquidity_constrained"
    liquidity_source_instance: TimeIndexTableUpdater | TimeIndexTableRef = Field(
        ...,
        description=("Asset-indexed quote, book, or capacity observations that trigger execution."),
    )
    price_column: str = Field(
        default="mid_price",
        min_length=1,
        description="Observed field each slice fills at, a close or a mark.",
    )
    available_liquidity_column: str = Field(
        default="available_notional",
        min_length=1,
        description="Observed field containing executable liquidity capacity.",
    )
    available_liquidity_unit: Literal["notional", "quantity"] = Field(
        default="notional",
        description="Unit of the configured available-liquidity field.",
    )
    max_liquidity_fraction: float = Field(
        default=1.0,
        gt=0,
        le=1,
        description="Maximum fraction of observed liquidity usable at one event.",
    )

    def declared_dependencies(
        self,
    ) -> dict[str, TimeIndexTableUpdater | TimeIndexTableRef]:
        return {"available_liquidity": self.liquidity_source_instance}

    def own_execution_prices(self) -> tuple[str, str]:
        return "available_liquidity", self.price_column

    def required_input_contract(self) -> dict[str, RebalanceInputContract]:
        return {
            "available_liquidity": RebalanceInputContract(
                index_names=("time_index", ASSET_IDENTIFIER_DIMENSION),
                required_columns=(self.price_column, self.available_liquidity_column),
            )
        }

    def select_events(
        self,
        start: dt.datetime,
        end: dt.datetime,
        *,
        signal_observations: pd.DataFrame,
        observed_inputs: dict[str, pd.DataFrame],
    ) -> pd.DataFrame:
        del signal_observations
        events = dependency_events(
            observed_inputs["available_liquidity"],
            source="available_liquidity",
        )
        if events.empty:
            return events
        timestamps = pd.to_datetime(events["time_index"], utc=True)
        start_ts = self._as_utc_timestamp(start)
        end_ts = self._as_utc_timestamp(end)
        return events[(timestamps >= start_ts) & (timestamps <= end_ts)]

    def bar_slices(
        self,
        *,
        event_time: pd.Timestamp,
        event_observations: dict[str, pd.DataFrame],
        book: RebalanceBook,
        prices: dict[str, float],
        bar_states: dict[str, dict[str, Any]],
        execution_context: Any,
    ) -> dict[str, BarSlice]:
        del event_time, bar_states, execution_context
        observations = event_observations["available_liquidity"]
        rows_by_asset = {
            str(row[ASSET_IDENTIFIER_DIMENSION]): row
            for row in observations.to_dict(orient="records")
        }
        slices: dict[str, BarSlice] = {}
        for asset, price in prices.items():
            value = rows_by_asset.get(asset, {}).get(self.available_liquidity_column)
            liquidity = None if value is None or pd.isna(value) else float(value)
            if liquidity is None or liquidity <= 0:
                available_notional = 0.0
            elif self.available_liquidity_unit == "notional":
                available_notional = liquidity
            else:
                available_notional = liquidity * price
            capacity = available_notional * self.max_liquidity_fraction
            slices[asset] = BarSlice(
                shares=self.shares_for_notional(capacity, price, book=book),
                observed_available_liquidity=liquidity,
                state={
                    "capacity_notional": capacity,
                    "liquidity_fraction": self.max_liquidity_fraction,
                    "liquidity_unit": self.available_liquidity_unit,
                },
            )
        return slices


__all__ = ["LiquidityConstrained"]
