"""Revision 0027 stores calendars as session rules and exceptions (ADR 0055)."""

from __future__ import annotations

import datetime as dt
import importlib
import uuid

import pytest
import sqlalchemy as sa
from alembic import command

from msm.models import CalendarExceptionTable, CalendarSessionRuleTable, CalendarTable
from msm.services.calendars import CalendarDefinition, compute_dates, compute_sessions
from tests.support.migrations import _config

REVISION = importlib.import_module(
    "msm_migrations.versions.mainsequence_markets.0027_calendar_rules_and_exceptions"
)
NEW_YORK = "America/New_York"
UTC = dt.UTC


def _table(connection, name: str) -> sa.Table:
    # Only the table at hand: reflecting the whole schema for each seeded row was most
    # of these tests' time.
    return sa.Table(name, sa.MetaData(), autoload_with=connection, resolve_fks=False)


def _uid(connection) -> object:
    # SQLite stores a uid as 32 hex characters.
    value = uuid.uuid4()
    return value if connection.dialect.name == "postgresql" else value.hex


def _calendar(connection, identifier: str, **values) -> object:
    uid = _uid(connection)
    connection.execute(
        _table(connection, REVISION.CALENDAR_TABLE).insert(),
        {
            "uid": uid,
            "unique_identifier": identifier,
            "display_name": identifier,
            "calendar_type": "TRADING",
            "timezone": NEW_YORK,
            "source": "pandas_market_calendars",
            "source_identifier": identifier,
            "valid_from": dt.date(2020, 1, 1),
            "valid_to": dt.date(2030, 12, 31),
            **values,
        },
    )
    return uid


def _date(connection, calendar_uid, local_date: str, *, business: bool, name: str | None = None) -> None:
    day = dt.date.fromisoformat(local_date)
    connection.execute(
        _table(connection, REVISION.DATE_TABLE).insert(),
        {
            "uid": _uid(connection),
            "calendar_uid": calendar_uid,
            "local_date": day,
            "is_business_day": business,
            "is_holiday": not business and day.weekday() < 5,
            "is_weekend": day.weekday() >= 5,
            "is_early_close": False,
            "holiday_name": name,
        },
    )


def _session(connection, calendar_uid, local_date: str, opens: str, closes: str, label="regular") -> None:
    connection.execute(
        _table(connection, REVISION.SESSION_TABLE).insert(),
        {
            "uid": _uid(connection),
            "calendar_uid": calendar_uid,
            "local_date": dt.date.fromisoformat(local_date),
            "session_label": label,
            "opens_at": dt.datetime.fromisoformat(opens).astimezone(UTC),
            "closes_at": dt.datetime.fromisoformat(closes).astimezone(UTC),
            "timezone": NEW_YORK,
            "is_primary": True,
        },
    )


def _seed_nyse_week(connection, calendar_uid) -> None:
    """Monday 2024-11-11 to Sunday 2024-12-01 as the old adapter stored it."""

    day = dt.date(2024, 11, 11)
    while day <= dt.date(2024, 12, 1):
        text = day.isoformat()
        thanksgiving = text == "2024-11-28"
        business = day.weekday() < 5 and not thanksgiving
        _date(
            connection,
            calendar_uid,
            text,
            business=business,
            name="Thanksgiving" if thanksgiving else None,
        )
        if business:
            close = "13:00:00" if text == "2024-11-29" else "16:00:00"
            _session(connection, calendar_uid, text, f"{text}T09:30:00-05:00", f"{text}T{close}-05:00")
        day += dt.timedelta(days=1)


def _rows(connection, table: str, calendar_uid=None) -> list[dict]:
    reflected = _table(connection, table)
    statement = sa.select(reflected)
    if calendar_uid is not None:
        statement = statement.where(reflected.c.calendar_uid == calendar_uid)
    return [dict(row) for row in connection.execute(statement).mappings()]


def _stored_definition(connection, calendar_uid) -> CalendarDefinition:
    calendar = next(
        row for row in _rows(connection, REVISION.CALENDAR_TABLE) if row["uid"] == calendar_uid
    )
    return CalendarDefinition.from_rows(
        timezone=calendar["timezone"],
        rules=_rows(connection, REVISION.RULE_TABLE, calendar_uid),
        exceptions=_rows(connection, REVISION.EXCEPTION_TABLE, calendar_uid),
        valid_from=calendar["valid_from"],
        valid_to=calendar["valid_to"],
    )


def test_0027_matches_the_models(tmp_path, sqlite_revisions) -> None:
    engine = sqlite_revisions.engine(tmp_path / "calendar-model.sqlite", "head")
    with engine.connect() as connection:
        inspector = sa.inspect(connection)

        for model in (
            CalendarTable.__table__,
            CalendarSessionRuleTable.__table__,
            CalendarExceptionTable.__table__,
        ):
            columns = {column["name"]: column for column in inspector.get_columns(model.name)}
            assert set(columns) == {column.name for column in model.columns}
            assert {name: column["nullable"] for name, column in columns.items()} == {
                column.name: column.nullable for column in model.columns
            }
            assert {index["name"] for index in inspector.get_indexes(model.name)} == {
                index.name for index in model.indexes
            }
            assert {
                key["name"]: (key["constrained_columns"], key["options"].get("ondelete"))
                for key in inspector.get_foreign_keys(model.name)
            } == {
                key.name: ([column.name for column in key.columns], key.ondelete)
                for key in model.foreign_key_constraints
            }
        assert REVISION.RULE_GRAIN == [
            column.name for column in next(iter(CalendarSessionRuleTable.__table__.indexes)).columns
        ]
        assert REVISION.EXCEPTION_GRAIN == [
            column.name for column in next(iter(CalendarExceptionTable.__table__.indexes)).columns
        ]
        tables = set(inspector.get_table_names())
        assert not tables & {REVISION.DATE_TABLE, REVISION.SESSION_TABLE, REVISION.EVENT_TABLE}
    engine.dispose()


def test_0027_converts_stored_rows_and_repairs_the_header(tmp_path, sqlite_revisions) -> None:
    engine = sqlite_revisions.engine(tmp_path / "calendar-data.sqlite", "0026")
    with engine.connect() as connection:
        config = _config(connection)
        # The header claims 2020 to 2030; the rows cover three weeks.
        calendar_uid = _calendar(connection, "NYSE")
        _seed_nyse_week(connection, calendar_uid)
        connection.commit()

        command.upgrade(config, "0027")

        rules = _rows(connection, REVISION.RULE_TABLE, calendar_uid)
        assert [
            {key: value for key, value in rule.items() if key not in ("uid", "calendar_uid")}
            for rule in rules
        ] == [
            {
                "session_label": "regular",
                "effective_from": dt.date(2024, 11, 11),
                "effective_to": None,
                "weekdays": "1111100",
                "opens_at_local": "09:30:00",
                "closes_at_local": "16:00:00",
                "open_day_offset": 0,
                "close_day_offset": 0,
                "is_primary": True,
            }
        ]
        exceptions = sorted(
            _rows(connection, REVISION.EXCEPTION_TABLE, calendar_uid),
            key=lambda row: row["local_date"],
        )
        assert [
            (
                row["local_date"].isoformat(),
                row["exception_type"],
                row["session_label"],
                row["closes_at_local"],
                row["name"],
                row["source"],
            )
            for row in exceptions
        ] == [
            ("2024-11-28", "CLOSED", "", None, "Thanksgiving", "pandas_market_calendars"),
            ("2024-11-29", "EARLY_CLOSE", "regular", "13:00:00", None, "pandas_market_calendars"),
        ]
        header = next(row for row in _rows(connection, REVISION.CALENDAR_TABLE))
        assert (header["valid_from"], header["valid_to"]) == (
            dt.date(2024, 11, 11),
            dt.date(2024, 12, 1),
        )

        # The stored calendar computes back to what was stored.
        definition = _stored_definition(connection, calendar_uid)
        sessions = compute_sessions(definition, "2024-11-25", "2024-12-01")
        assert [(s.local_date.isoformat(), s.opens_at, s.closes_at) for s in sessions] == [
            ("2024-11-25", dt.datetime(2024, 11, 25, 14, 30, tzinfo=UTC), dt.datetime(2024, 11, 25, 21, 0, tzinfo=UTC)),
            ("2024-11-26", dt.datetime(2024, 11, 26, 14, 30, tzinfo=UTC), dt.datetime(2024, 11, 26, 21, 0, tzinfo=UTC)),
            ("2024-11-27", dt.datetime(2024, 11, 27, 14, 30, tzinfo=UTC), dt.datetime(2024, 11, 27, 21, 0, tzinfo=UTC)),
            ("2024-11-29", dt.datetime(2024, 11, 29, 14, 30, tzinfo=UTC), dt.datetime(2024, 11, 29, 18, 0, tzinfo=UTC)),
        ]
        thanksgiving = compute_dates(definition, "2024-11-28", "2024-11-28")[0]
        assert (thanksgiving.is_holiday, thanksgiving.holiday_name) == (True, "Thanksgiving")
    engine.dispose()


def test_0027_keeps_what_was_stored_not_what_a_library_would_say(
    tmp_path, sqlite_revisions
) -> None:
    """A stored session that differs from the regular week stays as an exception."""

    engine = sqlite_revisions.engine(tmp_path / "calendar-odd.sqlite", "0026")
    with engine.connect() as connection:
        config = _config(connection)
        calendar_uid = _calendar(connection, "DESK", source=None, source_identifier=None)
        _seed_nyse_week(connection, calendar_uid)
        # A later close than the regular one, and a Saturday session.
        _session(connection, calendar_uid, "2024-11-30", "2024-11-30T10:00:00-05:00", "2024-11-30T12:00:00-05:00")
        connection.execute(
            sa.text(
                f"UPDATE {REVISION.DATE_TABLE} SET is_business_day = :flag WHERE local_date = :day"
            ),
            {"flag": True, "day": "2024-11-30"},
        )
        connection.commit()

        command.upgrade(config, "0027")

        saturday = [
            row
            for row in _rows(connection, REVISION.EXCEPTION_TABLE, calendar_uid)
            if row["local_date"] == dt.date(2024, 11, 30)
        ]
        assert [
            (row["exception_type"], row["opens_at_local"], row["closes_at_local"], row["source"])
            for row in saturday
        ] == [("OPEN", "10:00:00", "12:00:00", "user")]
        session = compute_sessions(
            _stored_definition(connection, calendar_uid), "2024-11-30", "2024-11-30"
        )[0]
        assert (session.opens_at, session.closes_at) == (
            dt.datetime(2024, 11, 30, 15, 0, tzinfo=UTC),
            dt.datetime(2024, 11, 30, 17, 0, tzinfo=UTC),
        )
    engine.dispose()


def test_0027_keeps_a_business_day_stored_without_a_session(tmp_path, sqlite_revisions) -> None:
    engine = sqlite_revisions.engine(tmp_path / "calendar-dates.sqlite", "0026")
    with engine.connect() as connection:
        config = _config(connection)
        calendar_uid = _calendar(connection, "SETTLEMENT")
        for day, business in [("2026-01-01", False), ("2026-01-02", True), ("2026-01-05", True)]:
            _date(connection, calendar_uid, day, business=business)
        connection.commit()

        command.upgrade(config, "0027")

        rule = _rows(connection, REVISION.RULE_TABLE, calendar_uid)[0]
        assert (rule["session_label"], rule["opens_at_local"], rule["closes_at_local"]) == (
            "regular",
            None,
            None,
        )
        dates = compute_dates(_stored_definition(connection, calendar_uid), "2026-01-01", "2026-01-05")
        assert [(date.local_date.isoformat(), date.is_business_day) for date in dates] == [
            ("2026-01-01", False),
            ("2026-01-02", True),
            ("2026-01-03", False),
            ("2026-01-04", False),
            ("2026-01-05", True),
        ]
    engine.dispose()


def test_0027_leaves_a_calendar_without_rows_and_drops_calendar_events(
    tmp_path, sqlite_revisions
) -> None:
    engine = sqlite_revisions.engine(tmp_path / "calendar-empty.sqlite", "0026")
    with engine.connect() as connection:
        config = _config(connection)
        calendar_uid = _calendar(connection, "HEADER_ONLY")
        connection.execute(
            _table(connection, REVISION.EVENT_TABLE).insert(),
            {
                "uid": _uid(connection),
                "calendar_uid": calendar_uid,
                "event_date": dt.date(2026, 3, 20),
                "event_type": "EXPIRY",
                "event_label": "",
                "target_type": "",
                "target_identifier": "",
            },
        )
        connection.commit()

        command.upgrade(config, "0027")

        header = _rows(connection, REVISION.CALENDAR_TABLE)[0]
        assert (header["valid_from"], header["valid_to"]) == (dt.date(2020, 1, 1), dt.date(2030, 12, 31))
        assert _rows(connection, REVISION.RULE_TABLE) == []
        assert _rows(connection, REVISION.EXCEPTION_TABLE) == []
        assert REVISION.EVENT_TABLE not in sa.inspect(connection).get_table_names()
    engine.dispose()


def test_0027_stops_before_dropping_when_rows_contradict_each_other(
    tmp_path, sqlite_revisions
) -> None:
    engine = sqlite_revisions.engine(tmp_path / "calendar-contradiction.sqlite", "0026")
    with engine.connect() as connection:
        config = _config(connection)
        calendar_uid = _calendar(connection, "BROKEN")
        _seed_nyse_week(connection, calendar_uid)
        # Thanksgiving is stored as not a business day and also has a session.
        _session(connection, calendar_uid, "2024-11-28", "2024-11-28T09:30:00-05:00", "2024-11-28T16:00:00-05:00")
        connection.commit()

        with pytest.raises(RuntimeError, match="'BROKEN' stores 2024-11-28 as not a business day"):
            command.upgrade(config, "0027")
        connection.rollback()
    engine.dispose()


def test_0027_converts_a_calendar_with_a_timezone_no_database_knows_in_utc() -> None:
    converted = REVISION.convert_calendar(
        unique_identifier="ODD",
        timezone="seed-timezone",
        source=None,
        date_rows=[(dt.date(2026, 1, 1), True, None)],
        session_rows=[
            (
                dt.date(2026, 1, 1),
                "regular",
                dt.datetime(2026, 1, 1, 9, 0),
                dt.datetime(2026, 1, 1, 17, 0),
                True,
            )
        ],
    )

    assert converted["timezone"] == "UTC"
    assert (converted["rules"][0]["opens_at_local"], converted["rules"][0]["closes_at_local"]) == (
        "09:00:00",
        "17:00:00",
    )
    assert converted["exceptions"] == []


def test_0027_refuses_a_session_on_another_day_than_its_regular_week() -> None:
    def instant(day: int, hour: int) -> dt.datetime:
        return dt.datetime(2026, 1, day, hour, tzinfo=UTC)

    with pytest.raises(RuntimeError, match="opens or closes on another day"):
        REVISION.convert_calendar(
            unique_identifier="ODD",
            timezone="UTC",
            source=None,
            date_rows=[],
            session_rows=[
                (dt.date(2026, 1, 5), "regular", instant(5, 9), instant(5, 17), True),
                (dt.date(2026, 1, 6), "regular", instant(6, 9), instant(6, 17), True),
                # Opens the evening before its local date.
                (dt.date(2026, 1, 7), "regular", instant(6, 22), instant(7, 17), True),
            ],
        )


def test_0027_downgrade_restores_the_tables_empty(tmp_path, sqlite_revisions) -> None:
    engine = sqlite_revisions.engine(tmp_path / "calendar-downgrade.sqlite", "0026")
    with engine.connect() as connection:
        config = _config(connection)
        calendar_uid = _calendar(connection, "NYSE")
        _seed_nyse_week(connection, calendar_uid)
        connection.commit()
        command.upgrade(config, "0027")

        command.downgrade(config, "0026")

        tables = set(sa.inspect(connection).get_table_names())
        assert {REVISION.DATE_TABLE, REVISION.SESSION_TABLE, REVISION.EVENT_TABLE} <= tables
        assert not tables & {REVISION.RULE_TABLE, REVISION.EXCEPTION_TABLE}
        assert _rows(connection, REVISION.DATE_TABLE) == []
        columns = {column["name"]: column for column in sa.inspect(connection).get_columns(REVISION.CALENDAR_TABLE)}
        assert not columns["valid_from"]["nullable"]
    engine.dispose()
