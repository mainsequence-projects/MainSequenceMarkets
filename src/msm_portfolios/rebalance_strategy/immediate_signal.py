import datetime as dt
from typing import Literal

import pandas as pd

from msm.settings import ASSET_IDENTIFIER_DIMENSION
from msm_portfolios.rebalance_strategy.base import (
    RebalanceStrategyBase,
)


class ImmediateSignal(RebalanceStrategyBase):
    timing_mode: Literal["signal_time"] = "signal_time"
    signal_selection: Literal["exact_observation"] = "exact_observation"
    execution_valuation: Literal["latest_at_or_before_event"] = "latest_at_or_before_event"

    def get_explanation(self):
        return (
            "ImmediateSignal: rebalances immediately to the current signal weights. "
            "This is equivalent to using the signal weights directly."
        )

    def execution_timestamps(
        self,
        start: dt.datetime,
        end: dt.datetime,
        *,
        signal_timestamps: pd.DatetimeIndex,
    ) -> pd.DatetimeIndex:
        timestamps = pd.DatetimeIndex(pd.to_datetime(signal_timestamps, utc=True), name="time_index")
        start_ts = pd.Timestamp(start)
        end_ts = pd.Timestamp(end)
        start_ts = start_ts.tz_localize("UTC") if start_ts.tzinfo is None else start_ts.tz_convert("UTC")
        end_ts = end_ts.tz_localize("UTC") if end_ts.tzinfo is None else end_ts.tz_convert("UTC")
        return timestamps[(timestamps >= start_ts) & (timestamps <= end_ts)]

    def apply_rebalance_logic(
        self,
        last_rebalance_weights: pd.DataFrame,
        signal_weights: pd.DataFrame,
        valuations_df: pd.DataFrame,
        valuation_column: str,
        *args,
        **kwargs,
    ) -> pd.DataFrame:
        flat_prices = valuations_df.reset_index()
        prices_df = flat_prices.pivot(
            index="time_index",
            columns=[ASSET_IDENTIFIER_DIMENSION],
            values=valuation_column,
        )
        if "volume" in flat_prices.columns:
            volume_df = flat_prices.pivot(
                index="time_index", columns=[ASSET_IDENTIFIER_DIMENSION], values="volume"
            )
        else:
            volume_df = pd.DataFrame(index=prices_df.index, columns=prices_df.columns)

        if last_rebalance_weights is not None:
            # This strategy emits backtest weights, so include the last observation
            # to calculate before/after execution context.
            volume_df = pd.concat(
                [last_rebalance_weights.unstack()["volume_current"], volume_df], axis=0
            )
            prices_df = pd.concat(
                [last_rebalance_weights.unstack()["price_current"], prices_df], axis=0
            )
            signal_weights = pd.concat(
                [last_rebalance_weights.unstack()["weights_current"], signal_weights], axis=0
            )
        rebalance_weights = pd.concat(
            objs=[
                signal_weights,
                signal_weights.shift(1),
                prices_df,
                prices_df.shift(1),
                volume_df,
                volume_df.shift(1),
            ],
            keys=[
                "weights_current",
                "weights_before",
                "price_current",
                "price_before",
                "volume_current",
                "volume_before",
            ],
            axis=1,
        )

        if last_rebalance_weights is not None:
            rebalance_weights = rebalance_weights[
                rebalance_weights.index
                > last_rebalance_weights.index.get_level_values("time_index")[0]
            ]

        return rebalance_weights
