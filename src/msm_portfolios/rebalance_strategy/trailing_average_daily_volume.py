from __future__ import annotations

import datetime as dt
import math
from dataclasses import dataclass
from typing import Any, Literal
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

import numpy as np
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


@dataclass(frozen=True)
class _TrailingCapacity:
    average_daily_notional: float | None
    history_observations: int


@dataclass(frozen=True)
class _TrailingExecutionContext:
    capacity_by_event_asset: dict[tuple[pd.Timestamp, str], _TrailingCapacity]
    session_date_by_event: dict[pd.Timestamp, str]


class TrailingAverageDailyVolumeParticipation(RebalanceStrategyBase):
    """Cap intraday execution using only completed trailing daily liquidity."""

    timing_mode: Literal["trailing_average_daily_volume_participation"] = (
        "trailing_average_daily_volume_participation"
    )
    daily_liquidity_instance: TimeIndexTableUpdater | TimeIndexTableRef = Field(
        ...,
        description=(
            "Completed asset-indexed daily bars used only to estimate trailing "
            "daily notional capacity."
        ),
    )
    execution_bars_instance: TimeIndexTableUpdater | TimeIndexTableRef = Field(
        ...,
        description=(
            "Asset-indexed intraday bars whose observable price and volume drive "
            "actual execution transitions."
        ),
    )
    daily_vwap_column: str = Field(
        default="vwap",
        min_length=1,
        description=(
            "Historical completed-daily VWAP field used with daily volume to estimate "
            "notional capacity; it is never used as an execution price."
        ),
    )
    daily_volume_column: str = Field(
        default="volume",
        min_length=1,
        description="Historical completed-daily quantity-volume field.",
    )
    execution_price_column: str = Field(
        default="close",
        min_length=1,
        description="Observable intraday bar price used for simulated execution.",
    )
    execution_volume_column: str = Field(
        default="volume",
        min_length=1,
        description="Observable intraday quantity volume used for the per-bar cap.",
    )
    lookback_observations: int = Field(
        default=20,
        ge=1,
        description="Number of completed daily observations in the trailing average.",
    )
    minimum_history_observations: int | None = Field(
        default=None,
        ge=1,
        description=(
            "Minimum completed daily observations required before trading. None "
            "requires the full lookback window."
        ),
    )
    history_lookback_days: int = Field(
        default=60,
        ge=1,
        description=(
            "Bounded calendar-day read horizon used to obtain the trailing daily "
            "observations, including weekends and holidays."
        ),
    )
    session_timezone: str = Field(
        default="UTC",
        min_length=1,
        description="IANA timezone used to assign intraday events to execution sessions.",
    )
    execution_start: dt.time = Field(
        default=dt.time(9, 0),
        description="Session-local start of the intraday execution window.",
    )
    execution_end: dt.time = Field(
        default=dt.time(23, 0),
        description="Session-local end of the intraday execution window.",
    )
    max_daily_participation: float = Field(
        default=0.05,
        gt=0,
        le=1,
        description=(
            "Maximum fraction of trailing average daily notional executable per asset and session."
        ),
    )
    max_bar_participation: float = Field(
        default=0.10,
        gt=0,
        le=1,
        description="Maximum fraction of the current observed intraday bar volume.",
    )
    total_notional: float = Field(
        default=50_000_000,
        gt=0,
        description="Portfolio notional used to translate target weights into notional.",
    )

    @field_validator("execution_start", "execution_end", mode="before")
    @classmethod
    def _parse_time(cls, value: object) -> object:
        if isinstance(value, str):
            try:
                return dt.time.fromisoformat(value)
            except ValueError as exc:
                raise ValueError("Expected an HH:MM[:SS] time.") from exc
        return value

    @field_validator("session_timezone")
    @classmethod
    def _validate_timezone(cls, value: str) -> str:
        try:
            ZoneInfo(value)
        except ZoneInfoNotFoundError as exc:
            raise ValueError(f"Unknown IANA timezone: {value!r}.") from exc
        return value

    @model_validator(mode="after")
    def _validate_windows(self) -> TrailingAverageDailyVolumeParticipation:
        if self.execution_start >= self.execution_end:
            raise ValueError("execution_start must be earlier than execution_end.")
        minimum = self._minimum_history()
        if minimum > self.lookback_observations:
            raise ValueError("minimum_history_observations cannot exceed lookback_observations.")
        if self.history_lookback_days < self.lookback_observations:
            raise ValueError("history_lookback_days cannot be shorter than lookback_observations.")
        return self

    def get_explanation(self) -> str:
        return (
            "TrailingAverageDailyVolumeParticipation: completed historical daily "
            "VWAP times volume estimates a bounded daily capacity; observable intraday "
            "bar prices and volumes determine each actual execution."
        )

    def declared_dependencies(
        self,
    ) -> dict[str, TimeIndexTableUpdater | TimeIndexTableRef]:
        return {
            "daily_liquidity": self.daily_liquidity_instance,
            "execution_bars": self.execution_bars_instance,
        }

    def required_input_contract(self) -> dict[str, RebalanceInputContract]:
        return {
            "daily_liquidity": RebalanceInputContract(
                index_names=("time_index", ASSET_IDENTIFIER_DIMENSION),
                required_columns=(self.daily_vwap_column, self.daily_volume_column),
            ),
            "execution_bars": RebalanceInputContract(
                index_names=("time_index", ASSET_IDENTIFIER_DIMENSION),
                required_columns=(self.execution_price_column, self.execution_volume_column),
            ),
        }

    def dependency_window(
        self,
        dependency_name: str,
        start: dt.datetime,
        end: dt.datetime,
    ) -> tuple[dt.datetime, dt.datetime]:
        if dependency_name == "daily_liquidity":
            return start - dt.timedelta(days=self.history_lookback_days), end
        return super().dependency_window(dependency_name, start, end)

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
        timestamps = pd.DatetimeIndex(pd.to_datetime(events["time_index"], utc=True))
        local_timestamps = timestamps.tz_convert(self.session_timezone)
        in_window = pd.Series(
            [
                self.execution_start <= timestamp.time() <= self.execution_end
                for timestamp in local_timestamps
            ],
            index=events.index,
        )
        start_ts = self._as_utc_timestamp(start)
        end_ts = self._as_utc_timestamp(end)
        return events[in_window & (timestamps >= start_ts) & (timestamps <= end_ts)]

    def prepare_execution_context(
        self,
        *,
        events: pd.DataFrame,
        observed_inputs: dict[str, pd.DataFrame],
    ) -> _TrailingExecutionContext:
        event_times = pd.DatetimeIndex(pd.to_datetime(events["time_index"], utc=True))
        session_dates = {
            self._as_utc_timestamp(timestamp): timestamp.tz_convert(self.session_timezone)
            .date()
            .isoformat()
            for timestamp in event_times
        }
        execution = self._validated_execution_bars(observed_inputs["execution_bars"])
        daily = self._daily_capacity_frame(observed_inputs["daily_liquidity"])
        capacities: dict[tuple[pd.Timestamp, str], _TrailingCapacity] = {}
        event_time_set = set(session_dates)
        execution = execution[execution["time_index"].isin(event_time_set)]

        daily_groups = {
            str(asset): group.sort_values("time_index", kind="stable")
            for asset, group in daily.groupby(ASSET_IDENTIFIER_DIMENSION, sort=False)
        }
        for asset, asset_events in execution.groupby(ASSET_IDENTIFIER_DIMENSION, sort=False):
            asset_key = str(asset)
            history = daily_groups.get(asset_key)
            ordered_events = pd.DatetimeIndex(
                pd.to_datetime(asset_events["time_index"], utc=True).unique()
            ).sort_values()
            if history is None or history.empty:
                for event_time in ordered_events:
                    capacities[(self._as_utc_timestamp(event_time), asset_key)] = _TrailingCapacity(
                        None, 0
                    )
                continue

            history_times = pd.DatetimeIndex(history["time_index"])
            averages = history["trailing_average_daily_notional"].tolist()
            counts = history["history_observations"].astype(int).tolist()
            history_index = -1
            for event_time in ordered_events:
                event_time = self._as_utc_timestamp(event_time)
                cutoff = self._session_start(session_dates[event_time])
                while (
                    history_index + 1 < len(history_times)
                    and history_times[history_index + 1] < cutoff
                ):
                    history_index += 1
                if history_index < 0 or pd.isna(averages[history_index]):
                    capacity = _TrailingCapacity(
                        None,
                        0 if history_index < 0 else counts[history_index],
                    )
                else:
                    capacity = _TrailingCapacity(
                        float(averages[history_index]),
                        counts[history_index],
                    )
                capacities[(event_time, asset_key)] = capacity

        return _TrailingExecutionContext(
            capacity_by_event_asset=capacities,
            session_date_by_event=session_dates,
        )

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
        del event_source, new_target
        if not isinstance(execution_context, _TrailingExecutionContext):
            raise TypeError("Trailing execution context was not prepared.")
        session_date = execution_context.session_date_by_event[event_time]
        capacities = execution_context.capacity_by_event_asset
        bars = event_observations["execution_bars"]
        bars_by_asset = {
            str(row[ASSET_IDENTIFIER_DIMENSION]): row for row in bars.to_dict(orient="records")
        }
        executions: dict[str, AssetExecution] = {}

        for asset in sorted(set(current_weights) | set(target.weights)):
            current = float(current_weights.get(asset, 0.0))
            remaining_weight = float(target.weights.get(asset, 0.0)) - current
            prior_state = self.parse_strategy_state(previous_asset_state.get(asset))
            consumed = (
                float(prior_state.get("daily_notional_consumed", 0.0))
                if prior_state.get("session_date") == session_date
                else 0.0
            )

            bar = bars_by_asset.get(asset, {})
            price_value = bar.get(self.execution_price_column)
            volume_value = bar.get(self.execution_volume_column)
            price = None if price_value is None or pd.isna(price_value) else float(price_value)
            volume = None if volume_value is None or pd.isna(volume_value) else float(volume_value)
            facts = capacities.get((event_time, asset), _TrailingCapacity(None, 0))
            daily_limit = (
                None
                if facts.average_daily_notional is None
                else facts.average_daily_notional * self.max_daily_participation
            )
            daily_remaining = 0.0 if daily_limit is None else max(daily_limit - consumed, 0.0)
            bar_limit = (
                0.0
                if price is None or volume is None
                else price * volume * self.max_bar_participation
            )
            remaining_notional = abs(remaining_weight) * self.total_notional
            executed_notional = min(remaining_notional, daily_remaining, bar_limit)
            executed_delta = executed_notional / self.total_notional
            if remaining_weight < 0:
                executed_delta = -executed_delta
            weight_after = current + executed_delta
            consumed_after = consumed + executed_notional
            quantity = None if price is None else executed_delta * self.total_notional / price

            executions[asset] = AssetExecution(
                weight_after=weight_after,
                execution_price=price,
                executed_quantity=quantity,
                executed_notional=executed_notional,
                observed_volume=volume,
                strategy_state={
                    "session_date": session_date,
                    "history_observations": facts.history_observations,
                    "trailing_average_daily_notional": facts.average_daily_notional,
                    "daily_notional_limit": daily_limit,
                    "daily_notional_consumed": consumed_after,
                    "daily_notional_remaining": (
                        None if daily_limit is None else max(daily_limit - consumed_after, 0.0)
                    ),
                    "bar_notional_limit": bar_limit,
                    "daily_participation_limit": self.max_daily_participation,
                    "bar_participation_limit": self.max_bar_participation,
                },
            )
        return executions

    def _minimum_history(self) -> int:
        return (
            self.lookback_observations
            if self.minimum_history_observations is None
            else self.minimum_history_observations
        )

    def _session_start(self, session_date: str) -> pd.Timestamp:
        local_midnight = pd.Timestamp(session_date, tz=self.session_timezone)
        local_start = local_midnight + pd.Timedelta(
            hours=self.execution_start.hour,
            minutes=self.execution_start.minute,
            seconds=self.execution_start.second,
            microseconds=self.execution_start.microsecond,
        )
        return local_start.tz_convert("UTC")

    def _validated_execution_bars(self, frame: pd.DataFrame) -> pd.DataFrame:
        if frame is None or frame.empty:
            return pd.DataFrame(
                columns=[
                    "time_index",
                    ASSET_IDENTIFIER_DIMENSION,
                    self.execution_price_column,
                    self.execution_volume_column,
                ]
            )
        flat = frame.reset_index().copy()
        flat["time_index"] = pd.to_datetime(flat["time_index"], utc=True)
        flat[ASSET_IDENTIFIER_DIMENSION] = flat[ASSET_IDENTIFIER_DIMENSION].map(str)
        price = pd.to_numeric(flat[self.execution_price_column], errors="coerce")
        volume = pd.to_numeric(flat[self.execution_volume_column], errors="coerce")
        invalid_price = ~np.isfinite(price) | (price <= 0)
        invalid_volume = ~np.isfinite(volume) | (volume < 0)
        if invalid_price.any() or invalid_volume.any():
            raise ValueError(
                "Execution bars require finite positive prices and finite non-negative volumes."
            )
        flat[self.execution_price_column] = price.astype(float)
        flat[self.execution_volume_column] = volume.astype(float)
        return flat

    def _daily_capacity_frame(self, frame: pd.DataFrame) -> pd.DataFrame:
        if frame is None or frame.empty:
            return pd.DataFrame(
                columns=[
                    "time_index",
                    ASSET_IDENTIFIER_DIMENSION,
                    "trailing_average_daily_notional",
                    "history_observations",
                ]
            )
        flat = frame.reset_index().copy()
        flat["time_index"] = pd.to_datetime(flat["time_index"], utc=True)
        flat[ASSET_IDENTIFIER_DIMENSION] = flat[ASSET_IDENTIFIER_DIMENSION].map(str)
        vwap = pd.to_numeric(flat[self.daily_vwap_column], errors="coerce")
        volume = pd.to_numeric(flat[self.daily_volume_column], errors="coerce")
        invalid_vwap = ~np.isfinite(vwap) | (vwap <= 0)
        invalid_volume = ~np.isfinite(volume) | (volume < 0)
        if invalid_vwap.any() or invalid_volume.any():
            raise ValueError(
                "Daily liquidity bars require finite positive VWAP and finite non-negative volume."
            )
        flat["daily_notional"] = vwap.astype(float) * volume.astype(float)
        flat = flat.sort_values(
            [ASSET_IDENTIFIER_DIMENSION, "time_index"],
            kind="stable",
        ).reset_index(drop=True)
        grouped = flat.groupby(ASSET_IDENTIFIER_DIMENSION, sort=False)["daily_notional"]
        rolling = grouped.rolling(
            window=self.lookback_observations,
            min_periods=self._minimum_history(),
        )
        flat["trailing_average_daily_notional"] = (
            rolling.mean().reset_index(level=0, drop=True).sort_index()
        )
        flat["history_observations"] = (
            flat.groupby(ASSET_IDENTIFIER_DIMENSION, sort=False).cumcount() + 1
        ).clip(upper=self.lookback_observations)
        if not all(math.isfinite(value) for value in flat["daily_notional"].astype(float).tolist()):
            raise ValueError("Daily notional capacity must be finite.")
        return flat


__all__ = ["TrailingAverageDailyVolumeParticipation"]
