"""jobs/resync_calendars.py writes stored calendars again when a person runs it (ADR 0055)."""

from __future__ import annotations

import datetime as dt
import importlib.util
import warnings
from contextlib import contextmanager
from pathlib import Path
from types import SimpleNamespace

import pytest
import sqlalchemy as sa
import yaml

import metatables
from msm.api.calendars import Calendar
from msm.services.calendars import (
    CalendarSyncResult,
    describe_calendar_sync,
    resync_adapter_calendars,
    sync_pandas_market_calendar,
)
from tests.support.sqlite_markets import serve_row_operations

PROJECT_ROOT = Path(__file__).resolve().parents[3]
JOB_PATH = PROJECT_ROOT / "jobs" / "resync_calendars.py"
WORKFLOW_PATH = PROJECT_ROOT / ".mainsequence" / "workflows" / "ms-markets-api.yaml"


@pytest.fixture
def markets(sqlite_markets, monkeypatch):
    serve_row_operations(monkeypatch, sqlite_markets)
    return sqlite_markets


def _load_job(monkeypatch, context) -> SimpleNamespace:
    """The Job's ``main`` on ``context``, with the API discovery scope observed."""

    state = {"scopes": [], "models": None}

    original = metatables.api_endpoint_scope

    @contextmanager
    def scope(**kwargs):
        # MetaTables opens the same scope around each compiled statement, without a timeout.
        if "discovery_timeout" in kwargs:
            state["scopes"].append(kwargs["discovery_timeout"])
        with original(**kwargs):
            yield

    def start_engine(*, models=None):
        state["models"] = models
        return SimpleNamespace(context=context)

    monkeypatch.setattr(metatables, "api_endpoint_scope", scope)
    monkeypatch.setattr("msm.start_engine", start_engine)
    spec = importlib.util.spec_from_file_location("resync_calendars_job", JOB_PATH)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return SimpleNamespace(main=module.main, state=state)


@pytest.fixture
def job(markets, monkeypatch):
    """The Job's ``main`` on the SQLite runtime."""

    loaded = _load_job(monkeypatch, markets.context)
    return SimpleNamespace(main=loaded.main, state=loaded.state, markets=markets)


@pytest.fixture
def wired_job(monkeypatch):
    """The Job's ``main`` with the re-sync service replaced: what it passes and prints.

    What the service writes is checked on SQLite in
    ``tests/msm/services/calendars/test_sync.py``.
    """

    context = object()
    calls: list[dict] = []

    def resync_adapter_calendars(passed_context, **kwargs):
        assert passed_context is context
        calls.append(kwargs)
        return [
            CalendarSyncResult(
                calendar={
                    "uid": "uid",
                    "unique_identifier": kwargs["unique_identifiers"][0],
                    "source": "pandas_market_calendars",
                    "source_identifier": "NYSE",
                    "valid_from": dt.date(2020, 1, 1),
                    "valid_to": dt.date(2200, 12, 31),
                },
                created=False,
                dry_run=kwargs["dry_run"],
                changed=True,
                source_version="5.5.0",
                previous_source_version="5.5.0",
                previous_valid_from=dt.date(2020, 1, 1),
                previous_valid_to=dt.date(2200, 12, 31),
                exceptions_added=[
                    {
                        "local_date": dt.date(2025, 1, 9),
                        "session_label": "",
                        "exception_type": "CLOSED",
                        "closes_at_local": None,
                        "name": None,
                    }
                ],
            )
        ]

    monkeypatch.setattr(
        "msm.services.calendars.resync_adapter_calendars", resync_adapter_calendars
    )
    loaded = _load_job(monkeypatch, context)
    return SimpleNamespace(main=loaded.main, state=loaded.state, calls=calls)


def _rows(markets, table: str) -> list[dict]:
    with markets.engine.connect() as connection:
        reflected = sa.Table(table, sa.MetaData(), autoload_with=connection)
        return [dict(row) for row in connection.execute(sa.select(reflected)).mappings()]


def _writes(markets) -> int:
    return sum(1 for sql in markets.statements if not sql.lstrip().upper().startswith("SELECT"))


def _create(markets, source_identifier: str, unique_identifier: str, **values) -> str:
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        result = sync_pandas_market_calendar(
            markets.context,
            source_identifier=source_identifier,
            unique_identifier=unique_identifier,
            **values,
        )
    return str(result.calendar["uid"])


def test_the_job_writes_the_named_calendars_and_prints_what_changed(wired_job, capsys) -> None:
    assert wired_job.main(["CustomNYSE", "--valid-from", "2020-01-01"]) == 0

    output = capsys.readouterr().out
    assert "Calendar re-sync (writing)" in output
    assert "CustomNYSE (pandas_market_calendars NYSE): written" in output
    assert "exceptions added: 1" in output
    assert "+ 2025-01-09 CLOSED" in output
    assert wired_job.calls == [
        {"unique_identifiers": ["CustomNYSE"], "valid_from": "2020-01-01", "dry_run": False}
    ]
    assert wired_job.state == {
        "scopes": [300],
        "models": ["Calendar", "CalendarSessionRule", "CalendarException"],
    }


def test_a_dry_run_prints_the_same_report_and_writes_nothing(wired_job, capsys) -> None:
    assert wired_job.main(["--dry-run", "--valid-from", "2020-01-01", "NYSE"]) == 0

    output = capsys.readouterr().out
    assert "Calendar re-sync (dry run, nothing is written)" in output
    assert "NYSE (pandas_market_calendars NYSE): would be written" in output
    assert "+ 2025-01-09 CLOSED" in output
    assert wired_job.calls == [
        {"unique_identifiers": ["NYSE"], "valid_from": "2020-01-01", "dry_run": True}
    ]


def test_without_names_the_job_takes_every_adapter_calendar_and_no_other(job, capsys) -> None:
    _create(job.markets, "NYSE", "NYSE", valid_from="2024-01-01")
    _create(job.markets, "24/7", "CRYPTO")
    Calendar.create(unique_identifier="DESK", display_name="Desk", calendar_type="CUSTOM")
    before = _writes(job.markets)

    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        assert job.main([]) == 0

    output = capsys.readouterr().out
    # A calendar that starts after 1990-01-01, as a migrated one does, is taken back to it.
    assert "NYSE (pandas_market_calendars NYSE): written" in output
    assert "range: 2024-01-01 to 2200-12-31 -> 1990-01-01 to 2200-12-31" in output
    assert "... and " in output
    assert "CRYPTO (pandas_market_calendars 24/7): unchanged" in output
    assert "DESK" not in output
    assert _writes(job.markets) > before
    nyse = next(row for row in _rows(job.markets, "ms_markets__calendar") if row["unique_identifier"] == "NYSE")
    assert str(nyse["valid_from"]) == "1990-01-01"


def test_a_calendar_that_fails_is_reported_and_the_others_still_run(job, capsys) -> None:
    _create(job.markets, "24/7", "CRYPTO")
    Calendar.create(unique_identifier="DESK", display_name="Desk", calendar_type="CUSTOM")

    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        assert job.main(["MISSING", "DESK", "CRYPTO"]) == 1

    output = capsys.readouterr().out
    assert "MISSING: FAILED: LookupError: Calendar 'MISSING' was not found." in output
    assert "DESK: FAILED: ValueError: Calendar 'DESK' was not written from pandas_market_calendars" in output
    assert "CRYPTO (pandas_market_calendars 24/7): unchanged" in output
    assert "2 calendar(s) failed." in output


def test_named_calendars_are_checked_before_anything_is_written(markets) -> None:
    _create(markets, "24/7", "CRYPTO")
    before = _writes(markets)

    with pytest.raises(LookupError):
        resync_adapter_calendars(markets.context, unique_identifiers=["CRYPTO", "MISSING"])
    assert _writes(markets) == before


def test_the_report_lists_changes_up_to_a_limit() -> None:
    def exception(day: int) -> dict:
        return {
            "local_date": dt.date(2030, 1, day),
            "session_label": "regular",
            "exception_type": "EARLY_CLOSE",
            "closes_at_local": "13:00:00",
            "name": None,
        }

    result = CalendarSyncResult(
        calendar={
            "uid": "uid",
            "unique_identifier": "NYSE",
            "source": "pandas_market_calendars",
            "source_identifier": "NYSE",
            "valid_from": dt.date(1990, 1, 1),
            "valid_to": dt.date(2200, 12, 31),
        },
        created=False,
        dry_run=True,
        changed=True,
        source_version="5.5.0",
        previous_source_version="5.4.0",
        previous_valid_from=dt.date(2017, 12, 2),
        previous_valid_to=dt.date(2027, 9, 10),
        rules_changed=True,
        exceptions_added=[exception(day) for day in range(1, 6)],
        exceptions_removed=[{**exception(7), "exception_type": "CLOSED", "session_label": "", "closes_at_local": None, "name": "Old Holiday"}],
    )

    assert describe_calendar_sync(result, list_limit=2) == [
        "NYSE (pandas_market_calendars NYSE): would be written",
        "  library: 5.4.0 -> 5.5.0",
        "  range: 2017-12-02 to 2027-09-10 -> 1990-01-01 to 2200-12-31",
        "  session rules: changed",
        "  exceptions added: 5",
        "    + 2030-01-01 EARLY_CLOSE regular closes 13:00:00",
        "    + 2030-01-02 EARLY_CLOSE regular closes 13:00:00",
        "    ... and 3 more",
        "  exceptions removed: 1",
        "    - 2030-01-07 CLOSED (Old Holiday)",
    ]
    assert len(describe_calendar_sync(result, list_limit=None)) == 12


def test_the_deployment_never_runs_the_job() -> None:
    """The Job is declared, so a person can run it, and no step of the rollout starts it."""

    workflow = yaml.safe_load(WORKFLOW_PATH.read_text())
    job = next(resource for resource in workflow["resources"] if resource["key"] == "resync-calendars")

    assert job["kind"] == "job"
    assert job["spec"]["execution_path"] == "jobs/resync_calendars.py"
    assert "scheduled_command_args" not in job["spec"]
    assert "schedule" not in job["spec"]
    steps = workflow["execution"]["steps"]
    assert not any("resync-calendars" in str(step) for step in steps.values())
