from __future__ import annotations

import datetime as dt
from typing import Literal

import pandas as pd
from pydantic import Field

from mainsequence.meta_tables import TimeIndexTableRef, TimeIndexTableUpdater
from msm_portfolios.rebalance_strategy.base import RebalanceInputContract
from msm_portfolios.rebalance_strategy.immediate_signal import ImmediateSignal


class CalendarEventSignal(ImmediateSignal):
    """Execute the latest eligible signal at explicitly published calendar events."""

    timing_mode: Literal["calendar_event"] = "calendar_event"
    calendar_events_instance: TimeIndexTableUpdater | TimeIndexTableRef = Field(
        ...,
        description=(
            "Published time-indexed calendar-event dependency. Its observation timestamps "
            "are the unshifted persisted events; the required fields identify calendar, "
            "session, event type, and local session date."
        ),
    )
    calendar_identifier: str = Field(
        ...,
        min_length=1,
        description="Calendar identifier selected from the declared event dependency.",
        examples=["XNYS", "CRYPTO_24_7"],
    )
    session_label: str = Field(
        "regular",
        min_length=1,
        description="Persisted calendar session label eligible for execution.",
    )
    rebalance_event: Literal["market_open", "market_close"] = "market_close"
    event_offset: dt.timedelta = Field(
        default=dt.timedelta(0),
        description="Hash-bearing offset applied to each selected persisted event.",
    )
    rebalance_cadence: Literal["every_session", "weekly"] = "every_session"
    rebalance_weekday: int = Field(
        default=0,
        ge=0,
        le=6,
        description="Local session weekday selected when cadence is weekly.",
    )
    signal_selection: Literal["latest_at_or_before_event"] = "latest_at_or_before_event"

    def declared_dependencies(
        self,
    ) -> dict[str, TimeIndexTableUpdater | TimeIndexTableRef]:
        return {"calendar_events": self.calendar_events_instance}

    def required_input_contract(self) -> dict[str, RebalanceInputContract]:
        return {
            "calendar_events": RebalanceInputContract(
                index_names=(
                    "time_index",
                    "calendar_identifier",
                    "session_label",
                    "event_type",
                ),
                required_columns=("local_date",),
            )
        }

    def target_selection_mode(self) -> Literal["latest_at_or_before"]:
        return "latest_at_or_before"

    def dependency_window(
        self,
        dependency_name: str,
        start: dt.datetime,
        end: dt.datetime,
    ) -> tuple[dt.datetime, dt.datetime]:
        if dependency_name != "calendar_events":
            return super().dependency_window(dependency_name, start, end)
        return start - self.event_offset, end - self.event_offset

    def select_events(
        self,
        start: dt.datetime,
        end: dt.datetime,
        *,
        signal_observations: pd.DataFrame,
        observed_inputs: dict[str, pd.DataFrame],
    ) -> pd.DataFrame:
        del signal_observations
        frame = observed_inputs["calendar_events"].reset_index().copy()
        if frame.empty:
            return pd.DataFrame(columns=["time_index", "event_source"])
        selected = frame[
            (frame["calendar_identifier"].astype(str) == self.calendar_identifier)
            & (frame["session_label"].astype(str) == self.session_label)
            & (frame["event_type"].astype(str) == self.rebalance_event)
        ].copy()
        if self.rebalance_cadence == "weekly":
            local_dates = pd.to_datetime(selected["local_date"]).dt.date
            selected = selected[
                pd.Index(value.weekday() for value in local_dates) == self.rebalance_weekday
            ]
        selected["time_index"] = (
            pd.to_datetime(selected["time_index"], utc=True) + self.event_offset
        )
        start_ts = self._as_utc_timestamp(start)
        end_ts = self._as_utc_timestamp(end)
        selected = selected[
            (selected["time_index"] >= start_ts) & (selected["time_index"] <= end_ts)
        ]
        return pd.DataFrame(
            {
                "time_index": selected["time_index"],
                "event_source": "calendar_events",
            }
        )


__all__ = ["CalendarEventSignal"]
