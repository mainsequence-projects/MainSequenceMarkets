from __future__ import annotations

import datetime as dt
import os
from typing import Any

import pytest
from sqlalchemy import Table
from sqlalchemy.sql import visitors

os.environ["MAIN_SEQUENCE_PROJECT_UID"] = " "
os.environ["MAIN_SEQUENCE_PROJECT_ID"] = " "
os.environ.setdefault("MAINSEQUENCE_ACCESS_TOKEN", "unit-test")
os.environ.setdefault("MAINSEQUENCE_REFRESH_TOKEN", "unit-test")

from msm.models import PortfolioTable
from msm_portfolios.time_index.portfolios.storage import PortfoliosStorage
from msm_portfolios.time_index.signals.storage import SignalWeightsStorage
from msm_portfolios.services import (
    latest_portfolio_weights,
    portfolio_values,
    signal_weights,
)

NOW = dt.datetime(2026, 1, 31, tzinfo=dt.UTC)


def _compiled_sql(statement: Any) -> str:
    return str(statement.compile(compile_kwargs={"literal_binds": True}))


def _referenced_tables(statement: Any) -> set[str]:
    return {element.name for element in visitors.iterate(statement) if isinstance(element, Table)}


class _Recorder:
    """Record every statement and answer it with fixed rows."""

    def __init__(self, core_rows: Any = None) -> None:
        self.core_rows = core_rows if core_rows is not None else []
        self.statements: list[str] = []
        self.tables: list[set[str]] = []

    def __call__(self, statement: Any) -> Any:
        self.statements.append(_compiled_sql(statement))
        self.tables.append(_referenced_tables(statement))
        return self.core_rows


def test_latest_portfolio_weights_builds_as_of_snapshot_query() -> None:
    executor = _Recorder(
        core_rows={
            "rows": [
                {
                    "portfolio_uid": "portfolio-uid",
                    "portfolio_identifier": "growth",
                    "time_index": dt.datetime(2026, 1, 2, tzinfo=dt.UTC),
                    "asset_identifier": "asset-a",
                    "weight": 1.0,
                }
            ]
        },
    )

    rows = latest_portfolio_weights(
        ["growth", "income", "growth"],
        weights_date="2026-01-03T00:00:00Z",
        executor=executor,
    )

    assert rows == [
        {
            "portfolio_uid": "portfolio-uid",
            "portfolio_identifier": "growth",
            "time_index": dt.datetime(2026, 1, 2, tzinfo=dt.UTC),
            "asset_identifier": "asset-a",
            "weight": 1.0,
        }
    ]
    assert len(executor.statements) == 1
    sql = executor.statements[0].lower()
    assert "max(" in sql
    assert "<=" in sql
    assert "growth" in executor.statements[0]
    assert "income" in executor.statements[0]


def test_latest_portfolio_weights_exact_date_does_not_use_latest_subquery() -> None:
    executor = _Recorder()

    rows = latest_portfolio_weights(
        "growth",
        weights_date=dt.datetime(2026, 1, 3, tzinfo=dt.UTC),
        as_of=False,
        executor=executor,
    )

    assert rows == []
    sql = executor.statements[0].lower()
    assert "max(" not in sql
    assert "2026-01-03" in executor.statements[0]


def test_portfolio_values_builds_latest_only_time_window_query() -> None:
    executor = _Recorder(
        core_rows={
            "rows": [
                {
                    "portfolio_uid": "portfolio-uid",
                    "portfolio_identifier": "growth",
                    "time_index": dt.datetime(2026, 1, 31, tzinfo=dt.UTC),
                    "close": 101.5,
                    "return": 0.015,
                }
            ]
        },
    )

    rows = portfolio_values(
        ["growth", "income"],
        start=dt.date(2026, 1, 1),
        end=dt.date(2026, 1, 31),
        latest_only=True,
        executor=executor,
    )

    assert rows[0]["portfolio_identifier"] == "growth"
    assert rows[0]["return"] == 0.015
    sql = executor.statements[0].lower()
    assert "max(" in sql
    assert ">=" in sql
    assert "<=" in sql


def test_portfolio_reads_require_explicit_execution_boundary() -> None:
    with pytest.raises(ValueError, match="repository_context"):
        latest_portfolio_weights("growth")

    with pytest.raises(ValueError, match="repository_context"):
        portfolio_values("growth")


def test_portfolio_reads_validate_identifiers_and_limits() -> None:
    with pytest.raises(ValueError, match="non-empty"):
        latest_portfolio_weights(["growth", " "], executor=lambda _statement: [])

    with pytest.raises(ValueError, match="positive"):
        portfolio_values("growth", limit=0, executor=lambda _statement: [])

    assert portfolio_values([], executor=lambda _statement: []) == []


def test_portfolio_reads_name_only_markets_own_tables() -> None:
    """ADR 0060: one statement per read, on Markets' own tables, with no catalog lookup."""

    executor = _Recorder()

    latest_portfolio_weights(["growth", "income"], executor=executor)
    portfolio_values(["growth", "income"], executor=executor)
    signal_weights("sig", executor=executor)

    assert executor.tables == [
        {"ms_markets__portfolioweightsts", PortfolioTable.__table__.name},
        {PortfoliosStorage.__table__.name, PortfolioTable.__table__.name},
        {SignalWeightsStorage.__table__.name},
    ]


def test_signal_weights_read_the_core_table_newest_first() -> None:
    executor = _Recorder(
        core_rows={
            "rows": [
                {"time_index": NOW, "signal_uid": "sig", "asset_identifier": "a",
                 "signal_weight": 1.0}
            ]
        }
    )

    rows = signal_weights("sig", limit=10, executor=executor)

    assert rows[0]["signal_weight"] == 1.0
    assert "LIMIT 10" in executor.statements[0]
    assert "DESC" in executor.statements[0]
