"""Published persisted-calendar events for rebalance strategies."""

from __future__ import annotations

import os
from dataclasses import replace
from datetime import datetime
from typing import Literal

import pandas as pd
import pytz
from pydantic import Field, field_validator

from msm.time_index.utils.time import normalize_datetime64_ns_utc
from msm_portfolios.services.calendars import resolve_rebalance_calendar

from ..base import PortfolioCanonicalUpdater, PortfolioCanonicalUpdaterConfiguration
from .storage import PortfolioCalendarEventsStorage


class PortfolioCalendarEventsConfiguration(PortfolioCanonicalUpdaterConfiguration):
    """Hash-bearing selection of a stored calendar's session events."""

    calendar_identifier: str = Field(
        ...,
        min_length=1,
        description="Persisted CalendarTable unique_identifier to publish.",
        examples=["XNYS", "CRYPTO_24_7"],
    )
    session_label: str = Field(
        default="regular",
        min_length=1,
        description="Session label of the stored calendar to publish.",
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


class PortfolioCalendarEvents(PortfolioCanonicalUpdater):
    """Publish a stored calendar's computed sessions as an explicit event dependency."""

    OFFSET_START = datetime(2018, 1, 1, tzinfo=pytz.utc)

    @classmethod
    def _validate_config(
        cls,
        config: PortfolioCanonicalUpdaterConfiguration,
    ) -> PortfolioCalendarEventsConfiguration:
        if not isinstance(config, PortfolioCalendarEventsConfiguration):
            raise TypeError(
                "PortfolioCalendarEvents requires PortfolioCalendarEventsConfiguration."
            )
        return config

    def _latest_by_event_type(
        self, config: PortfolioCalendarEventsConfiguration
    ) -> dict[str, pd.Timestamp | None]:
        """This calendar and session label's latest event of each type, not the table's.

        One events table holds every calendar's events, so the table's latest time is
        another calendar's progress, never this one's start (#119).
        """

        progress = getattr(getattr(self, "update_statistics", None), "index_progress", None)
        own = (progress or {}).get(config.calendar_identifier) if isinstance(progress, dict) else None
        own = own.get(config.session_label) if isinstance(own, dict) else None
        return {
            event_type: (
                None
                if not isinstance(own, dict) or own.get(event_type) is None
                else pd.Timestamp(own[event_type])
            )
            for event_type in config.event_types
        }

    def update(self) -> pd.DataFrame:
        config = self._validate_config(self.config)
        latest = self._latest_by_event_type(config)
        # Each event type continues after its own latest event; one with none starts at
        # OFFSET_START. The schedule is read from the earliest of those starts.
        start: pd.Timestamp = (
            pd.Timestamp(self.OFFSET_START)
            if any(value is None for value in latest.values())
            else min(latest.values()) + pd.Timedelta(1, unit="ns")
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
                "Calendar.unique_identifier. "
                f"Resolved {config.calendar_identifier!r} to {canonical_identifier!r}."
            )
        if hasattr(calendar, "session_label"):
            calendar = replace(calendar, session_label=config.session_label)
        # The first run starts at OFFSET_START. A calendar that begins later has
        # no event before its first date, so the read starts there. A window that
        # ends after the calendar's last date is refused by the calendar itself.
        first_date = getattr(getattr(calendar, "calendar", None), "valid_from", None)
        schedule_start = start if first_date is None else max(start, pd.Timestamp(first_date, tz="UTC"))
        if schedule_start > end:
            schedule = pd.DataFrame(columns=list(config.event_types))
        else:
            schedule = calendar.schedule(start_date=schedule_start, end_date=end)
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
        published = frame["event_type"].map(latest)
        frame = frame[
            (frame["time_index"] >= start)
            & (frame["time_index"] <= end)
            & (published.isna() | (frame["time_index"] > published))
        ]
        return self.validate_frame(frame, output_table=self.output_table)

    @classmethod
    def _required_output_table(cls) -> type[PortfolioCalendarEventsStorage]:
        return PortfolioCalendarEventsStorage


__all__ = [
    "PortfolioCalendarEvents",
    "PortfolioCalendarEventsConfiguration",
]
