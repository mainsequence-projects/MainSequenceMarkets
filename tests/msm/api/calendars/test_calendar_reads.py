"""Inside ``calendar_reads`` each calendar's row, rules and exceptions are read once (#137).

The test stores NYSE from the library on a SQLite DataSource served by MetaTables' own
server code for the local runtime (``sqlite_markets``).
"""

from __future__ import annotations

import datetime as dt

import pytest

from msm.api.calendars import Calendar, calendar_reads
from msm.repositories.operation_count import counting_operations
from tests.support.sqlite_markets import serve_row_operations

WINDOWS = [
    (dt.date(2024, 11, 25), dt.date(2024, 11, 29)),
    (dt.date(2024, 12, 23), dt.date(2024, 12, 31)),
]


@pytest.fixture
def markets(sqlite_markets, monkeypatch):
    serve_row_operations(monkeypatch, sqlite_markets)
    return sqlite_markets


def test_a_block_reads_each_calendar_once_and_computes_the_same_sessions(markets) -> None:
    calendar = Calendar.create_from_pandas_calendar("NYSE")
    with counting_operations() as alone:
        outside = [Calendar.sessions(calendar.uid, *window) for window in WINDOWS]

    with counting_operations() as count, calendar_reads():
        found = Calendar.get_by_unique_identifier("NYSE")
        again = Calendar.get_by_uid(calendar.uid)
        inside = [Calendar.sessions(found.uid, *window) for window in WINDOWS]
        missing = [Calendar.get_by_unique_identifier("XNYS") for _ in range(2)]

    # Outside a block each computation reads the row, the rules and its exceptions.
    assert alone.operations == 6
    # Inside: the row, the rules, every exception, and the missing calendar, once each.
    assert count.operations == 4
    assert inside == outside
    assert any(session.is_early_close for session in inside[0])
    assert again is found
    assert missing == [None, None]


def test_blocks_nest_and_a_new_block_reads_again(markets) -> None:
    Calendar.create_from_pandas_calendar("NYSE")

    with counting_operations() as count:
        with calendar_reads():
            Calendar.get_by_unique_identifier("NYSE")
            with calendar_reads():
                Calendar.get_by_unique_identifier("NYSE")
        with calendar_reads():
            Calendar.get_by_unique_identifier("NYSE")

    assert count.operations == 2
