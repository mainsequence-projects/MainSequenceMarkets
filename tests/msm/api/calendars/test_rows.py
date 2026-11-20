from __future__ import annotations

import datetime as dt
import uuid
from types import SimpleNamespace

import pytest
from pydantic import ValidationError

import msm.api
import msm.api.calendars
from msm.api.calendars import (
    Calendar,
    CalendarExceptionCreate,
    CalendarExceptionType,
    CalendarExceptionUpdate,
    CalendarExceptionUpsert,
    CalendarSessionRuleUpdate,
    CalendarSessionRuleUpsert,
    CalendarType,
    CalendarUpsert,
)
from msm.api.remote import remote_operations
from msm.models import CalendarExceptionTable, CalendarSessionRuleTable, CalendarTable
from msm.services.calendars import CalendarSyncResult
from tests.support.markets_runtime import serve_runtime


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


def test_a_calendar_needs_no_range() -> None:
    payload = CalendarUpsert(unique_identifier="DESK", display_name="Desk", calendar_type="custom")

    assert (payload.valid_from, payload.valid_to) == (None, None)


def test_session_rule_payload_normalizes_times_and_validates_the_week() -> None:
    payload = CalendarSessionRuleUpsert(
        calendar_uid=uuid.uuid4(),
        effective_from=dt.date(1985, 1, 1),
        weekdays="1111100",
        opens_at_local="09:30",
        closes_at_local=dt.time(16, 0),
    )

    assert (payload.session_label, payload.opens_at_local, payload.closes_at_local) == (
        "regular",
        "09:30:00",
        "16:00:00",
    )
    assert (payload.open_day_offset, payload.close_day_offset, payload.is_primary) == (0, 0, True)

    base = {"calendar_uid": uuid.uuid4(), "effective_from": dt.date(2026, 1, 1), "weekdays": "1111100"}
    for bad in (
        {"weekdays": "11111"},
        {"weekdays": "MTWTF--"},
        {"opens_at_local": "9am"},
        {"open_day_offset": -2},
        {"effective_to": dt.date(2025, 12, 31)},
        {"timezone": "UTC"},
    ):
        with pytest.raises(ValidationError):
            CalendarSessionRuleUpsert(**{**base, **bad})
    with pytest.raises(ValidationError):
        CalendarSessionRuleUpdate(weekdays="1")


def test_exception_payload_validates_type_and_times() -> None:
    calendar_uid = uuid.uuid4()
    closed = CalendarExceptionUpsert(
        calendar_uid=calendar_uid, local_date=dt.date(2024, 12, 25), exception_type="closed"
    )
    early = CalendarExceptionUpsert(
        calendar_uid=calendar_uid,
        local_date=dt.date(2024, 12, 24),
        session_label="regular",
        exception_type=CalendarExceptionType.EARLY_CLOSE,
        closes_at_local="13:00",
    )
    opened = CalendarExceptionCreate(
        calendar_uid=calendar_uid, local_date=dt.date(2024, 12, 24), exception_type="OPEN"
    )

    assert (closed.exception_type, closed.session_label) == ("CLOSED", "")
    assert (early.exception_type, early.closes_at_local) == ("EARLY_CLOSE", "13:00:00")
    assert (opened.opens_at_local, opened.closes_at_local) == (None, None)

    base = {"calendar_uid": calendar_uid, "local_date": dt.date(2024, 12, 24)}
    for bad in (
        {"exception_type": "HOLIDAY"},
        {"exception_type": "CLOSED", "closes_at_local": "13:00"},
        {"exception_type": "EARLY_CLOSE"},
        {"exception_type": "EARLY_CLOSE", "closes_at_local": "13:00", "opens_at_local": "10:00"},
        {"exception_type": "LATE_OPEN"},
        {"exception_type": "LATE_OPEN", "opens_at_local": "25:00"},
    ):
        with pytest.raises(ValidationError):
            CalendarExceptionCreate(**{**base, **bad})


def test_a_caller_cannot_choose_an_exceptions_source() -> None:
    """A row written through the row API is a user's row; only an adapter writes another source."""

    with pytest.raises(ValidationError):
        CalendarExceptionCreate(
            calendar_uid=uuid.uuid4(),
            local_date=dt.date(2024, 12, 24),
            exception_type="CLOSED",
            source="pandas_market_calendars",
        )
    with pytest.raises(ValidationError):
        CalendarExceptionUpdate(source="pandas_market_calendars")


def test_per_date_row_classes_are_gone() -> None:
    for module in (msm.api, msm.api.calendars):
        for name in ("CalendarDate", "CalendarSession", "CalendarEvent"):
            assert not hasattr(module, name)


def test_calendar_reads_and_the_adapter_write_are_remote_operations() -> None:
    operations = remote_operations(Calendar)

    assert {"create_from_pandas_calendar", "sessions", "dates", "is_business_day"} <= set(operations)


def test_rules_and_exceptions_can_be_deleted_under_the_remote_backend() -> None:
    """The rows route offers ``delete`` only for a class that defines its own (ADR 0055)."""

    from msm.api.calendars import CalendarException, CalendarSessionRule

    for row in (CalendarException, CalendarSessionRule):
        assert "delete" in vars(row)
        assert "delete" in remote_operations(row)


def test_create_from_pandas_calendar_takes_the_library_name_and_the_stored_name(monkeypatch) -> None:
    runtime = SimpleNamespace(context=object())
    calls: dict[str, object] = {}
    calendar_uid = uuid.uuid4()

    def fake_resolve_runtime(**kwargs):
        calls["resolve_runtime"] = kwargs
        return runtime

    def fake_sync(context, **kwargs):
        calls["sync"] = (context, kwargs)
        return CalendarSyncResult(
            calendar={
                "uid": calendar_uid,
                "unique_identifier": kwargs["unique_identifier"],
                "display_name": kwargs["unique_identifier"],
                "calendar_type": "TRADING",
                "timezone": "America/New_York",
                "source": "pandas_market_calendars",
                "source_identifier": kwargs["source_identifier"],
                "valid_from": dt.date(1990, 1, 1),
                "valid_to": dt.date(2200, 12, 31),
                "metadata_json": {"source_version": "5.4.0"},
            },
            created=True,
            dry_run=False,
            changed=True,
            source_version="5.4.0",
        )

    serve_runtime(monkeypatch, fake_resolve_runtime)
    monkeypatch.setattr("msm.services.calendars.sync_pandas_market_calendar", fake_sync)

    calendar = Calendar.create_from_pandas_calendar("NYSE", "CustomNYSE")

    assert (calendar.uid, calendar.unique_identifier) == (calendar_uid, "CustomNYSE")
    assert calendar.valid_to == dt.date(2200, 12, 31)
    assert calls["resolve_runtime"] == {
        "models": [CalendarTable, CalendarSessionRuleTable, CalendarExceptionTable],
        "row_model_name": "Calendar",
    }
    context, arguments = calls["sync"]
    assert context is runtime.context
    assert arguments == {
        "source_identifier": "NYSE",
        "unique_identifier": "CustomNYSE",
        "display_name": None,
        "calendar_type": None,
        "timezone": None,
        "session_label": None,
        "valid_from": None,
        "metadata_json": None,
    }


def test_create_from_pandas_calendar_no_longer_takes_a_range_end_or_materialize() -> None:
    for removed in ({"valid_to": "2030-01-01"}, {"materialize": False}):
        with pytest.raises(TypeError):
            Calendar.create_from_pandas_calendar("NYSE", **removed)
