from __future__ import annotations

import datetime as dt
from types import SimpleNamespace

import pandas as pd
import pytest

from msm.api.calendars import ComputedCalendarSession
from msm.services.calendars import CalendarRangeError
from msm_portfolios.services import calendars


def calendar_row(identifier: str = "XNYS", *, source_identifier: str = "NYSE"):
    return SimpleNamespace(
        uid="calendar-uid",
        unique_identifier=identifier,
        source_identifier=source_identifier,
        valid_from=dt.date(1990, 1, 1),
        valid_to=dt.date(2200, 12, 31),
    )


def session(local_date: dt.date) -> ComputedCalendarSession:
    return ComputedCalendarSession(
        local_date=local_date,
        session_label="regular",
        opens_at=pd.Timestamp(local_date, tz="UTC").to_pydatetime() + dt.timedelta(hours=14, minutes=30),
        closes_at=pd.Timestamp(local_date, tz="UTC").to_pydatetime() + dt.timedelta(hours=21),
        timezone="America/New_York",
    )


def test_rebalance_calendar_requires_a_stored_calendar(monkeypatch) -> None:
    monkeypatch.setattr(calendars.Calendar, "get_by_unique_identifier", lambda _identifier: None)

    with pytest.raises(ValueError, match="Stored rebalance calendar 'MISSING' was not found"):
        calendars.resolve_rebalance_calendar("MISSING")


def test_rebalance_calendar_does_not_hide_backend_lookup_failures(monkeypatch) -> None:
    def fail_lookup(_identifier):
        raise RuntimeError("backend unavailable")

    monkeypatch.setattr(calendars.Calendar, "get_by_unique_identifier", fail_lookup)

    with pytest.raises(RuntimeError, match="backend unavailable"):
        calendars.resolve_rebalance_calendar("XNYS")


def test_rebalance_calendar_is_found_by_unique_identifier_only(monkeypatch) -> None:
    """Several stored calendars can come from one library calendar (ADR 0055)."""

    stored = {"NYSE": calendar_row("NYSE"), "CustomNYSE": calendar_row("CustomNYSE")}
    monkeypatch.setattr(calendars.Calendar, "get_by_unique_identifier", stored.get)
    monkeypatch.setattr(
        calendars.Calendar,
        "filter",
        lambda **_kwargs: pytest.fail("a calendar is not looked up by its source_identifier"),
    )

    assert calendars.resolve_rebalance_calendar("CustomNYSE").name == "CustomNYSE"
    assert calendars.resolve_rebalance_calendar(" NYSE ").name == "NYSE"
    # XNYS is the source name of no stored calendar's unique_identifier here.
    with pytest.raises(ValueError, match="'XNYS' was not found"):
        calendars.resolve_rebalance_calendar("XNYS")


def _asset(identifier: str, uid: str):
    return SimpleNamespace(unique_identifier=identifier, uid=uid)


def _stub_rows(monkeypatch, *, assets, links, stored) -> list[tuple[str, dict]]:
    calls: list[tuple[str, dict]] = []

    def reader(name, rows, column):
        def read(**filters):
            calls.append((name, filters))
            wanted = filters[f"{column}__in"]
            return [row for row in rows if getattr(row, column) in wanted]

        return read

    monkeypatch.setattr(calendars.Asset, "filter", reader("Asset", assets, "unique_identifier"))
    monkeypatch.setattr(calendars.AssetCalendar, "filter", reader("AssetCalendar", links, "asset_uid"))
    monkeypatch.setattr(calendars.Calendar, "filter", reader("Calendar", stored, "uid"))
    return calls


def test_asset_schedules_come_from_the_stored_links_in_three_reads(monkeypatch) -> None:
    nyse = calendar_row("NYSE")
    nyse.uid = "nyse-uid"
    crypto = calendar_row("CRYPTO_24_7")
    crypto.uid = "crypto-uid"
    calls = _stub_rows(
        monkeypatch,
        assets=[_asset("ACME", "a1"), _asset("BOLT", "a2"), _asset("BTC", "a3")],
        links=[
            SimpleNamespace(asset_uid="a1", calendar_uid="nyse-uid"),
            SimpleNamespace(asset_uid="a2", calendar_uid="nyse-uid"),
            SimpleNamespace(asset_uid="a3", calendar_uid="crypto-uid"),
        ],
        stored=[nyse, crypto],
    )

    schedules = calendars.resolve_asset_schedules(["ACME", "BOLT", "BTC", "ACME"])

    assert {identifier: schedule.name for identifier, schedule in schedules.items()} == {
        "ACME": "NYSE",
        "BOLT": "NYSE",
        "BTC": "CRYPTO_24_7",
    }
    # Two assets on one calendar share one schedule, so its sessions are read once.
    assert schedules["ACME"] is schedules["BOLT"]
    assert [name for name, _filters in calls] == ["Asset", "AssetCalendar", "Calendar"]
    assert calls[2][1]["uid__in"] == ["nyse-uid", "crypto-uid"]


def test_an_asset_with_no_calendar_fails_the_whole_scope(monkeypatch) -> None:
    nyse = calendar_row("NYSE")
    nyse.uid = "nyse-uid"
    calls = _stub_rows(
        monkeypatch,
        assets=[_asset("ACME", "a1"), _asset("BOLT", "a2"), _asset("CASH", "a3")],
        links=[SimpleNamespace(asset_uid="a1", calendar_uid="nyse-uid")],
        stored=[nyse],
    )

    with pytest.raises(calendars.AssetCalendarMissingError) as raised:
        calendars.resolve_asset_schedules(["ACME", "BOLT", "CASH", "GHOST"])

    # Every asset without a calendar is named; there is no default calendar.
    assert raised.value.unlinked == ["BOLT", "CASH"]
    assert raised.value.unknown == ["GHOST"]
    message = str(raised.value)
    assert "No trading calendar is linked to: BOLT, CASH." in message
    assert "Not an Asset row, so it has no trading calendar: GHOST." in message
    # The linked asset gets no schedule either: no calendar is read.
    assert [name for name, _filters in calls] == ["Asset", "AssetCalendar"]


def test_an_empty_scope_reads_nothing(monkeypatch) -> None:
    calls = _stub_rows(monkeypatch, assets=[], links=[], stored=[])

    assert calendars.resolve_asset_schedules([]) == {}
    assert calls == []


def test_the_library_is_not_a_schedule_source() -> None:
    """ADR 0056: outside the adapter nothing asks pandas_market_calendars."""

    for removed in (
        "AlwaysOpenCalendarSchedule",
        "PandasMarketCalendarSchedule",
        "resolve_legacy_rebalance_calendar",
    ):
        assert not hasattr(calendars, removed)


def test_stored_calendar_schedule_is_one_computed_read(monkeypatch) -> None:
    calls: list[tuple] = []

    def fake_sessions(calendar_uid, start_date, end_date, *, session_label=None):
        calls.append((calendar_uid, start_date, end_date, session_label))
        return [session(start_date), session(end_date)]

    monkeypatch.setattr(calendars.Calendar, "sessions", fake_sessions)

    schedule = calendars.PersistedCalendarSchedule(calendar=calendar_row("NYSE"))
    frame = schedule.schedule("2018-01-02", pd.Timestamp("2026-09-04T12:00:00Z"))

    # Eight years in one read: nothing is windowed.
    assert calls == [("calendar-uid", dt.date(2018, 1, 2), dt.date(2026, 9, 4), "regular")]
    assert list(frame.columns) == ["market_open", "market_close"]
    assert list(frame.index) == [dt.date(2018, 1, 2), dt.date(2026, 9, 4)]
    assert frame.loc[dt.date(2018, 1, 2), "market_open"] == pd.Timestamp("2018-01-02T14:30:00Z")
    assert frame.loc[dt.date(2026, 9, 4), "market_close"] == pd.Timestamp("2026-09-04T21:00:00Z")
    assert str(frame["market_close"].dt.tz) == "UTC"


def test_stored_calendar_schedule_without_sessions_is_an_empty_frame(monkeypatch) -> None:
    monkeypatch.setattr(calendars.Calendar, "sessions", lambda *args, **kwargs: [])

    frame = calendars.PersistedCalendarSchedule(calendar=calendar_row()).schedule(
        "2026-01-03", "2026-01-04"
    )

    assert frame.empty
    assert list(frame.columns) == ["market_open", "market_close"]


def test_stored_calendar_schedule_does_not_hide_a_window_outside_the_range(monkeypatch) -> None:
    def refuse(*args, **kwargs):
        raise CalendarRangeError("Calendar 'NYSE' is complete from 1990-01-01 to 2200-12-31")

    monkeypatch.setattr(calendars.Calendar, "sessions", refuse)

    with pytest.raises(CalendarRangeError):
        calendars.PersistedCalendarSchedule(calendar=calendar_row()).schedule(
            "2200-12-01", "2201-01-31"
        )
