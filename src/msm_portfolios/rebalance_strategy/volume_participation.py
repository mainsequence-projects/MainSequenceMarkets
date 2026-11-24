from __future__ import annotations

import datetime as dt
from typing import Any, Literal

import pandas as pd
from pydantic import Field, field_validator, model_validator

from metatables import TimeIndexTableRef, TimeIndexTableUpdater
from msm.settings import ASSET_IDENTIFIER_DIMENSION
from msm_portfolios.rebalance_strategy.bars import SizedBarStrategy
from msm_portfolios.rebalance_strategy.base import (
    BarSlice,
    RebalanceInputContract,
    dependency_events,
)
from msm_portfolios.rebalance_strategy.execution_policy import RebalanceBook


class VolumeParticipation(SizedBarStrategy):
    """Fill each order in slices of at most a fraction of each bar's observed volume.

    The order is fixed at the decision (#90). A bar's slice is at most
    ``max_percent_volume_in_bar`` of its volume, in shares of the asset, which is that
    quantity divided by the book's unit, the portfolio's initial NAV, in shares of the
    book.
    """

    timing_mode: Literal["bar_participation"] = "bar_participation"
    execution_bars_instance: TimeIndexTableUpdater | TimeIndexTableRef = Field(
        ...,
        description="Asset-indexed observed bars containing price and traded volume.",
    )
    price_column: str = Field(
        default="close",
        min_length=1,
        description="Observed bar field each slice fills at, a close or a mark.",
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

    def own_execution_prices(self) -> tuple[str, str]:
        return "execution_bars", self.price_column

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
        bars = event_observations["execution_bars"]
        bars_by_asset = {
            str(row[ASSET_IDENTIFIER_DIMENSION]): row for row in bars.to_dict(orient="records")
        }
        slices: dict[str, BarSlice] = {}
        for asset in prices:
            value = bars_by_asset.get(asset, {}).get(self.volume_column)
            volume = None if value is None or pd.isna(value) else float(value)
            capacity = (
                0.0
                if volume is None or volume <= 0
                else volume * self.max_percent_volume_in_bar
            )
            slices[asset] = BarSlice(
                shares=self.shares_for_quantity(capacity, book=book),
                observed_volume=volume,
                state={
                    "capacity_quantity": capacity,
                    "participation_limit": self.max_percent_volume_in_bar,
                },
            )
        return slices


__all__ = ["VolumeParticipation"]
