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


def run_calendar_materialization_workflow() -> dict[str, Any]:
    """Create calendar identity rows and materialize date/session rows."""

    print("0. Starting the markets engine with calendar schema.")
    runtime = msm.start_engine(
        models=[
            "Calendar",
            "CalendarDate",
            "CalendarSession",
            "CalendarEvent",
        ],
    )
    print("   Markets engine ready.")

    from msm.api.calendars import Calendar, CalendarType
    from msm.services.calendars import (
        build_always_open_calendar_materialization,
        build_pandas_market_calendar_materialization,
        materialize_calendar_rows,
    )

    valid_from = dt.date(2026, 1, 1)
    valid_to = dt.date(2026, 1, 10)

    print("1. Upserting the XNYS trading calendar identity.")
    xnys = Calendar.upsert(
        unique_identifier="XNYS",
        display_name="New York Stock Exchange",
        calendar_type=CalendarType.TRADING,
        timezone="America/New_York",
        source="pandas_market_calendars",
        source_identifier="NYSE",
        valid_from=valid_from,
        valid_to=valid_to,
        metadata_json={"example": "calendar_materialization_workflow"},
    )
    print(f"   Calendar uid={xnys.uid} unique_identifier={xnys.unique_identifier}")

    print("2. Materializing XNYS dates and regular sessions from pandas_market_calendars.")
    xnys_rows = build_pandas_market_calendar_materialization(
        calendar_uid=xnys.uid,
        source_identifier="NYSE",
        start_date=valid_from,
        end_date=valid_to,
        timezone=xnys.timezone,
    )
    xnys_materialization = materialize_calendar_rows(runtime.context, xnys_rows)
    print(
        "   XNYS rows materialized: "
        f"dates={len(xnys_rows.dates)} sessions={len(xnys_rows.sessions)}"
    )

    print("3. Upserting a CRYPTO_24_7 trading calendar identity.")
    crypto = Calendar.upsert(
        unique_identifier="CRYPTO_24_7",
        display_name="Crypto 24/7",
        calendar_type=CalendarType.TRADING,
        timezone="UTC",
        source="user",
        source_identifier="always_open",
        valid_from=valid_from,
        valid_to=valid_to,
        metadata_json={"example": "calendar_materialization_workflow"},
    )
    print(f"   Calendar uid={crypto.uid} unique_identifier={crypto.unique_identifier}")

    print("4. Materializing CRYPTO_24_7 as an always-open calendar.")
    crypto_rows = build_always_open_calendar_materialization(
        calendar_uid=crypto.uid,
        start_date=valid_from,
        end_date=valid_to,
    )
    crypto_materialization = materialize_calendar_rows(runtime.context, crypto_rows)
    print(
        "   CRYPTO_24_7 rows materialized: "
        f"dates={len(crypto_rows.dates)} sessions={len(crypto_rows.sessions)}"
    )

    print("5. Listing the calendars created by the workflow.")
    calendars = Calendar.filter(unique_identifier_contains="", limit=20)
    for calendar in calendars:
        if calendar.unique_identifier in {"XNYS", "CRYPTO_24_7"}:
            print(
                "   Calendar "
                f"uid={calendar.uid} unique_identifier={calendar.unique_identifier} "
                f"type={calendar.calendar_type}"
            )

    return {
        "xnys_calendar": xnys,
        "xnys_materialization": xnys_materialization,
        "crypto_calendar": crypto,
        "crypto_materialization": crypto_materialization,
        "calendars": calendars,
    }


def main() -> None:
    run_calendar_materialization_workflow()


if __name__ == "__main__":
    main()
