from __future__ import annotations

import datetime as dt
from typing import Any, Literal

import pandas as pd
from pydantic import Field

from mainsequence.meta_tables import TimeIndexTableRef, TimeIndexTableUpdater
from msm.settings import ASSET_IDENTIFIER_DIMENSION
from msm_portfolios.rebalance_strategy.base import (
    AssetExecution,
    RebalanceInputContract,
    RebalanceTarget,
    RebalanceStrategyBase,
    dependency_events,
)


class LiquidityConstrained(RebalanceStrategyBase):
    """Execute target deltas within observed available-liquidity capacity."""

    timing_mode: Literal["liquidity_constrained"] = "liquidity_constrained"
    liquidity_source_instance: TimeIndexTableUpdater | TimeIndexTableRef = Field(
        ...,
        description=("Asset-indexed quote, book, or capacity observations that trigger execution."),
    )
    price_column: str = Field(
        default="mid_price",
        min_length=1,
        description="Observed price used for quantity conversion and execution provenance.",
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
    total_notional: float = Field(
        default=50_000_000,
        gt=0,
        description="Portfolio notional used to translate liquidity capacity into weight.",
    )

    def declared_dependencies(
        self,
    ) -> dict[str, TimeIndexTableUpdater | TimeIndexTableRef]:
        return {"available_liquidity": self.liquidity_source_instance}

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

    def apply_event(
        self,
        *,
        event_time: pd.Timestamp,
        event_source: str,
        event_observations: dict[str, pd.DataFrame],
        target: RebalanceTarget,
        current_weights: dict[str, float],
        previous_asset_state: dict[str, dict],
        new_target: bool,
        execution_context: Any,
    ) -> dict[str, AssetExecution]:
        del event_time, event_source, previous_asset_state, new_target, execution_context
        observations = event_observations["available_liquidity"]
        rows_by_asset = {
            str(row[ASSET_IDENTIFIER_DIMENSION]): row
            for row in observations.to_dict(orient="records")
        }
        executions: dict[str, AssetExecution] = {}
        for asset in sorted(set(current_weights) | set(target.weights)):
            current = float(current_weights.get(asset, 0.0))
            remaining = float(target.weights.get(asset, 0.0)) - current
            row = rows_by_asset.get(asset, {})
            price_value = row.get(self.price_column)
            liquidity_value = row.get(self.available_liquidity_column)
            price = None if pd.isna(price_value) else float(price_value)
            liquidity = None if pd.isna(liquidity_value) else float(liquidity_value)
            if liquidity is None or liquidity <= 0:
                available_notional = 0.0
            elif self.available_liquidity_unit == "notional":
                available_notional = liquidity
            elif price is None or price <= 0:
                available_notional = 0.0
            else:
                available_notional = liquidity * price
            capacity_weight = available_notional * self.max_liquidity_fraction / self.total_notional
            executed_delta = min(abs(remaining), capacity_weight)
            if remaining < 0:
                executed_delta = -executed_delta
            weight_after = current + executed_delta
            executed_notional = abs(executed_delta) * self.total_notional
            executed_quantity = (
                None
                if price is None or price <= 0
                else executed_delta * self.total_notional / price
            )
            executions[asset] = AssetExecution(
                weight_after=weight_after,
                execution_price=price,
                executed_quantity=executed_quantity,
                executed_notional=executed_notional,
                observed_available_liquidity=liquidity,
                strategy_state={
                    "capacity_weight": capacity_weight,
                    "liquidity_fraction": self.max_liquidity_fraction,
                    "liquidity_unit": self.available_liquidity_unit,
                },
            )
        return executions


__all__ = ["LiquidityConstrained"]
