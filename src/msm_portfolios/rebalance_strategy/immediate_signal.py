import datetime as dt
from typing import Any, Literal

import pandas as pd

from msm_portfolios.rebalance_strategy.base import (
    AssetExecution,
    RebalanceStrategyBase,
    RebalanceTarget,
)


class ImmediateSignal(RebalanceStrategyBase):
    timing_mode: Literal["signal_time"] = "signal_time"
    signal_selection: Literal["exact_observation"] = "exact_observation"

    def get_explanation(self):
        return (
            "ImmediateSignal: rebalances immediately to the current signal weights. "
            "This is equivalent to using the signal weights directly."
        )

    def target_selection_mode(self) -> Literal["exact"]:
        return "exact"

    def select_events(
        self,
        start: dt.datetime,
        end: dt.datetime,
        *,
        signal_observations: pd.DataFrame,
        observed_inputs: dict[str, pd.DataFrame],
    ) -> pd.DataFrame:
        del observed_inputs
        if signal_observations is None or signal_observations.empty:
            return pd.DataFrame(columns=["time_index", "event_source"])
        timestamps = pd.DatetimeIndex(
            pd.to_datetime(
                signal_observations.index.get_level_values("time_index"),
                utc=True,
            ),
            name="time_index",
        ).unique()
        start_ts = self._as_utc_timestamp(start)
        end_ts = self._as_utc_timestamp(end)
        timestamps = timestamps[(timestamps >= start_ts) & (timestamps <= end_ts)]
        return pd.DataFrame({"time_index": timestamps, "event_source": "signal_weights"})

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
        del (
            event_time,
            event_source,
            event_observations,
            previous_asset_state,
            new_target,
            execution_context,
        )
        assets = set(current_weights) | set(target.weights)
        return {
            asset: AssetExecution(weight_after=float(target.weights.get(asset, 0.0)))
            for asset in assets
        }
