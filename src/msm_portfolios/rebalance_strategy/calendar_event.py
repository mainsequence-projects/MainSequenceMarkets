from __future__ import annotations

import datetime as dt
from typing import Literal

import pandas as pd
from pydantic import Field

from msm_portfolios.rebalance_strategy.immediate_signal import ImmediateSignal


class CalendarEventSignal(ImmediateSignal):
    """Rebalance to the latest signal at explicitly published calendar events.

    The strategy's moment is each selected open or close, shifted by
    ``event_offset``; its target is the latest signal at or before that moment.
    Each asset then trades at its first observed price at or after the earliest
    moment and strictly after that signal (ADR 0058). The calendar fields, the
    ``calendar_events`` dependency and its checks are inherited from
    ``ImmediateSignal``.
    """

    timing_mode: Literal["calendar_event"] = "calendar_event"
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
