from __future__ import annotations

import datetime as dt
import os
import sys
from pathlib import Path
from typing import Any

if __package__ in {None, ""}:
    _PROJECT_ROOT = Path(__file__).resolve().parents[3]
    sys.path[:0] = [str(_PROJECT_ROOT / "src"), str(_PROJECT_ROOT)]

from examples.msm.platform.bootstrap import (
    EXAMPLE_METATABLE_NAMESPACE,
    EXAMPLE_NAMESPACE_ENV,
)

os.environ.setdefault(EXAMPLE_NAMESPACE_ENV, EXAMPLE_METATABLE_NAMESPACE)

import msm

CUSTOM_NYSE_UNIQUE_IDENTIFIER = "EXAMPLE_CUSTOM_NYSE"
CRYPTO_UNIQUE_IDENTIFIER = "CRYPTO_24_7"
DESK_UNIQUE_IDENTIFIER = "EXAMPLE_DESK_HOURS"

WINDOW_START = dt.date(2024, 12, 23)
WINDOW_END = dt.date(2024, 12, 31)


def _print_sessions(sessions: list[Any]) -> None:
    for session in sessions:
        flag = " early close" if session.is_early_close else ""
        print(
            f"   {session.local_date} {session.session_label}: "
            f"{session.opens_at:%Y-%m-%d %H:%M} -> {session.closes_at:%Y-%m-%d %H:%M} UTC{flag}"
        )


def run_calendar_rules_and_exceptions_workflow() -> dict[str, Any]:
    """Create calendars as session rules and exceptions, and read computed sessions."""

    print("0. Starting the markets engine with the calendar schema.")
    msm.start_engine(models=["Calendar", "CalendarSessionRule", "CalendarException"])
    print("   Markets engine ready.")

    from msm.api.calendars import (
        Calendar,
        CalendarException,
        CalendarSessionRule,
        CalendarType,
    )

    print("1. Storing the library's NYSE calendar under a custom name.")
    custom_nyse = Calendar.create_from_pandas_calendar(
        "NYSE",
        CUSTOM_NYSE_UNIQUE_IDENTIFIER,
        display_name="Example Custom NYSE",
        metadata_json={"example": "calendar_rules_and_exceptions_workflow"},
    )
    print(
        f"   Calendar uid={custom_nyse.uid} unique_identifier={custom_nyse.unique_identifier} "
        f"source={custom_nyse.source}:{custom_nyse.source_identifier} "
        f"range={custom_nyse.valid_from}..{custom_nyse.valid_to}"
    )

    print(f"2. Reading its sessions from {WINDOW_START} to {WINDOW_END}.")
    library_sessions = Calendar.sessions(custom_nyse.uid, WINDOW_START, WINDOW_END)
    _print_sessions(library_sessions)

    print("3. Correcting it by hand: a full day on 2024-12-24, closed on 2024-12-31.")
    # A row written here has source="user". A date with a user row is computed
    # from its user rows alone, so the OPEN row cancels the library's early close.
    user_exceptions = CalendarException.upsert_many(
        [
            {
                "calendar_uid": custom_nyse.uid,
                "local_date": dt.date(2024, 12, 24),
                "exception_type": "OPEN",
            },
            {
                "calendar_uid": custom_nyse.uid,
                "local_date": dt.date(2024, 12, 31),
                "exception_type": "CLOSED",
                "name": "Desk closed",
            },
        ]
    )
    for exception in user_exceptions:
        print(
            f"   Exception {exception.local_date} {exception.exception_type} "
            f"source={exception.source}"
        )
    corrected_sessions = Calendar.sessions(custom_nyse.uid, WINDOW_START, WINDOW_END)
    _print_sessions(corrected_sessions)
    print(
        "   2024-12-31 is a business day: "
        f"{Calendar.is_business_day(custom_nyse.uid, dt.date(2024, 12, 31))}"
    )

    print("4. Writing the calendar again from the library keeps the user exceptions.")
    Calendar.create_from_pandas_calendar("NYSE", CUSTOM_NYSE_UNIQUE_IDENTIFIER)
    kept = CalendarException.filter(calendar_uid=custom_nyse.uid, source="user")
    print(f"   User exceptions kept: {len(kept)}")

    print("5. Creating a 24/7 calendar: one rule, no exceptions.")
    crypto = Calendar.create_from_pandas_calendar(
        "24/7",
        CRYPTO_UNIQUE_IDENTIFIER,
        display_name="Crypto 24/7",
    )
    for rule in CalendarSessionRule.filter(calendar_uid=crypto.uid):
        print(
            f"   Rule weekdays={rule.weekdays} opens={rule.opens_at_local} "
            f"closes={rule.closes_at_local} close_day_offset={rule.close_day_offset}"
        )
    crypto_sessions = Calendar.sessions(crypto.uid, dt.date(2026, 1, 3), dt.date(2026, 1, 4))
    _print_sessions(crypto_sessions)

    print("6. Writing a calendar by hand with one session rule.")
    desk = Calendar.upsert(
        unique_identifier=DESK_UNIQUE_IDENTIFIER,
        display_name="Example Desk Hours",
        calendar_type=CalendarType.CUSTOM,
        timezone="Europe/London",
        metadata_json={"example": "calendar_rules_and_exceptions_workflow"},
    )
    desk_rule = CalendarSessionRule.upsert(
        calendar_uid=desk.uid,
        effective_from=dt.date(2026, 1, 1),
        weekdays="1111100",
        opens_at_local="09:00",
        closes_at_local="17:30",
    )
    print(
        f"   Calendar uid={desk.uid} rule weekdays={desk_rule.weekdays} "
        f"{desk_rule.opens_at_local}-{desk_rule.closes_at_local} {desk.timezone}"
    )
    desk_sessions = Calendar.sessions(desk.uid, dt.date(2026, 1, 5), dt.date(2026, 1, 11))
    _print_sessions(desk_sessions)

    return {
        "custom_nyse_calendar": custom_nyse,
        "library_sessions": library_sessions,
        "user_exceptions": user_exceptions,
        "corrected_sessions": corrected_sessions,
        "crypto_calendar": crypto,
        "crypto_sessions": crypto_sessions,
        "desk_calendar": desk,
        "desk_rule": desk_rule,
        "desk_sessions": desk_sessions,
    }


def main() -> None:
    run_calendar_rules_and_exceptions_workflow()


if __name__ == "__main__":
    main()
