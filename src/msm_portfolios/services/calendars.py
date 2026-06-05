from __future__ import annotations

import datetime as dt
from dataclasses import dataclass
from typing import Any

import pandas as pd

from msm.api.base import operation_result_rows
from msm.api.calendars import Calendar
from msm.repositories.calendars import search_calendar_sessions
from msm.services.calendars import ensure_date_range, iter_local_dates


@dataclass(frozen=True)
class PersistedCalendarSchedule:
    """Pandas-like schedule adapter backed by persisted calendar session rows."""

    calendar: Calendar
    session_label: str = "regular"

    @property
    def name(self) -> str:
        return self.calendar.unique_identifier

    def schedule(
        self,
        start_date: dt.date | dt.datetime | str,
        end_date: dt.date | dt.datetime | str,
    ) -> pd.DataFrame:
        start, end = ensure_date_range(start_date, end_date)
        context = Calendar._active_context()
        result = search_calendar_sessions(
            context,
            calendar_uid=str(self.calendar.uid),
            start_date=start,
            end_date=end,
            session_label=self.session_label,
        )
        rows = operation_result_rows(result)
        if not rows:
            return pd.DataFrame(columns=["market_open", "market_close"])

        frame = pd.DataFrame(rows)
        frame["market_open"] = pd.to_datetime(frame["opens_at"], utc=True)
        frame["market_close"] = pd.to_datetime(frame["closes_at"], utc=True)
        frame["local_date"] = pd.to_datetime(frame["local_date"]).dt.date
        return frame.sort_values("local_date").set_index("local_date")[
            ["market_open", "market_close"]
        ]


@dataclass(frozen=True)
class AlwaysOpenCalendarSchedule:
    """Synthetic 24/7 schedule for legacy portfolio strategy configuration."""

    name: str = "CRYPTO_24_7"

    def schedule(
        self,
        start_date: dt.date | dt.datetime | str,
        end_date: dt.date | dt.datetime | str,
    ) -> pd.DataFrame:
        rows = []
        for local_date in iter_local_dates(start_date, end_date):
            opens_at = dt.datetime.combine(local_date, dt.time.min, tzinfo=dt.UTC)
            rows.append(
                {
                    "local_date": local_date,
                    "market_open": pd.Timestamp(opens_at),
                    "market_close": pd.Timestamp(opens_at + dt.timedelta(days=1)),
                }
            )
        if not rows:
            return pd.DataFrame(columns=["market_open", "market_close"])
        return pd.DataFrame(rows).set_index("local_date")[["market_open", "market_close"]]


@dataclass(frozen=True)
class PandasMarketCalendarSchedule:
    """Legacy fallback adapter for calendar keys not persisted yet."""

    calendar_key: str

    @property
    def name(self) -> str:
        return self.calendar_key

    def schedule(
        self,
        start_date: dt.date | dt.datetime | str,
        end_date: dt.date | dt.datetime | str,
    ) -> pd.DataFrame:
        import pandas_market_calendars as mcal

        calendar = mcal.get_calendar(self.calendar_key)
        start, end = ensure_date_range(start_date, end_date)
        return calendar.schedule(start_date=start, end_date=end)


def resolve_rebalance_calendar(calendar_key: str) -> Any:
    """Resolve a portfolio rebalance calendar, preferring persisted calendars."""

    if calendar_key == "24/7":
        return AlwaysOpenCalendarSchedule(name=calendar_key)

    calendar = _find_persisted_calendar(calendar_key)
    if calendar is not None:
        return PersistedCalendarSchedule(calendar=calendar)

    if calendar_key == "CRYPTO_24_7":
        return AlwaysOpenCalendarSchedule(name=calendar_key)

    return PandasMarketCalendarSchedule(calendar_key=calendar_key)


def _find_persisted_calendar(calendar_key: str) -> Calendar | None:
    try:
        matches = Calendar.filter(unique_identifier=calendar_key, limit=1)
        if not matches:
            matches = Calendar.filter(source_identifier=calendar_key, limit=1)
    except Exception:
        return None
    return matches[0] if matches else None


__all__ = [
    "AlwaysOpenCalendarSchedule",
    "PandasMarketCalendarSchedule",
    "PersistedCalendarSchedule",
    "resolve_rebalance_calendar",
]
