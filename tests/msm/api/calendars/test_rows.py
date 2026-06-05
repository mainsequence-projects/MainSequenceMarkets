from __future__ import annotations

import datetime as dt
import uuid

import pytest
from pydantic import ValidationError

from msm.api.calendars import (
    CalendarEventUpsert,
    CalendarSessionUpsert,
    CalendarType,
    CalendarUpsert,
)


def test_calendar_upsert_normalizes_type_and_validates_horizon() -> None:
    payload = CalendarUpsert(
        unique_identifier="XNYS",
        display_name="New York Stock Exchange",
        calendar_type="trading",
        timezone="America/New_York",
        valid_from=dt.date(2026, 1, 1),
        valid_to=dt.date(2026, 1, 31),
    )

    assert payload.calendar_type == CalendarType.TRADING.value

    with pytest.raises(ValidationError):
        CalendarUpsert(
            unique_identifier="BROKEN",
            display_name="Broken",
            calendar_type="trading",
            valid_from=dt.date(2026, 2, 1),
            valid_to=dt.date(2026, 1, 1),
        )


def test_calendar_session_requires_utc_aware_window() -> None:
    calendar_uid = uuid.uuid4()

    payload = CalendarSessionUpsert(
        calendar_uid=calendar_uid,
        local_date=dt.date(2026, 1, 5),
        session_label="regular",
        opens_at="2026-01-05T14:30:00-05:00",
        closes_at="2026-01-05T16:00:00-05:00",
        timezone="America/New_York",
    )

    assert payload.opens_at == dt.datetime(2026, 1, 5, 19, 30, tzinfo=dt.UTC)
    assert payload.closes_at == dt.datetime(2026, 1, 5, 21, 0, tzinfo=dt.UTC)

    with pytest.raises(ValidationError):
        CalendarSessionUpsert(
            calendar_uid=calendar_uid,
            local_date=dt.date(2026, 1, 5),
            session_label="regular",
            opens_at=dt.datetime(2026, 1, 5, 9, 30),
        )


def test_calendar_event_upsert_requires_event_date_for_conflict_key() -> None:
    with pytest.raises(ValidationError):
        CalendarEventUpsert(
            calendar_uid=uuid.uuid4(),
            event_type="expiry",
        )

    payload = CalendarEventUpsert(
        calendar_uid=uuid.uuid4(),
        event_date=dt.date(2026, 3, 20),
        event_type="last trade",
        event_label=None,
        target_type=None,
        target_identifier=None,
    )

    assert payload.event_type == "LAST_TRADE"
    assert payload.event_label == ""
    assert payload.target_type == ""
    assert payload.target_identifier == ""
