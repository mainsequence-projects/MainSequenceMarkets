from __future__ import annotations

import datetime as dt
from collections.abc import Iterator


def coerce_local_date(value: dt.date | dt.datetime | str) -> dt.date:
    if isinstance(value, dt.datetime):
        return value.date()
    if isinstance(value, dt.date):
        return value
    return dt.date.fromisoformat(str(value))


def ensure_date_range(
    start_date: dt.date | dt.datetime | str,
    end_date: dt.date | dt.datetime | str,
) -> tuple[dt.date, dt.date]:
    start = coerce_local_date(start_date)
    end = coerce_local_date(end_date)
    if end < start:
        raise ValueError("end_date must be greater than or equal to start_date.")
    return start, end


def iter_local_dates(
    start_date: dt.date | dt.datetime | str,
    end_date: dt.date | dt.datetime | str,
) -> Iterator[dt.date]:
    current, end = ensure_date_range(start_date, end_date)
    while current <= end:
        yield current
        current += dt.timedelta(days=1)


__all__ = [
    "coerce_local_date",
    "ensure_date_range",
    "iter_local_dates",
]
