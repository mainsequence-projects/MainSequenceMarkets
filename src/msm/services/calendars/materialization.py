from __future__ import annotations

import datetime as dt
import uuid
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any

from msm.repositories import MarketsRepositoryContext
from msm.repositories.calendars import (
    bulk_upsert_calendar_dates,
    bulk_upsert_calendar_events,
    bulk_upsert_calendar_sessions,
)

from .validation import iter_local_dates


@dataclass(frozen=True)
class CalendarMaterializationRows:
    """Calendar date, session, and event rows ready for MetaTable upsert."""

    dates: list[dict[str, Any]] = field(default_factory=list)
    sessions: list[dict[str, Any]] = field(default_factory=list)
    events: list[dict[str, Any]] = field(default_factory=list)


def build_always_open_calendar_materialization(
    *,
    calendar_uid: uuid.UUID | str,
    start_date: dt.date | dt.datetime | str,
    end_date: dt.date | dt.datetime | str,
    timezone: str = "UTC",
    session_label: str = "regular",
) -> CalendarMaterializationRows:
    """Build a 24/7 calendar materialization for assets such as crypto markets."""

    dates: list[dict[str, Any]] = []
    sessions: list[dict[str, Any]] = []
    for local_date in iter_local_dates(start_date, end_date):
        dates.append(
            {
                "calendar_uid": calendar_uid,
                "local_date": local_date,
                "is_business_day": True,
                "is_holiday": False,
                "is_weekend": local_date.weekday() >= 5,
                "is_early_close": False,
                "holiday_name": None,
                "metadata_json": {"source": "always_open"},
            }
        )
        opens_at = dt.datetime.combine(local_date, dt.time.min, tzinfo=dt.UTC)
        closes_at = opens_at + dt.timedelta(days=1)
        sessions.append(
            {
                "calendar_uid": calendar_uid,
                "local_date": local_date,
                "session_label": session_label,
                "opens_at": opens_at,
                "closes_at": closes_at,
                "timezone": timezone,
                "is_primary": True,
                "metadata_json": {"source": "always_open"},
            }
        )
    return CalendarMaterializationRows(dates=dates, sessions=sessions)


def materialize_calendar_rows(
    context: MarketsRepositoryContext,
    rows: CalendarMaterializationRows | None = None,
    *,
    dates: Sequence[Mapping[str, Any]] | None = None,
    sessions: Sequence[Mapping[str, Any]] | None = None,
    events: Sequence[Mapping[str, Any]] | None = None,
) -> dict[str, Any]:
    """Bulk upsert normalized calendar rows into the active markets runtime."""

    date_rows = list(dates if dates is not None else (rows.dates if rows else []))
    session_rows = list(sessions if sessions is not None else (rows.sessions if rows else []))
    event_rows = list(events if events is not None else (rows.events if rows else []))

    results: dict[str, Any] = {}
    if date_rows:
        results["dates"] = bulk_upsert_calendar_dates(context, date_rows)
    if session_rows:
        results["sessions"] = bulk_upsert_calendar_sessions(context, session_rows)
    if event_rows:
        results["events"] = bulk_upsert_calendar_events(context, event_rows)
    return results


__all__ = [
    "CalendarMaterializationRows",
    "build_always_open_calendar_materialization",
    "materialize_calendar_rows",
]
