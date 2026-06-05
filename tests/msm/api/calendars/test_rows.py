from __future__ import annotations

import datetime as dt
import uuid
from types import SimpleNamespace

import pytest
from pydantic import ValidationError

from msm.api.calendars import (
    Calendar,
    CalendarEventUpsert,
    CalendarSessionUpsert,
    CalendarType,
    CalendarUpsert,
)
from msm.models import CalendarDateTable, CalendarSessionTable, CalendarTable


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


def test_calendar_create_from_pandas_calendar_materializes(monkeypatch) -> None:
    runtime = SimpleNamespace(context=object())
    calls: dict[str, object] = {}
    calendar_uid = uuid.uuid4()

    def fake_resolve_runtime(**kwargs):
        calls["resolve_runtime"] = kwargs
        return runtime

    def fake_upsert(cls, **kwargs):
        calls["upsert"] = kwargs
        return SimpleNamespace(
            uid=calendar_uid,
            unique_identifier=kwargs["unique_identifier"],
            timezone=kwargs["timezone"],
        )

    def fake_build_materialization(**kwargs):
        calls["build_materialization"] = kwargs
        return SimpleNamespace(dates=[{"calendar_uid": calendar_uid}], sessions=[], events=[])

    def fake_materialize(context, rows):
        calls["materialize"] = (context, rows)
        return {"dates": {"rows": []}}

    monkeypatch.setattr("msm.bootstrap.resolve_runtime", fake_resolve_runtime)
    monkeypatch.setattr(Calendar, "upsert", classmethod(fake_upsert))
    monkeypatch.setattr(
        "msm.api.calendars.core._pandas_market_calendar_timezone",
        lambda source_identifier: "America/New_York",
    )
    monkeypatch.setattr(
        "msm.services.calendars.build_pandas_market_calendar_materialization",
        fake_build_materialization,
    )
    monkeypatch.setattr("msm.services.calendars.materialize_calendar_rows", fake_materialize)

    calendar = Calendar.create_from_pandas_calendar(
        source_identifier="NYSE",
        unique_identifier="XNYS",
        display_name="New York Stock Exchange",
        valid_from="2026-01-01",
        valid_to="2026-01-02",
    )

    assert calendar.unique_identifier == "XNYS"
    assert calls["resolve_runtime"] == {
        "models": [CalendarTable, CalendarDateTable, CalendarSessionTable],
        "row_model_name": "Calendar",
    }
    assert calls["upsert"] == {
        "unique_identifier": "XNYS",
        "display_name": "New York Stock Exchange",
        "calendar_type": CalendarType.TRADING,
        "timezone": "America/New_York",
        "source": "pandas_market_calendars",
        "source_identifier": "NYSE",
        "valid_from": dt.date(2026, 1, 1),
        "valid_to": dt.date(2026, 1, 2),
        "metadata_json": None,
    }
    assert calls["build_materialization"] == {
        "calendar_uid": calendar_uid,
        "source_identifier": "NYSE",
        "start_date": dt.date(2026, 1, 1),
        "end_date": dt.date(2026, 1, 2),
        "timezone": "America/New_York",
        "session_label": "regular",
    }
    assert calls["materialize"][0] is runtime.context
