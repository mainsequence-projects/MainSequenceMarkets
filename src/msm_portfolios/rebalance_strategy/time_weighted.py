from __future__ import annotations

import datetime as dt
from typing import Any, Literal

import pandas as pd
from pydantic import Field, field_validator, model_validator

from metatables import TimeIndexTableRef, TimeIndexTableUpdater
from msm.settings import ASSET_IDENTIFIER_DIMENSION
from msm_portfolios.rebalance_strategy.bars import BarStrategy
from msm_portfolios.rebalance_strategy.base import (
    BarSlice,
    RebalanceInputContract,
    dependency_events,
)
from msm_portfolios.rebalance_strategy.execution_policy import RebalanceBook


class TimeWeighted(BarStrategy):
    """Fill each order evenly over the time left in its day's window.

    The order is fixed at the decision (#90). By a bar at ``t`` the order should have
    filled the part of it that the time from its earliest moment to ``t`` is of the time
    from its earliest moment to ``rebalance_end`` that day. Each bar's slice is what is
    still short of that, so an asset that missed bars, halted or short of cash, catches
    up at its next bar; past the window's end the rest fills at the next bar.
    """

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

    def own_execution_prices(self) -> tuple[str, str]:
        return "execution_bars", self.price_column

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
        del event_observations, bar_states, execution_context
        started_at = book.earliest_time_index
        window_end = started_at.normalize() + pd.Timedelta(
            hours=self.rebalance_end.hour,
            minutes=self.rebalance_end.minute,
            seconds=self.rebalance_end.second,
        )
        duration = max((window_end - started_at).total_seconds(), 0.0)
        elapsed = max((event_time - started_at).total_seconds(), 0.0)
        progress = 1.0 if duration == 0 else min(1.0, elapsed / duration)
        slices: dict[str, BarSlice] = {}
        for asset in prices:
            order = book.orders[asset]
            due = abs(order.order_shares or 0.0) * progress - abs(order.filled_shares)
            slices[asset] = BarSlice(
                shares=max(due, 0.0),
                state={"elapsed_fraction": progress},
            )
        return slices


__all__ = ["TimeWeighted"]
