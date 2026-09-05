from __future__ import annotations

import datetime as dt
from types import SimpleNamespace

import pandas as pd

from msm_portfolios.services import calendars


def test_persisted_calendar_schedule_chunks_multi_year_session_reads(monkeypatch) -> None:
    calls: list[dict[str, object]] = []

    def fake_search_calendar_sessions(_context, **kwargs):
        calls.append(kwargs)
        start_date = kwargs["start_date"]
        end_date = kwargs["end_date"]
        return {
            "rows": [
                {
                    "local_date": start_date,
                    "opens_at": pd.Timestamp(start_date, tz="UTC"),
                    "closes_at": pd.Timestamp(start_date, tz="UTC") + pd.Timedelta(hours=6),
                },
                {
                    "local_date": end_date,
                    "opens_at": pd.Timestamp(end_date, tz="UTC"),
                    "closes_at": pd.Timestamp(end_date, tz="UTC") + pd.Timedelta(hours=6),
                },
            ]
        }

    monkeypatch.setattr(calendars.Calendar, "_active_context", lambda: object())
    monkeypatch.setattr(calendars, "search_calendar_sessions", fake_search_calendar_sessions)
    monkeypatch.setattr(calendars, "operation_result_rows", lambda result: result["rows"])

    schedule = calendars.PersistedCalendarSchedule(
        calendar=SimpleNamespace(uid="calendar-uid", unique_identifier="NYSE")
    )
    frame = schedule.schedule("2018-01-01", "2026-09-05")

    assert len(calls) > 1
    assert calls[0]["start_date"] == dt.date(2018, 1, 1)
    assert calls[-1]["end_date"] == dt.date(2026, 9, 5)
    for previous, current in zip(calls, calls[1:], strict=False):
        assert current["start_date"] == previous["end_date"] + dt.timedelta(days=1)
    assert all(
        call["end_date"] - call["start_date"]
        < dt.timedelta(days=calendars._SESSION_QUERY_WINDOW_DAYS)
        for call in calls
    )
    assert frame.index.min() == dt.date(2018, 1, 1)
    assert frame.index.max() == dt.date(2026, 9, 5)
