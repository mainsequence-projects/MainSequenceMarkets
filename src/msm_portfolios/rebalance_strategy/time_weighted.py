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


class TimeWeighted(RebalanceStrategyBase):
    """Move toward each active target according to elapsed observed bar time."""

    timing_mode: Literal["bar_participation"] = "bar_participation"
    execution_bars_instance: TimeIndexTableUpdater | TimeIndexTableRef = Field(
        ...,
        description="Asset-indexed observed bars that provide eligible execution events.",
    )
    price_column: str = Field(
        default="close",
        min_length=1,
        description="Observed bar field recorded as execution price.",
    )
    rebalance_start: dt.time = Field(
        default=dt.time(9, 0),
        description="UTC start of the daily time-weighted execution window.",
    )
    rebalance_end: dt.time = Field(
        default=dt.time(23, 0),
        description="UTC end of the daily time-weighted execution window.",
    )

    @model_validator(mode="after")
    def _check_time_order(self) -> TimeWeighted:
        if self.rebalance_start >= self.rebalance_end:
            raise ValueError("rebalance_start must be earlier than rebalance_end.")
        return self

    @field_validator("rebalance_start", "rebalance_end", mode="before")
    @classmethod
    def _parse_time(cls, value: object) -> object:
        if isinstance(value, str):
            try:
                return dt.time.fromisoformat(value)
            except ValueError as exc:
                raise ValueError("Expected an HH:MM[:SS] time.") from exc
        return value

    def declared_dependencies(
        self,
    ) -> dict[str, TimeIndexTableUpdater | TimeIndexTableRef]:
        return {"execution_bars": self.execution_bars_instance}

    def required_input_contract(self) -> dict[str, RebalanceInputContract]:
        return {
            "execution_bars": RebalanceInputContract(
                index_names=("time_index", ASSET_IDENTIFIER_DIMENSION),
                required_columns=(self.price_column,),
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
        del event_source, execution_context
        bars = event_observations["execution_bars"]
        bars_by_asset = {
            str(row[ASSET_IDENTIFIER_DIMENSION]): row for row in bars.to_dict(orient="records")
        }
        session_end = event_time.normalize() + pd.Timedelta(
            hours=self.rebalance_end.hour,
            minutes=self.rebalance_end.minute,
            seconds=self.rebalance_end.second,
        )
        executions: dict[str, AssetExecution] = {}
        for asset in sorted(set(current_weights) | set(target.weights)):
            prior = previous_asset_state.get(asset)
            prior_payload = self.parse_strategy_state(prior)
            if (
                new_target
                or str(prior.get("rebalance_intent_id") if prior else "") != target.intent_id
            ):
                target_start_weight = float(current_weights.get(asset, 0.0))
                target_started_at = event_time
            else:
                target_start_weight = float(
                    prior_payload.get("target_start_weight", current_weights.get(asset, 0.0))
                )
                target_started_at = self._as_utc_timestamp(
                    prior_payload.get("target_started_at", event_time)
                )
            duration = max((session_end - target_started_at).total_seconds(), 0.0)
            elapsed = max((event_time - target_started_at).total_seconds(), 0.0)
            progress = 1.0 if duration == 0 else min(1.0, elapsed / duration)
            target_weight = float(target.weights.get(asset, 0.0))
            weight_after = target_start_weight + (target_weight - target_start_weight) * progress
            bar = bars_by_asset.get(asset, {})
            price = bar.get(self.price_column)
            executions[asset] = AssetExecution(
                weight_after=weight_after,
                execution_price=None if pd.isna(price) else float(price),
                strategy_state={
                    "target_start_weight": target_start_weight,
                    "target_started_at": target_started_at.isoformat(),
                    "elapsed_fraction": progress,
                },
            )
        return executions


__all__ = ["TimeWeighted"]
