from __future__ import annotations

import datetime as dt
from typing import Any, Literal

import pandas as pd
from pydantic import Field, field_validator, model_validator

from mainsequence.meta_tables import TimeIndexTableRef, TimeIndexTableUpdater
from msm.settings import ASSET_IDENTIFIER_DIMENSION
from msm_portfolios.rebalance_strategy.base import (
    AssetExecution,
    RebalanceInputContract,
    RebalanceTarget,
    RebalanceStrategyBase,
    dependency_events,
)


class VolumeParticipation(RebalanceStrategyBase):
    """Execute target deltas without exceeding a configured fraction of observed bar volume."""

    timing_mode: Literal["bar_participation"] = "bar_participation"
    execution_bars_instance: TimeIndexTableUpdater | TimeIndexTableRef = Field(
        ...,
        description="Asset-indexed observed bars containing price and traded volume.",
    )
    price_column: str = Field(
        default="close",
        min_length=1,
        description="Observed price field used to convert bar volume to notional capacity.",
    )
    volume_column: str = Field(
        default="volume",
        min_length=1,
        description="Observed quantity-volume field used to cap execution.",
    )
    rebalance_start: dt.time = Field(
        default=dt.time(9, 0),
        description="UTC start of the daily participation window.",
    )
    rebalance_end: dt.time = Field(
        default=dt.time(23, 0),
        description="UTC end of the daily participation window.",
    )
    max_percent_volume_in_bar: float = Field(
        default=0.01,
        gt=0,
        le=1,
        description="Maximum fraction of observed quantity volume executable in one bar.",
    )
    total_notional: float = Field(
        default=50_000_000,
        gt=0,
        description="Portfolio notional used to translate execution capacity into weight.",
    )

    @field_validator("rebalance_start", "rebalance_end", mode="before")
    @classmethod
    def _parse_time(cls, value: object) -> object:
        if isinstance(value, str):
            try:
                return dt.time.fromisoformat(value)
            except ValueError as exc:
                raise ValueError("Expected an HH:MM[:SS] time.") from exc
        return value

    @model_validator(mode="after")
    def _check_time_order(self) -> VolumeParticipation:
        if self.rebalance_start >= self.rebalance_end:
            raise ValueError("rebalance_start must be earlier than rebalance_end.")
        return self

    def declared_dependencies(
        self,
    ) -> dict[str, TimeIndexTableUpdater | TimeIndexTableRef]:
        return {"execution_bars": self.execution_bars_instance}

    def required_input_contract(self) -> dict[str, RebalanceInputContract]:
        return {
            "execution_bars": RebalanceInputContract(
                index_names=("time_index", ASSET_IDENTIFIER_DIMENSION),
                required_columns=(self.price_column, self.volume_column),
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
        events = dependency_events(observed_inputs["execution_bars"], source="execution_bars")
        if events.empty:
            return events
        timestamps = pd.to_datetime(events["time_index"], utc=True)
        in_window = pd.Series(
            [
                self.rebalance_start <= timestamp.time() <= self.rebalance_end
                for timestamp in timestamps
            ],
            index=events.index,
        )
        start_ts = self._as_utc_timestamp(start)
        end_ts = self._as_utc_timestamp(end)
        return events[in_window & (timestamps >= start_ts) & (timestamps <= end_ts)]

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
        bars = event_observations["execution_bars"]
        bars_by_asset = {
            str(row[ASSET_IDENTIFIER_DIMENSION]): row for row in bars.to_dict(orient="records")
        }
        executions: dict[str, AssetExecution] = {}
        for asset in sorted(set(current_weights) | set(target.weights)):
            current = float(current_weights.get(asset, 0.0))
            remaining = float(target.weights.get(asset, 0.0)) - current
            bar = bars_by_asset.get(asset, {})
            price_value = bar.get(self.price_column)
            volume_value = bar.get(self.volume_column)
            price = None if pd.isna(price_value) else float(price_value)
            volume = None if pd.isna(volume_value) else float(volume_value)
            capacity_weight = (
                0.0
                if price is None or volume is None or price <= 0 or volume <= 0
                else price * volume * self.max_percent_volume_in_bar / self.total_notional
            )
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
                observed_volume=volume,
                strategy_state={
                    "capacity_weight": capacity_weight,
                    "participation_limit": self.max_percent_volume_in_bar,
                },
            )
        return executions


__all__ = ["VolumeParticipation"]
