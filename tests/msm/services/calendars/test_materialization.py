from __future__ import annotations

import datetime as dt
import uuid

from msm.services.calendars import (
    build_always_open_calendar_materialization,
    iter_local_dates,
)
from msm_portfolios.services.calendars import AlwaysOpenCalendarSchedule


def test_iter_local_dates_requires_ordered_range() -> None:
    assert list(iter_local_dates("2026-01-01", "2026-01-03")) == [
        dt.date(2026, 1, 1),
        dt.date(2026, 1, 2),
        dt.date(2026, 1, 3),
    ]


def test_always_open_calendar_materialization_builds_dates_and_sessions() -> None:
    calendar_uid = uuid.uuid4()

    rows = build_always_open_calendar_materialization(
        calendar_uid=calendar_uid,
        start_date=dt.date(2026, 1, 1),
        end_date=dt.date(2026, 1, 2),
    )

    assert len(rows.dates) == 2
    assert len(rows.sessions) == 2
    assert rows.dates[0]["calendar_uid"] == calendar_uid
    assert rows.sessions[0]["opens_at"].tzinfo is dt.UTC


def test_always_open_portfolio_schedule_matches_calendar_shape() -> None:
    schedule = AlwaysOpenCalendarSchedule(name="24/7").schedule(
        start_date=dt.date(2026, 1, 1),
        end_date=dt.date(2026, 1, 2),
    )

    assert list(schedule.columns) == ["market_open", "market_close"]
    assert len(schedule) == 2
