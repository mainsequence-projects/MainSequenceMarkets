from __future__ import annotations

import datetime as dt
import uuid
from typing import Any

from .materialization import CalendarMaterializationRows
from .validation import ensure_date_range, iter_local_dates


def build_pandas_market_calendar_materialization(
    *,
    calendar_uid: uuid.UUID | str,
    source_identifier: str,
    start_date: dt.date | dt.datetime | str,
    end_date: dt.date | dt.datetime | str,
    timezone: str | None = None,
    session_label: str = "regular",
) -> CalendarMaterializationRows:
    """Build persisted calendar rows from a pandas_market_calendars adapter."""

    import pandas as pd
    import pandas_market_calendars as mcal

    start, end = ensure_date_range(start_date, end_date)
    market_calendar = mcal.get_calendar(source_identifier)
    schedule = market_calendar.schedule(start_date=start.isoformat(), end_date=end.isoformat())
    calendar_timezone = timezone or str(getattr(market_calendar, "tz", "UTC") or "UTC")
    business_dates = {_schedule_local_date(index_value) for index_value in schedule.index}
    early_close_dates = _early_close_dates(market_calendar, schedule)

    date_rows: list[dict[str, Any]] = []
    for local_date in iter_local_dates(start, end):
        is_business_day = local_date in business_dates
        is_weekend = local_date.weekday() >= 5
        date_rows.append(
            {
                "calendar_uid": calendar_uid,
                "local_date": local_date,
                "is_business_day": is_business_day,
                "is_holiday": not is_business_day and not is_weekend,
                "is_weekend": is_weekend,
                "is_early_close": local_date in early_close_dates,
                "holiday_name": None,
                "metadata_json": {
                    "source": "pandas_market_calendars",
                    "source_identifier": source_identifier,
                },
            }
        )

    session_rows: list[dict[str, Any]] = []
    for index_value, row in schedule.iterrows():
        local_date = _schedule_local_date(index_value)
        market_open = row.get("market_open")
        market_close = row.get("market_close")
        session_rows.append(
            {
                "calendar_uid": calendar_uid,
                "local_date": local_date,
                "session_label": session_label,
                "opens_at": _utc_datetime_or_none(market_open, pd=pd),
                "closes_at": _utc_datetime_or_none(market_close, pd=pd),
                "timezone": calendar_timezone,
                "is_primary": True,
                "metadata_json": {
                    "source": "pandas_market_calendars",
                    "source_identifier": source_identifier,
                },
            }
        )

    return CalendarMaterializationRows(dates=date_rows, sessions=session_rows)


def _schedule_local_date(value: Any) -> dt.date:
    timestamp = getattr(value, "date", None)
    if callable(timestamp):
        return timestamp()
    return dt.date.fromisoformat(str(value))


def _early_close_dates(market_calendar: Any, schedule: Any) -> set[dt.date]:
    early_closes = getattr(market_calendar, "early_closes", None)
    if not callable(early_closes):
        return set()
    try:
        early_close_schedule = early_closes(schedule=schedule)
    except TypeError:
        early_close_schedule = early_closes(schedule)
    return {_schedule_local_date(index_value) for index_value in early_close_schedule.index}


def _utc_datetime_or_none(value: Any, *, pd: Any) -> dt.datetime | None:
    if pd.isna(value):
        return None
    timestamp = pd.Timestamp(value)
    if timestamp.tzinfo is None:
        timestamp = timestamp.tz_localize("UTC")
    else:
        timestamp = timestamp.tz_convert("UTC")
    return timestamp.to_pydatetime()


__all__ = ["build_pandas_market_calendar_materialization"]
