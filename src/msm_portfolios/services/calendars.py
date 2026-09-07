from __future__ import annotations

import datetime as dt
from dataclasses import dataclass
from typing import Any

import pandas as pd

from msm.api.base import operation_result_rows
from msm.api.calendars import Calendar
from msm.repositories.calendars import search_calendar_sessions
from msm.services.calendars import ensure_date_range, iter_local_dates


# Governed MetaTable reads can cap an operation at 1,000 rows. A multi-year
# trading-calendar request can exceed that even though the requested date range
# is valid, so keep every read comfortably below that boundary.
_SESSION_QUERY_WINDOW_DAYS = 366 * 2


def _calendar_session_query_windows(
    start: dt.date,
    end: dt.date,
):
    window_start = start
    while window_start <= end:
        window_end = min(
            window_start + dt.timedelta(days=_SESSION_QUERY_WINDOW_DAYS - 1),
            end,
        )
        yield window_start, window_end
        window_start = window_end + dt.timedelta(days=1)


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
        rows: list[dict[str, Any]] = []
        for window_start, window_end in _calendar_session_query_windows(start, end):
            result = search_calendar_sessions(
                context,
                calendar_uid=str(self.calendar.uid),
                start_date=window_start,
                end_date=window_end,
                session_label=self.session_label,
            )
            rows.extend(operation_result_rows(result))
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
    """Resolve a persisted calendar for an economic rebalance contract.

    Calendar-relative execution must remain reproducible from governed
    ``CalendarSession`` rows. Missing calendars and backend lookup failures are
    therefore errors; callers never silently switch to a local calendar
    implementation.
    """

    identifier = str(calendar_key).strip()
    if not identifier:
        raise ValueError("calendar_identifier must be a non-empty string.")

    calendar = _find_persisted_calendar(identifier)
    if calendar is None:
        raise ValueError(
            f"Persisted rebalance calendar {identifier!r} was not found. "
            "Create and materialize the Calendar and CalendarSession rows before "
            "running CalendarEventSignal."
        )
    return PersistedCalendarSchedule(calendar=calendar)


def resolve_legacy_rebalance_calendar(calendar_key: str) -> Any:
    """Explicitly resolve a legacy local calendar helper.

    This helper is intentionally separate from ``resolve_rebalance_calendar``
    so a serialized economic strategy cannot fall back to process-local date
    generation.
    """

    identifier = str(calendar_key).strip()
    if not identifier:
        raise ValueError("calendar_key must be a non-empty string.")
    if identifier in {"24/7", "CRYPTO_24_7"}:
        return AlwaysOpenCalendarSchedule(name=identifier)
    return PandasMarketCalendarSchedule(calendar_key=identifier)


def _find_persisted_calendar(calendar_key: str) -> Calendar | None:
    matches = Calendar.filter(unique_identifier=calendar_key, limit=2)
    if len(matches) > 1:
        raise RuntimeError(
            f"Persisted calendar identifier {calendar_key!r} resolved to multiple rows."
        )
    if matches:
        return matches[0]

    matches = Calendar.filter(source_identifier=calendar_key, limit=2)
    if len(matches) > 1:
        raise ValueError(
            f"Calendar source_identifier {calendar_key!r} is ambiguous; "
            "configure CalendarEventSignal with a unique Calendar.unique_identifier."
        )
    return matches[0] if matches else None


__all__ = [
    "AlwaysOpenCalendarSchedule",
    "PandasMarketCalendarSchedule",
    "PersistedCalendarSchedule",
    "resolve_legacy_rebalance_calendar",
    "resolve_rebalance_calendar",
]
