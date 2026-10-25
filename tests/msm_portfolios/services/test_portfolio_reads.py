from __future__ import annotations

import datetime as dt
import os
import uuid
from typing import Any

import pandas as pd
import pytest
from sqlalchemy import Table
from sqlalchemy.sql import visitors

os.environ["MAIN_SEQUENCE_PROJECT_UID"] = " "
os.environ["MAIN_SEQUENCE_PROJECT_ID"] = " "
os.environ.setdefault("MAINSEQUENCE_ACCESS_TOKEN", "unit-test")
os.environ.setdefault("MAINSEQUENCE_REFRESH_TOKEN", "unit-test")

from msm.models import PortfolioDatasetAvailabilityTable, SignalMetadataTable
from msm_portfolios.data_nodes.portfolios.storage import PortfoliosStorage
from msm_portfolios.data_nodes.signals.storage import SignalWeightsStorage
from msm_portfolios.services import (
    latest_portfolio_weights,
    portfolio_values,
    resolve_portfolio_dataset_tables,
    signal_weights,
)

GROWTH_UID = uuid.uuid4()
INCOME_UID = uuid.uuid4()
ALPACA_VALUES = "alpaca-values-table"
ALPACA_WEIGHTS = "alpaca-weights-table"
IBKR_VALUES = "ibkr-values-table"
NOW = dt.datetime(2026, 1, 31, tzinfo=dt.UTC)


def _compiled_sql(statement: Any) -> str:
    return str(statement.compile(compile_kwargs={"literal_binds": True}))


def _referenced_tables(statement: Any) -> set[str]:
    return {element.name for element in visitors.iterate(statement) if isinstance(element, Table)}


def _catalog_row(
    identifier: str,
    *,
    portfolio_uid: uuid.UUID,
    values: str | None = None,
    weights: str | None = None,
    signal: str | None = None,
    signal_uid: str | None = None,
) -> dict[str, Any]:
    return {
        "portfolio_uid": str(portfolio_uid),
        "portfolio_identifier": identifier,
        "signal_uid": signal_uid,
        "values_meta_table_uid": values,
        "weights_meta_table_uid": weights,
        "signal_meta_table_uid": signal,
        "signal_metadata_meta_table_uid": None,
    }


class _Recorder:
    """Execute catalog lookups from fixed rows and record every other statement."""

    def __init__(self, catalog_rows: list[dict[str, Any]], core_rows: Any = None) -> None:
        self.catalog_rows = catalog_rows
        self.core_rows = core_rows if core_rows is not None else []
        self.core_sql: list[str] = []
        self.catalog_sql: list[str] = []

    def __call__(self, statement: Any) -> Any:
        tables = _referenced_tables(statement)
        if PortfolioDatasetAvailabilityTable.__table__.name in tables:
            self.catalog_sql.append(_compiled_sql(statement))
            return {"rows": self.catalog_rows}
        self.core_sql.append(_compiled_sql(statement))
        return self.core_rows


class _FakeReader:
    """Stand in for ``TimeIndexTableRef`` with a frame indexed like the real reader."""

    def __init__(self, rows: list[dict[str, Any]], *, index_names: list[str]) -> None:
        self.rows = rows
        self.index_names = index_names
        self.calls: list[dict[str, Any]] = []
        self.last_observation_calls: list[dict[str, Any]] = []

    def _frame(self, rows: list[dict[str, Any]]) -> pd.DataFrame:
        if not rows:
            return pd.DataFrame()
        frame = pd.DataFrame(rows)
        frame["time_index"] = pd.to_datetime(frame["time_index"], utc=True)
        return frame.set_index(self.index_names)

    def get_df_between_dates(self, **kwargs: Any) -> pd.DataFrame:
        self.calls.append(kwargs)
        selected = self.rows
        filters = kwargs.get("dimension_filters") or {}
        for dimension, allowed in filters.items():
            selected = [row for row in selected if row[dimension] in allowed]
        start = kwargs.get("start_date")
        end = kwargs.get("end_date")
        if start is not None:
            selected = [row for row in selected if row["time_index"] >= start]
        if end is not None:
            selected = [row for row in selected if row["time_index"] <= end]
        return self._frame(selected)

    def get_last_observation(self, **kwargs: Any) -> pd.DataFrame:
        self.last_observation_calls.append(kwargs)
        selected = self.rows
        for dimension, allowed in (kwargs.get("dimension_filters") or {}).items():
            selected = [row for row in selected if row[dimension] in allowed]
        latest: dict[tuple, dict[str, Any]] = {}
        for row in selected:
            key = tuple(row[name] for name in self.index_names if name != "time_index")
            if key not in latest or row["time_index"] > latest[key]["time_index"]:
                latest[key] = row
        return self._frame(list(latest.values()))


def test_latest_portfolio_weights_builds_as_of_snapshot_query() -> None:
    executor = _Recorder(
        catalog_rows=[],
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
    assert len(executor.catalog_sql) == 1
    assert len(executor.core_sql) == 1
    sql = executor.core_sql[0].lower()
    assert "max(" in sql
    assert "<=" in sql
    assert "growth" in executor.core_sql[0]
    assert "income" in executor.core_sql[0]


def test_latest_portfolio_weights_exact_date_does_not_use_latest_subquery() -> None:
    executor = _Recorder(catalog_rows=[])

    rows = latest_portfolio_weights(
        "growth",
        weights_date=dt.datetime(2026, 1, 3, tzinfo=dt.UTC),
        as_of=False,
        executor=executor,
    )

    assert rows == []
    sql = executor.core_sql[0].lower()
    assert "max(" not in sql
    assert "2026-01-03" in executor.core_sql[0]


def test_portfolio_values_builds_latest_only_time_window_query() -> None:
    executor = _Recorder(
        catalog_rows=[],
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
    sql = executor.core_sql[0].lower()
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


def test_catalog_resolution_joins_portfolio_catalog_and_signal_metadata() -> None:
    executor = _Recorder(
        catalog_rows=[
            {
                **_catalog_row("growth", portfolio_uid=GROWTH_UID, values=ALPACA_VALUES),
                "signal_uid": "growth-signal",
                "signal_metadata_meta_table_uid": "signal-table-from-metadata",
            }
        ]
    )

    resolved = resolve_portfolio_dataset_tables(["growth", "unknown"], executor=executor)

    assert set(resolved) == {"growth"}
    assert resolved["growth"].portfolio_uid == GROWTH_UID
    assert resolved["growth"].values_meta_table_uid == ALPACA_VALUES
    assert resolved["growth"].weights_meta_table_uid is None
    # The catalog's signal table wins; SignalMetadata.meta_table_uid is the fallback.
    assert resolved["growth"].signal_meta_table_uid == "signal-table-from-metadata"
    sql = executor.catalog_sql[0]
    assert "LEFT OUTER JOIN" in sql
    assert PortfolioDatasetAvailabilityTable.__table__.name in sql
    assert SignalMetadataTable.__table__.name in sql


def test_portfolio_without_catalog_row_falls_back_to_core_tables_without_reader() -> None:
    executor = _Recorder(
        catalog_rows=[_catalog_row("growth", portfolio_uid=GROWTH_UID)],
        core_rows={"rows": [{"portfolio_uid": str(GROWTH_UID), "portfolio_identifier": "growth"}]},
    )
    readers: list[str] = []

    rows = portfolio_values("growth", executor=executor, dataset_reader=readers.append)

    assert rows == [{"portfolio_uid": str(GROWTH_UID), "portfolio_identifier": "growth"}]
    assert readers == []
    assert PortfoliosStorage.__table__.name in executor.core_sql[0]


def test_multi_portfolio_values_read_each_instance_once_and_merge_with_core_rows() -> None:
    frames = {
        ALPACA_VALUES: _FakeReader(
            [
                {"time_index": NOW, "portfolio_identifier": "growth", "close": 101.0, "return": 0.01,
                 "calculated_close": 101.0, "close_time": NOW, "provider_only": "ignored"},
                {"time_index": NOW - dt.timedelta(days=1), "portfolio_identifier": "growth",
                 "close": 100.0, "return": 0.0, "calculated_close": 100.0, "close_time": None},
                {"time_index": NOW, "portfolio_identifier": "balanced", "close": 50.0, "return": 0.02,
                 "calculated_close": 50.0, "close_time": NOW},
                {"time_index": NOW, "portfolio_identifier": "not-requested", "close": 1.0,
                 "return": 0.0, "calculated_close": 1.0, "close_time": NOW},
            ],
            index_names=["time_index", "portfolio_identifier"],
        ),
        IBKR_VALUES: _FakeReader(
            [
                {"time_index": NOW, "portfolio_identifier": "income", "close": 7.0, "return": 0.03,
                 "calculated_close": 7.0, "close_time": NOW},
            ],
            index_names=["time_index", "portfolio_identifier"],
        ),
    }
    balanced_uid = uuid.uuid4()
    core_uid = uuid.uuid4()
    executor = _Recorder(
        catalog_rows=[
            _catalog_row("growth", portfolio_uid=GROWTH_UID, values=ALPACA_VALUES),
            _catalog_row("balanced", portfolio_uid=balanced_uid, values=ALPACA_VALUES),
            _catalog_row("income", portfolio_uid=INCOME_UID, values=IBKR_VALUES),
            _catalog_row("legacy", portfolio_uid=core_uid),
        ],
        core_rows={
            "rows": [
                {"portfolio_uid": str(core_uid), "portfolio_identifier": "legacy",
                 "time_index": NOW, "close": 3.0, "return": 0.0, "calculated_close": 3.0,
                 "close_time": NOW}
            ]
        },
    )
    requested: list[str] = []

    def reader(meta_table_uid: str) -> _FakeReader:
        requested.append(meta_table_uid)
        return frames[meta_table_uid]

    rows = portfolio_values(
        ["growth", "income", "balanced", "legacy"],
        start=NOW - dt.timedelta(days=5),
        end=NOW,
        executor=executor,
        dataset_reader=reader,
    )

    # Each instance is read once, with both of its portfolios in one filter.
    assert sorted(requested) == [ALPACA_VALUES, IBKR_VALUES]
    assert frames[ALPACA_VALUES].calls[0]["dimension_filters"] == {
        "portfolio_identifier": ["growth", "balanced"]
    }
    assert frames[ALPACA_VALUES].calls[0]["columns"] == [
        "time_index", "portfolio_identifier", "close", "return", "calculated_close", "close_time",
    ]
    # The core table was read once, only for the uncatalogued portfolio.
    assert len(executor.core_sql) == 1
    assert "legacy" in executor.core_sql[0] and "growth" not in executor.core_sql[0]
    # One merged, ordered result with contract columns only and the portfolio uid attached.
    assert [(row["portfolio_identifier"], row["time_index"]) for row in rows] == [
        ("balanced", NOW),
        ("growth", NOW - dt.timedelta(days=1)),
        ("growth", NOW),
        ("income", NOW),
        ("legacy", NOW),
    ]
    growth = next(row for row in rows if row["portfolio_identifier"] == "growth")
    assert growth["portfolio_uid"] == GROWTH_UID
    assert "provider_only" not in growth
    assert rows[1]["close_time"] is None
    assert isinstance(rows[0]["time_index"], dt.datetime)


def test_multi_portfolio_values_latest_only_and_limit_apply_across_instances() -> None:
    reader = _FakeReader(
        [
            {"time_index": NOW - dt.timedelta(days=1), "portfolio_identifier": "growth", "close": 1.0},
            {"time_index": NOW, "portfolio_identifier": "growth", "close": 2.0},
        ],
        index_names=["time_index", "portfolio_identifier"],
    )
    executor = _Recorder(
        catalog_rows=[_catalog_row("growth", portfolio_uid=GROWTH_UID, values=ALPACA_VALUES)]
    )

    rows = portfolio_values(
        "growth", latest_only=True, limit=5, executor=executor, dataset_reader=lambda _uid: reader
    )

    assert [row["close"] for row in rows] == [2.0]
    assert executor.core_sql == []


def test_latest_portfolio_weights_reads_catalogued_instance_by_last_observation() -> None:
    reader = _FakeReader(
        [
            {"time_index": NOW - dt.timedelta(days=1), "portfolio_identifier": "growth",
             "asset_identifier": "a", "weight": 0.5},
            {"time_index": NOW - dt.timedelta(days=1), "portfolio_identifier": "growth",
             "asset_identifier": "b", "weight": 0.5},
            {"time_index": NOW, "portfolio_identifier": "growth", "asset_identifier": "a",
             "weight": 1.0},
        ],
        index_names=["time_index", "portfolio_identifier", "asset_identifier"],
    )
    executor = _Recorder(
        catalog_rows=[_catalog_row("growth", portfolio_uid=GROWTH_UID, weights=ALPACA_WEIGHTS)]
    )

    rows = latest_portfolio_weights("growth", executor=executor, dataset_reader=lambda _uid: reader)

    # Only the latest snapshot survives even though asset ``b`` was last seen earlier.
    assert [(row["asset_identifier"], row["weight"]) for row in rows] == [("a", 1.0)]
    assert rows[0]["portfolio_uid"] == GROWTH_UID
    assert reader.last_observation_calls[0]["dimension_filters"] == {"portfolio_identifier": ["growth"]}
    assert executor.core_sql == []


def test_latest_portfolio_weights_as_of_and_exact_read_catalogued_instance() -> None:
    reader = _FakeReader(
        [
            {"time_index": NOW - dt.timedelta(days=2), "portfolio_identifier": "growth",
             "asset_identifier": "a", "weight": 0.2},
            {"time_index": NOW, "portfolio_identifier": "growth", "asset_identifier": "a",
             "weight": 1.0},
        ],
        index_names=["time_index", "portfolio_identifier", "asset_identifier"],
    )
    executor = _Recorder(
        catalog_rows=[_catalog_row("growth", portfolio_uid=GROWTH_UID, weights=ALPACA_WEIGHTS)]
    )

    as_of = latest_portfolio_weights(
        "growth",
        weights_date=NOW - dt.timedelta(days=1),
        executor=executor,
        dataset_reader=lambda _uid: reader,
    )
    exact = latest_portfolio_weights(
        "growth",
        weights_date=NOW,
        as_of=False,
        executor=executor,
        dataset_reader=lambda _uid: reader,
    )
    missing = latest_portfolio_weights(
        "growth",
        weights_date=NOW - dt.timedelta(days=1),
        as_of=False,
        executor=executor,
        dataset_reader=lambda _uid: reader,
    )

    assert [row["weight"] for row in as_of] == [0.2]
    assert [row["weight"] for row in exact] == [1.0]
    assert missing == []
    assert reader.calls[0]["end_date"] == NOW - dt.timedelta(days=1)
    assert reader.calls[1]["start_date"] == reader.calls[1]["end_date"] == NOW


def test_signal_weights_fall_back_to_core_table_without_metadata_reference() -> None:
    calls: list[str] = []

    def executor(statement: Any) -> dict[str, Any]:
        calls.append(_compiled_sql(statement))
        if SignalMetadataTable.__table__.name in _referenced_tables(statement):
            return {"rows": [{"meta_table_uid": None}]}
        return {"rows": [{"time_index": NOW, "signal_uid": "sig", "asset_identifier": "a",
                          "signal_weight": 1.0}]}

    rows = signal_weights("sig", order="asc", limit=10, executor=executor,
                          dataset_reader=lambda _uid: pytest.fail("reader must not be used"))

    assert rows[0]["signal_weight"] == 1.0
    assert SignalWeightsStorage.__table__.name in calls[1]
    assert "LIMIT 10" in calls[1]


def test_signal_weights_read_catalogued_instance_by_signal_uid() -> None:
    reader = _FakeReader(
        [
            {"time_index": NOW - dt.timedelta(days=1), "signal_uid": "sig", "asset_identifier": "a",
             "signal_weight": 0.5},
            {"time_index": NOW, "signal_uid": "sig", "asset_identifier": "a", "signal_weight": 1.0},
            {"time_index": NOW, "signal_uid": "other", "asset_identifier": "a", "signal_weight": 9.0},
        ],
        index_names=["time_index", "signal_uid", "asset_identifier"],
    )
    requested: list[str] = []

    def reader_for(uid: str) -> _FakeReader:
        requested.append(uid)
        return reader

    rows = signal_weights(
        "sig",
        meta_table_uid="signal-instance",
        order="desc",
        limit=1,
        executor=lambda _statement: pytest.fail("the catalogued table is read by uid, not SQL"),
        dataset_reader=reader_for,
    )

    assert requested == ["signal-instance"]
    assert [(row["time_index"], row["signal_weight"]) for row in rows] == [(NOW, 1.0)]
    assert reader.calls[0]["dimension_filters"] == {"signal_uid": ["sig"]}
