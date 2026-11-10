"""The portfolio updaters write nothing dated at or after ``retired_at`` (ADR 0049)."""

from __future__ import annotations

import datetime as dt
import uuid
from types import SimpleNamespace

import pandas as pd
import pytest

from tests.identity.test_pinned_identities import _bound
from msm_portfolios.retirement import (
    drop_retired_rows,
    end_before_retirement,
    retirement_boundary,
    window_is_empty,
)
from msm_portfolios.time_index.portfolios import PortfoliosUpdater
from msm_portfolios.time_index.portfolios.accounting import PortfolioEngine
from msm_portfolios.time_index.portfolios.rebalance import PortfolioRebalance
from msm_portfolios.time_index.portfolios.storage import PortfolioRebalanceStateStorage
from msm_portfolios.time_index.portfolios.weights import PortfolioWeights

RETIRED_AT = pd.Timestamp("2026-11-10T00:00:00Z")


def test_boundary_reads_retired_at_from_rows_and_mappings() -> None:
    naive = dt.datetime(2026, 11, 10)

    assert retirement_boundary(None) is None
    assert retirement_boundary(SimpleNamespace(retired_at=None)) is None
    assert retirement_boundary(SimpleNamespace(retired_at=naive)) == RETIRED_AT
    assert retirement_boundary({"retired_at": "2026-11-10T00:00:00+00:00"}) == RETIRED_AT


def test_window_end_stops_before_the_boundary_and_keeps_its_type() -> None:
    later_ts = pd.Timestamp("2026-12-01T00:00:00Z")
    later_dt = later_ts.to_pydatetime()

    assert end_before_retirement(later_ts, None) == later_ts
    assert end_before_retirement(later_ts, RETIRED_AT) == RETIRED_AT - pd.Timedelta(1, "ns")
    clamped = end_before_retirement(later_dt, RETIRED_AT)
    assert isinstance(clamped, dt.datetime) and clamped < RETIRED_AT.to_pydatetime()
    earlier = pd.Timestamp("2026-11-01T00:00:00Z")
    assert end_before_retirement(earlier, RETIRED_AT) == earlier
    assert window_is_empty(RETIRED_AT, end_before_retirement(later_ts, RETIRED_AT))


def test_rows_dated_at_or_after_the_boundary_are_dropped() -> None:
    times = pd.to_datetime(
        ["2026-11-09T00:00:00Z", "2026-11-10T00:00:00Z", "2026-11-11T00:00:00Z"], utc=True
    )
    indexed = pd.DataFrame(
        {"value": [1.0, 2.0, 3.0]},
        index=pd.MultiIndex.from_arrays([times, ["p"] * 3], names=["time_index", "portfolio"]),
    )
    flat = indexed.reset_index()

    assert drop_retired_rows(indexed, RETIRED_AT)["value"].tolist() == [1.0]
    assert drop_retired_rows(flat, RETIRED_AT)["value"].tolist() == [1.0]
    assert drop_retired_rows(indexed, None) is indexed


@pytest.fixture
def quiet_logger(monkeypatch) -> None:
    monkeypatch.setattr(
        PortfoliosUpdater,
        "logger",
        property(lambda self: SimpleNamespace(info=lambda *args, **kwargs: None)),
    )


def test_values_updater_returns_before_reading_once_caught_up(quiet_logger) -> None:
    node = object.__new__(PortfoliosUpdater)
    node.target_portfolio = SimpleNamespace(retired_at=RETIRED_AT.to_pydatetime())
    node._latest_portfolio_time_index_value = lambda: RETIRED_AT - pd.Timedelta(1, "us")
    node._valuation_window = lambda latest: (
        pd.Timestamp(latest).to_pydatetime(),
        pd.Timestamp("2026-12-01T00:00:00Z").to_pydatetime(),
    )

    def unexpected(**kwargs):
        raise AssertionError("A caught-up run reads no executed weights.")

    node._executed_weights_between = unexpected

    assert node._calculate_portfolio_workflow_values().empty


def test_values_updater_reads_up_to_the_boundary(quiet_logger) -> None:
    node = object.__new__(PortfoliosUpdater)
    node.target_portfolio = SimpleNamespace(retired_at=RETIRED_AT.to_pydatetime())
    node._latest_portfolio_time_index_value = lambda: None
    start = pd.Timestamp("2026-11-01T00:00:00Z").to_pydatetime()
    node._valuation_window = lambda latest: (start, pd.Timestamp.now(tz="UTC").to_pydatetime())
    window: dict[str, object] = {}

    def executed_weights_between(*, start, end):
        window.update(start=start, end=end)
        return pd.DataFrame()

    node._executed_weights_between = executed_weights_between

    assert node._calculate_portfolio_workflow_values().empty
    assert window["start"] == start
    assert window["end"] < RETIRED_AT.to_pydatetime()


@pytest.mark.parametrize("updater_class", [PortfolioWeights, PortfolioRebalance])
def test_weights_and_rebalance_take_the_boundary_from_their_portfolio(updater_class) -> None:
    node = object.__new__(updater_class)
    node._portfolio = SimpleNamespace(
        unique_identifier=str(uuid.uuid4()),
        retired_at=RETIRED_AT.to_pydatetime(),
    )
    node._portfolio_configuration = None

    assert node._retirement_boundary() == RETIRED_AT


def test_rebalance_writes_no_transition_after_the_boundary() -> None:
    node = object.__new__(PortfolioRebalance)
    node._portfolio_configuration = SimpleNamespace()
    node._portfolio = SimpleNamespace(unique_identifier="retired-sleeve", retired_at=RETIRED_AT)
    node._latest_transition_time_index_value = lambda: RETIRED_AT - pd.Timedelta(1, "ns")
    node._execution_window = lambda latest: (
        pd.Timestamp(latest) + pd.Timedelta(1, "ns"),
        pd.Timestamp("2026-12-01T00:00:00Z"),
    )
    node._resolve_portfolio_identifier = lambda: "retired-sleeve"

    def unexpected():
        raise AssertionError("A caught-up run reads no inputs.")

    node._required_asset_identifiers = unexpected

    with _bound(PortfolioRebalanceStateStorage, str(uuid.uuid4())) as storage:
        node.output_table = storage
        assert node.update().empty


def test_engine_reads_its_portfolio_row_once_for_the_boundary(monkeypatch) -> None:
    from msm.api.portfolios import Portfolio

    asked: list[str] = []

    def get_by_unique_identifier(cls, unique_identifier):
        asked.append(unique_identifier)
        return SimpleNamespace(retired_at=RETIRED_AT)

    monkeypatch.setattr(
        Portfolio, "get_by_unique_identifier", classmethod(get_by_unique_identifier)
    )

    assert PortfolioEngine._retirement_boundary("retired-sleeve") == RETIRED_AT
    assert asked == ["retired-sleeve"]
