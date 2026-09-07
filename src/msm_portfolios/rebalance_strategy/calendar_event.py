from __future__ import annotations

import datetime as dt
from dataclasses import replace
from typing import Any, Literal

import pandas as pd
from pydantic import Field, PrivateAttr

from msm_portfolios.rebalance_strategy.immediate_signal import ImmediateSignal
from msm_portfolios.services.calendars import resolve_rebalance_calendar


class CalendarEventSignal(ImmediateSignal):
    """Execute the latest eligible signal at persisted calendar events."""

    timing_mode: Literal["calendar_event"] = "calendar_event"
    calendar_identifier: str = Field(
        "24/7",
        min_length=1,
        description=(
            "Persisted Calendar.unique_identifier or source_identifier used to "
            "resolve sessions."
        ),
    )
    session_label: str = Field(
        "regular",
        min_length=1,
        description="Persisted calendar session label eligible for execution.",
    )
    rebalance_event: Literal["market_open", "market_close"] = "market_close"
    event_offset: dt.timedelta = Field(
        default=dt.timedelta(0),
        description="Offset applied to the selected persisted session event.",
    )
    rebalance_cadence: Literal["every_session", "weekly"] = "every_session"
    rebalance_weekday: int = Field(
        default=0,
        ge=0,
        le=6,
        description="Local session weekday used when rebalance_cadence is weekly.",
    )
    signal_selection: Literal["latest_at_or_before_event"] = "latest_at_or_before_event"
    execution_valuation: Literal["latest_at_or_before_event"] = "latest_at_or_before_event"

    _calendar_obj: Any = PrivateAttr(default=None)

    @property
    def calendar(self) -> Any:
        if self._calendar_obj is None:
            resolved = resolve_rebalance_calendar(self.calendar_identifier)
            if hasattr(resolved, "session_label"):
                resolved = replace(resolved, session_label=self.session_label)
            self._calendar_obj = resolved
        return self._calendar_obj

    def execution_timestamps(
        self,
        start: dt.datetime,
        end: dt.datetime,
        *,
        signal_timestamps: pd.DatetimeIndex,
    ) -> pd.DatetimeIndex:
        del signal_timestamps
        schedule = self.calendar.schedule(start_date=start, end_date=end)
        if schedule.empty:
            return pd.DatetimeIndex([], tz="UTC", name="time_index")

        if self.rebalance_cadence == "weekly":
            local_dates = pd.Index(schedule.index)
            schedule = schedule[[value.weekday() == self.rebalance_weekday for value in local_dates]]

        timestamps = pd.to_datetime(schedule[self.rebalance_event], utc=True)
        timestamps = pd.DatetimeIndex(timestamps + self.event_offset, name="time_index")
        start_ts = pd.Timestamp(start)
        end_ts = pd.Timestamp(end)
        if start_ts.tzinfo is None:
            start_ts = start_ts.tz_localize("UTC")
        else:
            start_ts = start_ts.tz_convert("UTC")
        if end_ts.tzinfo is None:
            end_ts = end_ts.tz_localize("UTC")
        else:
            end_ts = end_ts.tz_convert("UTC")
        return timestamps[(timestamps >= start_ts) & (timestamps <= end_ts)]
