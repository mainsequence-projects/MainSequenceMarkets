from __future__ import annotations

import datetime as dt
import os
from typing import Any

import pytest

os.environ["MAIN_SEQUENCE_PROJECT_UID"] = " "
os.environ["MAIN_SEQUENCE_PROJECT_ID"] = " "
os.environ.setdefault("MAINSEQUENCE_ACCESS_TOKEN", "unit-test")
os.environ.setdefault("MAINSEQUENCE_REFRESH_TOKEN", "unit-test")

from msm.models import PortfolioTable
from msm_portfolios.data_nodes.portfolios.storage import PortfolioWeightsStorage, PortfoliosStorage
from msm_portfolios.services import latest_portfolio_weights, portfolio_values


def _compiled_sql(statement: Any) -> str:
    return str(statement.compile(compile_kwargs={"literal_binds": True}))


def test_latest_portfolio_weights_builds_as_of_snapshot_query() -> None:
    calls: list[dict[str, Any]] = []

    def executor(statement: Any, models: tuple[type[Any], ...]) -> dict[str, Any]:
        calls.append(
            {
                "sql": _compiled_sql(statement),
                "models": models,
            }
        )
        return {
            "rows": [
                {
                    "portfolio_uid": "portfolio-uid",
                    "portfolio_identifier": "growth",
                    "time_index": dt.datetime(2026, 1, 2, tzinfo=dt.UTC),
                    "asset_identifier": "asset-a",
                    "weight": 1.0,
                }
            ]
        }

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
    assert calls[0]["models"] == (PortfolioTable, PortfolioWeightsStorage)
    sql = calls[0]["sql"].lower()
    assert "max(" in sql
    assert "<=" in sql
    assert "growth" in calls[0]["sql"]
    assert "income" in calls[0]["sql"]


def test_latest_portfolio_weights_exact_date_does_not_use_latest_subquery() -> None:
    calls: list[str] = []

    def executor(statement: Any, models: tuple[type[Any], ...]) -> list[dict[str, Any]]:
        assert models == (PortfolioTable, PortfolioWeightsStorage)
        calls.append(_compiled_sql(statement))
        return []

    rows = latest_portfolio_weights(
        "growth",
        weights_date=dt.datetime(2026, 1, 3, tzinfo=dt.UTC),
        as_of=False,
        executor=executor,
    )

    assert rows == []
    sql = calls[0].lower()
    assert "max(" not in sql
    assert "2026-01-03" in calls[0]


def test_portfolio_values_builds_latest_only_time_window_query() -> None:
    calls: list[dict[str, Any]] = []

    def executor(statement: Any, models: tuple[type[Any], ...]) -> dict[str, Any]:
        calls.append(
            {
                "sql": _compiled_sql(statement),
                "models": models,
            }
        )
        return {
            "rows": [
                {
                    "portfolio_uid": "portfolio-uid",
                    "portfolio_identifier": "growth",
                    "time_index": dt.datetime(2026, 1, 31, tzinfo=dt.UTC),
                    "close": 101.5,
                    "return": 0.015,
                }
            ]
        }

    rows = portfolio_values(
        ["growth", "income"],
        start=dt.date(2026, 1, 1),
        end=dt.date(2026, 1, 31),
        latest_only=True,
        executor=executor,
    )

    assert rows[0]["portfolio_identifier"] == "growth"
    assert rows[0]["return"] == 0.015
    assert calls[0]["models"] == (PortfolioTable, PortfoliosStorage)
    sql = calls[0]["sql"].lower()
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
        latest_portfolio_weights(["growth", " "], executor=lambda _statement, _models: [])

    with pytest.raises(ValueError, match="positive"):
        portfolio_values("growth", limit=0, executor=lambda _statement, _models: [])

    assert portfolio_values([], executor=lambda _statement, _models: []) == []
