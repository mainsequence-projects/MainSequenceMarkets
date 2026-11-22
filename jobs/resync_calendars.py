"""Main Sequence Job: write stored calendars again from the installed library (ADR 0055).

A stored calendar holds what pandas-market-calendars knew when it was written. A
newer library version can know a new closure, a new holiday or new regular hours.
Taking them is the user's decision, so a person runs this Job; the deployment
workflow does not, and the Markets API never writes a calendar again by itself.

Arguments of one manual run:

    resync_calendars.py NYSE CustomNYSE     write these calendars again
    resync_calendars.py                     every calendar the adapter wrote
    resync_calendars.py --dry-run [...]     print the same report and write nothing
    resync_calendars.py --valid-from DATE   first date to write, instead of 1990-01-01
    resync_calendars.py --list-all          list every exception added and removed

Every ``user`` exception is kept. The Job exits with 1 when a calendar fails;
the calendars before it are written and the ones after it are still tried.
"""

import argparse
import sys

from metatables.endpoint import api_endpoint_scope

CALENDAR_MODELS = ("Calendar", "CalendarSessionRule", "CalendarException")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="resync_calendars.py",
        description="Write stored calendars again from the installed pandas-market-calendars.",
    )
    parser.add_argument(
        "calendars",
        nargs="*",
        metavar="CALENDAR",
        help="unique_identifier of a calendar to write again; none means every adapter calendar",
    )
    parser.add_argument("--dry-run", action="store_true", help="report and write nothing")
    parser.add_argument("--valid-from", default=None, help="first date to write, as YYYY-MM-DD")
    parser.add_argument(
        "--list-all", action="store_true", help="list every exception added and removed"
    )
    arguments = parser.parse_args(argv)

    import msm
    from msm.services.calendars import (
        describe_calendar_sync,
        list_adapter_calendars,
        resync_adapter_calendars,
    )

    mode = "dry run, nothing is written" if arguments.dry_run else "writing"
    print(f"Calendar re-sync ({mode})", flush=True)
    failures = 0
    # Pin the Environment's API for the whole run and allow its runtime to wake.
    with api_endpoint_scope(discovery_timeout=300):
        runtime = msm.start_engine(models=list(CALENDAR_MODELS))
        # One calendar at a time, so a failure names its calendar and the rest still run.
        targets = arguments.calendars or [
            calendar["unique_identifier"] for calendar in list_adapter_calendars(runtime.context)
        ]
        if not targets:
            print("No calendar was written from pandas_market_calendars.", flush=True)
        for unique_identifier in targets:
            try:
                results = resync_adapter_calendars(
                    runtime.context,
                    unique_identifiers=[unique_identifier],
                    valid_from=arguments.valid_from,
                    dry_run=arguments.dry_run,
                )
            except Exception as error:  # noqa: BLE001 - reported per calendar, then the Job fails
                failures += 1
                print(f"{unique_identifier}: FAILED: {type(error).__name__}: {error}", flush=True)
                continue
            for result in results:
                limit = None if arguments.list_all else 20
                print("\n".join(describe_calendar_sync(result, list_limit=limit)), flush=True)
    if failures:
        print(f"{failures} calendar(s) failed.", flush=True)
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
