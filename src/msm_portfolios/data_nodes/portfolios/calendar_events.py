"""Published persisted-calendar events for rebalance strategies."""

from __future__ import annotations

import os
from dataclasses import replace
from datetime import datetime
from typing import Literal

import pandas as pd
import pytz
from pydantic import Field, field_validator

from msm.data_nodes.utils.time import normalize_datetime64_ns_utc
from msm_portfolios.services.calendars import resolve_rebalance_calendar

from ..base import PortfolioCanonicalDataNode, PortfolioCanonicalDataNodeConfiguration
from .storage import PortfolioCalendarEventsStorage


class PortfolioCalendarEventsConfiguration(PortfolioCanonicalDataNodeConfiguration):
    """Hash-bearing selection of persisted calendar session events."""

    calendar_identifier: str = Field(
        ...,
        min_length=1,
        description="Persisted CalendarTable unique_identifier to publish.",
        examples=["XNYS", "CRYPTO_24_7"],
    )
    session_label: str = Field(
        default="regular",
        min_length=1,
        description="Persisted CalendarSession label to publish.",
    )
    event_types: tuple[Literal["market_open", "market_close"], ...] = Field(
        default=("market_open", "market_close"),
        min_length=1,
        description="Session boundaries emitted at their actual UTC timestamps.",
    )

    @field_validator("event_types")
    @classmethod
    def _require_unique_event_types(
        cls,
        value: tuple[Literal["market_open", "market_close"], ...],
    ) -> tuple[Literal["market_open", "market_close"], ...]:
        if len(set(value)) != len(value):
            raise ValueError("event_types must not contain duplicate event types.")
        return value


class PortfolioCalendarEvents(PortfolioCanonicalDataNode):
    """Project governed CalendarSession rows into an explicit event dependency."""

    OFFSET_START = datetime(2018, 1, 1, tzinfo=pytz.utc)

    @classmethod
    def _validate_config(
        cls,
        config: PortfolioCanonicalDataNodeConfiguration,
    ) -> PortfolioCalendarEventsConfiguration:
        if not isinstance(config, PortfolioCalendarEventsConfiguration):
            raise TypeError(
                "PortfolioCalendarEvents requires PortfolioCalendarEventsConfiguration."
            )
        return config

    def update(self) -> pd.DataFrame:
        config = self._validate_config(self.config)
        latest = getattr(getattr(self, "update_statistics", None), "max_time_index_value", None)
        start: pd.Timestamp = (
            pd.Timestamp(self.OFFSET_START)
            if latest is None
            else pd.Timestamp(latest) + pd.Timedelta(1, unit="ns")
        )
        end = pd.Timestamp.now(tz="UTC")
        maximum_window = os.getenv("MAX_TD_FROM_LATEST_VALUE")
        if maximum_window:
            end = min(end, start + pd.Timedelta(maximum_window))

        calendar = resolve_rebalance_calendar(config.calendar_identifier)
        canonical_identifier = str(calendar.name)
        if canonical_identifier != config.calendar_identifier:
            raise ValueError(
                "PortfolioCalendarEvents.calendar_identifier must be the canonical "
                "Calendar.unique_identifier, not a source_identifier alias. "
                f"Resolved {config.calendar_identifier!r} to {canonical_identifier!r}."
            )
        if hasattr(calendar, "session_label"):
            calendar = replace(calendar, session_label=config.session_label)
        schedule = calendar.schedule(start_date=start, end_date=end)
        rows: list[dict[str, object]] = []
        for local_date, session in schedule.iterrows():
            for event_type in config.event_types:
                rows.append(
                    {
                        "time_index": session[event_type],
                        "calendar_identifier": canonical_identifier,
                        "session_label": config.session_label,
                        "event_type": event_type,
                        "local_date": local_date.isoformat(),
                    }
                )
        if not rows:
            return self.validate_frame(
                pd.DataFrame(
                    columns=[
                        "time_index",
                        "calendar_identifier",
                        "session_label",
                        "event_type",
                        "local_date",
                    ]
                ),
                output_table=self.output_table,
            )
        frame = pd.DataFrame(rows)
        frame["time_index"] = normalize_datetime64_ns_utc(frame["time_index"])
        frame = frame[(frame["time_index"] >= start) & (frame["time_index"] <= end)]
        return self.validate_frame(frame, output_table=self.output_table)

    @classmethod
    def _required_output_table(cls) -> type[PortfolioCalendarEventsStorage]:
        return PortfolioCalendarEventsStorage


__all__ = [
    "PortfolioCalendarEvents",
    "PortfolioCalendarEventsConfiguration",
]
