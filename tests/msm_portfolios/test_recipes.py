"""The recipes and the publishing engine nodes under both row backends (ADR 0060, decisions 5, 6).

Each test migrates a fresh SQLite file and runs the series operations through MetaTables'
own server code for the local runtime (`make_sqlite_markets`). Under ``remote`` the same
calls reach an in-process Markets API, whose caller is a branch's workload, so the rows a
producer creates are managed by that branch. The rebalance state and prices are the
producer's own: here they are in-memory sources, and nothing leaves the process.
"""

from __future__ import annotations

import datetime as dt
import json
import uuid
from types import SimpleNamespace

import pandas as pd
import pytest
from fastapi.testclient import TestClient

from msm.api.remote import use_remote_backend, use_runtime_backend
from msm_portfolios import recipes
from msm_portfolios.api import (
    SignalMetadata,
    SignalWeightsSeries,
)
from msm_portfolios.contrib.signals import ApplicationWeights, ApplicationWeightsConfig
from msm_portfolios.configuration import (
    BacktestingWeightsConfig,
    PortfolioBuildConfiguration,
    PortfolioConfiguration,
    PortfolioExecutionConfiguration,
    PortfolioMarketsConfig,
)
from msm_portfolios.time_index.portfolios.rebalance import (
    PortfolioRebalance,
    PortfolioRebalanceStateStorage,
)
from msm_portfolios.rebalance_strategy import ImmediateSignal
from tests.identity.test_pinned_identities import _bound
from tests.msm.repositories.test_sqlite_snapshot_writes import (
    _asset,
    _insert,
    _rows,
    make_sqlite_markets,
)
from tests.msm_portfolios.time_index.test_next_observed_price import PublishedTable

UTC = dt.UTC
T0 = dt.datetime(2026, 3, 2, 21, 0, tzinfo=UTC)
T1 = T0 + dt.timedelta(days=1)
T2 = T0 + dt.timedelta(days=2)
BRANCH = "b7a1c2d3-e4f5-4a6b-8c7d-9e0f1a2b3c4d"


@pytest.fixture(params=["runtime", "remote"])
def markets(request, tmp_path, monkeypatch):
    markets = make_sqlite_markets(tmp_path, monkeypatch)
    for asset in ("AAA", "BBB", "USD"):
        _asset(markets.engine, asset)
    markets.calendar = _insert(markets.engine, "ms_markets__calendar", unique_identifier="XNYS")
    monkeypatch.setattr(
        "msm.bootstrap.resolve_runtime",
        lambda **_kwargs: SimpleNamespace(context=markets.context),
    )
    markets.backend = request.param
    if request.param == "runtime":
        yield markets
        return
    from apps.v1.main import app
    from msm.client import MarketsClient

    monkeypatch.setattr("apps.v1.identity.caller_principal", lambda uid: f"branch:{BRANCH}")
    use_remote_backend(MarketsClient("http://testserver", session=TestClient(app)).backend)
    try:
        yield markets
    finally:
        use_runtime_backend()


def _signal() -> ApplicationWeights:
    return ApplicationWeights.from_signal_configuration(
        ApplicationWeightsConfig(provider="an-application", key="model-a")
    )


# Signals -------------------------------------------------------------------------------------


def test_publish_signal_weights_creates_the_metadata_once_and_publishes(markets) -> None:
    signal = _signal()

    first = recipes.publish_signal_weights(
        signal.signal_uid, {T0: {"AAA": 0.6, "BBB": 0.4}}, description="Model A"
    )
    again = recipes.publish_signal_weights(signal.signal_uid, {T0: {"AAA": 0.6, "BBB": 0.4}})
    closed = signal.publish({T1: {"AAA": 1.0}})

    assert (first.created_metadata, first.written, first.assets) == (True, 2, ("AAA", "BBB"))
    assert (again.created_metadata, again.written, again.skipped) == (False, 0, 2)
    assert (closed.written, closed.first_time, closed.last_time) == (2, T0, T1)
    (metadata,) = SignalMetadata.filter(signal_uid=signal.signal_uid)
    assert metadata.signal_description == "Model A"
    assert metadata.managed_by == (f"branch:{BRANCH}" if markets.backend == "remote" else None)
    with pytest.raises(ValueError, match="at or before this signal's last stored observation"):
        recipes.publish_signal_weights(signal.signal_uid, {T0 - dt.timedelta(days=1): {"AAA": 0.1}})
    with pytest.raises(ValueError, match="never rewritten"):
        recipes.publish_signal_weights(signal.signal_uid, {T0: {"AAA": 0.1}})
    with pytest.raises(ValueError, match="has no timezone"):
        recipes.publish_signal_weights(signal.signal_uid, {dt.datetime(2026, 4, 1): {"AAA": 1.0}})


def test_an_empty_observation_closes_every_held_asset(markets) -> None:
    signal = _signal()
    recipes.publish_signal_weights(signal.signal_uid, {T0: {"AAA": 0.6, "BBB": 0.4}})

    closed = recipes.publish_signal_weights(signal.signal_uid, {T1: {}})

    assert closed.written == 2
    history = recipes.signal_history([signal.signal_uid], latest=1)
    assert history.latest[signal.signal_uid].to_dict(orient="records") == [{"AAA": 0.0, "BBB": 0.0}]


def test_signal_history_answers_bounds_of_many_signals_and_latest_matrices(markets) -> None:
    signal = _signal()
    recipes.publish_signal_weights(
        signal.signal_uid, {T0: {"AAA": 0.6, "BBB": 0.4}, T1: {"AAA": 1.0}, T2: {"BBB": 1.0}}
    )

    history = recipes.signal_history([signal.signal_uid, "never-published"], latest=2)

    assert history.bounds[signal.signal_uid].first_time == T0
    assert history.bounds[signal.signal_uid].last_time == T2
    assert history.bounds["never-published"].row_count == 0
    matrix = history.latest[signal.signal_uid]
    assert list(matrix.index) == [pd.Timestamp(T1), pd.Timestamp(T2)]
    assert matrix.loc[pd.Timestamp(T2)].to_dict() == {"AAA": 0.0, "BBB": 1.0}
    assert history.latest["never-published"].empty


def test_end_signal_deletes_the_weights_and_metadata_in_one_call(markets) -> None:
    signal = _signal()
    recipes.publish_signal_weights(signal.signal_uid, {T0: {"AAA": 1.0}})

    ended = recipes.end_signal(signal.signal_uid)

    assert ended["deleted_weights_count"] == 1
    assert SignalMetadata.filter(signal_uid=signal.signal_uid) == []
    assert SignalWeightsSeries.bounds([signal.signal_uid])[0].row_count == 0


def test_end_signal_is_refused_while_a_portfolio_names_the_signal(markets) -> None:
    signal = _signal()
    recipes.publish_signal_weights(signal.signal_uid, {T0: {"AAA": 1.0}})
    _insert(
        markets.engine,
        "ms_markets__portfolio",
        unique_identifier="names-the-signal",
        calendar_uid=markets.calendar["uid"],
        signal_uid=signal.signal_uid,
    )

    with pytest.raises(ValueError, match="could not be deleted"):
        recipes.end_signal(signal.signal_uid)

    assert SignalWeightsSeries.bounds([signal.signal_uid])[0].row_count == 1


# Portfolios ----------------------------------------------------------------------------------


class Prices(PublishedTable):
    """The producer's own price table: read, never written, by the run."""

    def run(self, **_kwargs):
        return None


class Resolver:
    """The producer's portfolio resolver: one Portfolio row per configuration."""

    def __init__(self, calendar_uid: str) -> None:
        self.calendar_uid = uuid.UUID(calendar_uid)

    def get_or_create_from_configuration_hash(self, **_kwargs):
        from msm.api.portfolios import Portfolio

        existing = Portfolio.get_by_unique_identifier("model-a-portfolio")
        if existing is not None:
            return existing
        return Portfolio.create(
            unique_identifier="model-a-portfolio", calendar_uid=self.calendar_uid
        )


def _prices() -> Prices:
    rows = [
        {"time_index": time, "asset_identifier": asset, "close": price}
        for time, prices in ((T1, {"AAA": 100.0, "BBB": 50.0}), (T2, {"AAA": 110.0, "BBB": 50.0}))
        for asset, price in prices.items()
    ]
    return Prices.build("prices", pd.DataFrame(rows), index=["time_index", "asset_identifier"])


def _configuration(signal: ApplicationWeights) -> PortfolioConfiguration:
    return PortfolioConfiguration(
        portfolio_build_configuration=PortfolioBuildConfiguration(
            valuation_source_instance=_prices(),
            valuation_asset_identifier="USD",
            execution_configuration=PortfolioExecutionConfiguration(commission_fee=0.0),
            backtesting_weights_configuration=BacktestingWeightsConfig(
                signal_weights_instance=signal,
                rebalance_strategy_instance=ImmediateSignal(
                    calendar_events_instance=_prices(), calendar_identifier="XNYS"
                ),
            ),
        ),
        portfolio_markets_configuration=PortfolioMarketsConfig(portfolio_name="model-a-portfolio"),
    )


@pytest.fixture
def rebalance_state(monkeypatch):
    """The producer's private rebalance state: filled at T1, read by the weights node."""

    state = pd.DataFrame(
        [
            {
                "time_index": T1,
                "portfolio_identifier": "model-a-portfolio",
                "rebalance_intent_id": "intent-1",
                "asset_identifier": asset,
                "target_signal_time_index": T0,
                "event_source": "signal",
                "execution_status": "filled",
                "target_weight": weight,
                "weight_before": 0.0,
                "weight_after": weight,
                "executed_weight_delta": weight,
                "remaining_weight_delta": 0.0,
                "execution_price": price,
                "observed_volume": None,
                "strategy_state": json.dumps({}),
            }
            for asset, weight, price in (("AAA", 0.6, 100.0), ("BBB", 0.4, 50.0))
        ]
    )
    runs: list[str] = []
    monkeypatch.setattr(PortfolioRebalance, "run", lambda self, **_kwargs: runs.append("run"))
    monkeypatch.setattr(
        PortfolioRebalance,
        "get_df_between_dates",
        lambda self, **_kwargs: state.set_index(
            ["time_index", "portfolio_identifier", "rebalance_intent_id", "asset_identifier"]
        ),
    )
    with _bound(PortfolioRebalanceStateStorage, "a0000000-0000-4000-8000-0000000000aa"):
        yield runs


def test_run_portfolio_publishes_weights_and_values_once(markets, rebalance_state) -> None:
    signal = _signal()
    configuration = _configuration(signal)
    resolver = Resolver(markets.calendar["uid"])

    with pytest.raises(ValueError, match="has no published observation"):
        recipes.run_portfolio(configuration, portfolio_resolver=resolver)
    recipes.publish_signal_weights(signal.signal_uid, {T0: {"AAA": 0.6, "BBB": 0.4}})
    first = recipes.run_portfolio(configuration, portfolio_resolver=resolver)
    second = recipes.run_portfolio(configuration, portfolio_resolver=resolver)

    assert first.first_rebalance is True
    assert first.weights.written == 2
    assert first.values.written == 2
    assert first.portfolio.signal_uid == signal.signal_uid
    assert (second.first_rebalance, second.weights, second.values) == (False, None, None)
    assert rebalance_state == ["run", "run"]
    values = recipes.portfolio_history("model-a-portfolio")
    assert values.count == 2
    assert list(values.values.index.get_level_values("time_index")) == [
        pd.Timestamp(T2),
        pd.Timestamp(T1),
    ]
    assert values.values["close"].tolist() == pytest.approx([1.06, 1.0])
    weights = recipes.weights_as_of(["model-a-portfolio"], at=T2)
    assert weights["weight"].to_dict() == {
        (pd.Timestamp(T1), "model-a-portfolio", "AAA"): 0.6,
        (pd.Timestamp(T1), "model-a-portfolio", "BBB"): 0.4,
    }
    (row,) = _rows(markets.engine, "SELECT managed_by FROM ms_markets__portfolio")
    assert row["managed_by"] == (f"branch:{BRANCH}" if markets.backend == "remote" else None)


def test_portfolio_preflight_reports_why_a_portfolio_cannot_run(markets) -> None:
    signal = _signal()

    blocked = recipes.portfolio_preflight(_configuration(signal))
    recipes.publish_signal_weights(signal.signal_uid, {T0: {"AAA": 1.0}})
    ready = recipes.portfolio_preflight(_configuration(signal))

    assert blocked.ready is False and "has no published observation" in blocked.reasons[0]
    assert ready.ready is True and ready.signal_first_time == T0


# Private rows --------------------------------------------------------------------------------


def test_delete_private_series_clears_the_producers_rows_in_key_order(tmp_path, monkeypatch):
    from msm_portfolios.time_index.contract_instances import (
        configured_portfolio_calendar_events_storage,
        configured_portfolio_rebalance_state_storage,
    )

    rebalance = configured_portfolio_rebalance_state_storage(
        instance_key="private", namespace="my-app", storage_app="my_app"
    )
    events = configured_portfolio_calendar_events_storage(
        instance_key="private", namespace="my-app", storage_app="my_app"
    )

    def prepare(engine):
        rebalance.__table__.create(engine)
        events.__table__.create(engine)

    markets = make_sqlite_markets(tmp_path, monkeypatch, prepare=prepare)
    _asset(markets.engine, "AAA")
    calendar = _insert(markets.engine, "ms_markets__calendar", unique_identifier="XNYS")
    for identifier in ("kept", "deleted"):
        _insert(
            markets.engine,
            "ms_markets__portfolio",
            unique_identifier=identifier,
            calendar_uid=calendar["uid"],
        )
        _insert(
            markets.engine,
            rebalance.__table__.name,
            time_index=T0,
            portfolio_identifier=identifier,
            asset_identifier="AAA",
            target_signal_time_index=T0,
        )
    _insert(markets.engine, events.__table__.name, time_index=T0, calendar_identifier="XNYS")

    deleted = recipes.delete_private_series(
        [rebalance, events], portfolios=["deleted"], calendars=["XNYS"]
    )

    assert deleted == {rebalance.__table__.name: 1, events.__table__.name: 1}
    remaining = _rows(
        markets.engine, f"SELECT portfolio_identifier FROM {rebalance.__table__.name}"
    )
    assert remaining == [{"portfolio_identifier": "kept"}]
    with pytest.raises(ValueError, match="has none of the columns"):
        recipes.delete_private_series([events], portfolios=["kept"])
