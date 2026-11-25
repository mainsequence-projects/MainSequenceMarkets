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
from sqlalchemy import MetaData
from sqlalchemy.orm import DeclarativeBase

from metatables import sqlalchemy_naming_convention
from msm.api.remote import use_remote_backend, use_runtime_backend
from msm_portfolios import recipes
from msm_portfolios.api import (
    SignalMetadata,
    SignalWeightsSeries,
)
from msm_portfolios.contrib.signals import (
    ApplicationWeights,
    ApplicationWeightsConfig,
    AUIDWeight,
    FixedWeights,
    FixedWeightsConfig,
)
from msm_portfolios.accounting import (
    MarketPriceValuationModel,
    PortfolioAccountingConfiguration,
)
from msm_portfolios.configuration import (
    BacktestingWeightsConfig,
    PortfolioBuildConfiguration,
    PortfolioConfiguration,
    PortfolioMarketsConfig,
)
from msm_portfolios.time_index.portfolios.accounting import PortfolioEngine
from msm_portfolios.time_index.portfolios.rebalance import (
    PortfolioRebalance,
    PortfolioRebalanceStateStorage,
)
from msm_portfolios.time_index.portfolios.storage import PortfolioEventLedgerStorage
from msm_portfolios.rebalance_strategy import ImmediateSignal
from msm_portfolios.time_index import SignalWeights, compute_portfolio_configuration_hash
from msm_portfolios.time_index.signals.storage import SignalWeightsInstance
from tests.support.metatables_runs import serve_joined_runs
from tests.support.pinned_identities import _bound
from tests.support.rebalance import PublishedTable
from tests.support.sqlite_markets import (
    _asset,
    _insert,
    _rows,
    make_sqlite_markets,
    serve_row_operations,
)

UTC = dt.UTC
T0 = dt.datetime(2026, 3, 2, 21, 0, tzinfo=UTC)
T1 = T0 + dt.timedelta(days=1)
T2 = T0 + dt.timedelta(days=2)
BRANCH = "b7a1c2d3-e4f5-4a6b-8c7d-9e0f1a2b3c4d"


@pytest.fixture(params=["runtime", "remote"])
def markets(request, tmp_path, monkeypatch, sqlite_revisions):
    markets = make_sqlite_markets(tmp_path, monkeypatch, template=sqlite_revisions.file("head"))
    for asset in ("AAA", "BBB", "USD"):
        _asset(markets.engine, asset)
    markets.calendar = _insert(markets.engine, "ms_markets__calendar", unique_identifier="XNYS")
    serve_row_operations(monkeypatch, markets)
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


def _signal(key: str = "model-a") -> ApplicationWeights:
    return ApplicationWeights.from_signal_configuration(
        ApplicationWeightsConfig(provider="an-application", key=key)
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


def test_end_signals_ends_what_may_go_and_reports_the_rest(markets) -> None:
    """Issue 126: one call; a refused or missing signal never stops the others."""

    first, second, named = (
        ApplicationWeights.from_signal_configuration(
            ApplicationWeightsConfig(provider="an-application", key=key)
        )
        for key in ("model-a", "model-b", "model-c")
    )
    for signal in (first, second, named):
        recipes.publish_signal_weights(signal.signal_uid, {T0: {"AAA": 1.0}})
    _insert(
        markets.engine,
        "ms_markets__portfolio",
        unique_identifier="names-the-signal",
        calendar_uid=markets.calendar["uid"],
        signal_uid=named.signal_uid,
    )

    result = recipes.end_signals(
        [first.signal_uid, named.signal_uid, "never-published", second.signal_uid]
    )

    assert [item["signal_uid"] for item in result["ended"]] == [first.signal_uid, second.signal_uid]
    assert all(item["deleted_weights_count"] == 1 for item in result["ended"])
    assert [item["signal_uid"] for item in result["failed"]] == [named.signal_uid, "never-published"]
    assert "1 portfolio names it" in result["failed"][0]["detail"]
    assert SignalMetadata.filter(signal_uid=first.signal_uid) == []
    assert SignalMetadata.filter(signal_uid=second.signal_uid) == []
    assert SignalWeightsSeries.bounds([named.signal_uid])[0].row_count == 1


def test_end_signals_keeps_only_the_signal_a_key_the_read_cannot_see_holds(markets) -> None:
    """Issue 126: the database refuses the selection's transaction, which deletes nothing;
    each signal is then ended on its own, and only the refused one stays."""

    from msm_portfolios.models import SignalMetadataTable

    kept, gone = (
        ApplicationWeights.from_signal_configuration(
            ApplicationWeightsConfig(provider="an-application", key=key)
        )
        for key in ("model-kept", "model-gone")
    )
    for signal in (kept, gone):
        recipes.publish_signal_weights(signal.signal_uid, {T0: {"AAA": 1.0}})
    with markets.engine.begin() as connection:
        connection.exec_driver_sql(
            "CREATE TABLE provider_ns__signalnotes (signal_uid VARCHAR(255) NOT NULL "
            f"REFERENCES {SignalMetadataTable.__table__.name} (signal_uid) ON DELETE RESTRICT)"
        )
        connection.exec_driver_sql(
            "INSERT INTO provider_ns__signalnotes VALUES (?)", (kept.signal_uid,)
        )

    result = recipes.end_signals([kept.signal_uid, gone.signal_uid])

    assert [item["signal_uid"] for item in result["ended"]] == [gone.signal_uid]
    assert [item["signal_uid"] for item in result["failed"]] == [kept.signal_uid]
    assert "could not be deleted" in result["failed"][0]["detail"]
    assert SignalWeightsSeries.bounds([kept.signal_uid])[0].row_count == 1
    assert SignalMetadata.filter(signal_uid=gone.signal_uid) == []


# Portfolios ----------------------------------------------------------------------------------


class Prices(PublishedTable):
    """The producer's own price table: read, never written, by the run."""

    def run(self, **_kwargs):
        return None


class Resolver:
    """The producer's portfolio resolver: one Portfolio row per configuration.

    ``identifiers`` maps a configuration hash to its portfolio; without it every
    configuration is ``model-a-portfolio``.
    """

    def __init__(self, calendar_uid: str, identifiers: dict[str, str] | None = None) -> None:
        self.calendar_uid = uuid.UUID(calendar_uid)
        self.identifiers = identifiers or {}

    def get_or_create_from_configuration_hash(self, *, portfolio_configuration_hash, **_kwargs):
        from msm.api.portfolios import Portfolio

        identifier = self.identifiers.get(portfolio_configuration_hash, "model-a-portfolio")
        existing = Portfolio.get_by_unique_identifier(identifier)
        if existing is not None:
            return existing
        return Portfolio.create(unique_identifier=identifier, calendar_uid=self.calendar_uid)


def _prices(name: str = "prices") -> Prices:
    rows = [
        {"time_index": time, "asset_identifier": asset, "close": price}
        for time, prices in ((T1, {"AAA": 100.0, "BBB": 50.0}), (T2, {"AAA": 110.0, "BBB": 50.0}))
        for asset, price in prices.items()
    ]
    return Prices.build(name, pd.DataFrame(rows), index=["time_index", "asset_identifier"])


def _configuration(
    signal: ApplicationWeights | FixedWeights,
    *,
    prices: Prices | None = None,
    calendar_events: Prices | None = None,
    name: str = "model-a-portfolio",
) -> PortfolioConfiguration:
    return PortfolioConfiguration(
        portfolio_build_configuration=PortfolioBuildConfiguration(
            valuation_source_instance=prices or _prices(),
            valuation_asset_identifier="USD",
            backtesting_weights_configuration=BacktestingWeightsConfig(
                signal_weights_instance=signal,
                rebalance_strategy_instance=ImmediateSignal(
                    calendar_events_instance=calendar_events or _prices("calendar-events"),
                    calendar_identifier="XNYS",
                ),
            ),
            accounting_configuration=PortfolioAccountingConfiguration(
                initial_nav=1_000.0,
                initial_state_time_index=T0,
                position_valuation_model_instance=MarketPriceValuationModel(),
            ),
        ),
        portfolio_markets_configuration=PortfolioMarketsConfig(portfolio_name=name),
    )


def _filled_state(portfolio_identifier: str) -> pd.DataFrame:
    """The rebalance state of a portfolio filled at T1: 0.6 AAA at 100, 0.4 BBB at 50."""

    return pd.DataFrame(
        [
            {
                "time_index": T1,
                "portfolio_identifier": portfolio_identifier,
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
    ).set_index(["time_index", "portfolio_identifier", "rebalance_intent_id", "asset_identifier"])


@pytest.fixture
def rebalance_state(monkeypatch):
    """The producer's private rebalance state and ledger, run by MetaTables' joined run.

    Each portfolio's rebalance state is filled at T1. The run is MetaTables' own
    ``run_updaters`` (``tests/support/metatables_runs.py``): its graph and order are
    MetaTables'. A ledger node computes its rows (``PortfolioEngine.update``) and keeps
    them in memory, where the weights and values nodes read them; the other nodes write
    nothing. Answers the invocations, each the update hashes of the nodes it ran, and
    ``calculate``, the node calculation a test may replace.
    """

    ledger: dict[str, list[pd.DataFrame]] = {}

    def book(updater):
        if isinstance(updater, PortfolioEngine):
            frame = updater.update()
            if not frame.empty:
                ledger.setdefault(updater.config.portfolio_identifier, []).append(frame)
            return frame
        return None

    def booked(self, **_kwargs):
        frames = ledger.get(self.config.portfolio_identifier)
        return pd.concat(frames) if frames else pd.DataFrame()

    monkeypatch.setattr(
        PortfolioRebalance,
        "get_df_between_dates",
        lambda self, **_kwargs: _filled_state(self._portfolio_identifier),
    )
    monkeypatch.setattr(PortfolioEngine, "get_df_between_dates", booked)
    runs = serve_joined_runs(monkeypatch, lambda updater: runs.calculate(updater))
    runs.calculate = book
    with (
        _bound(PortfolioRebalanceStateStorage, "a0000000-0000-4000-8000-0000000000aa"),
        _bound(PortfolioEventLedgerStorage, "a0000000-0000-4000-8000-0000000000bb"),
    ):
        yield runs


def _count_reads(monkeypatch, *updaters) -> dict[str, int]:
    """Count the window reads of each updater class from now on."""

    reads = {updater.__name__: 0 for updater in updaters}
    for updater in updaters:
        original = updater.get_df_between_dates

        def counted(self, *args, _original=original, _name=updater.__name__, **kwargs):
            reads[_name] += 1
            return _original(self, *args, **kwargs)

        monkeypatch.setattr(updater, "get_df_between_dates", counted)
    return reads


def _spy_registry_writes(monkeypatch) -> list[str]:
    """Record every write of a ``Portfolio`` or ``SignalMetadata`` row from now on."""

    from msm.api.portfolios import Portfolio

    writes: list[str] = []
    for rows in (Portfolio, SignalMetadata):
        for name in ("create", "update", "upsert"):
            original = getattr(rows, name).__func__

            def spy(cls, *args, _original=original, _name=f"{rows.__name__}.{name}", **kwargs):
                writes.append(_name)
                return _original(cls, *args, **kwargs)

            monkeypatch.setattr(rows, name, classmethod(spy))
    return writes


def test_run_portfolio_publishes_weights_and_values_once(
    markets, rebalance_state, monkeypatch
) -> None:
    signal = _signal()
    configuration = _configuration(signal)
    resolver = Resolver(markets.calendar["uid"])

    with pytest.raises(ValueError, match="has no published observation"):
        recipes.run_portfolio(configuration, portfolio_resolver=resolver)
    recipes.publish_signal_weights(signal.signal_uid, {T0: {"AAA": 0.6, "BBB": 0.4}})
    reads = _count_reads(monkeypatch, PortfolioEngine, PortfolioRebalance, Prices)
    first = recipes.run_portfolio(configuration, portfolio_resolver=resolver)
    writes = _spy_registry_writes(monkeypatch)
    second = recipes.run_portfolio(configuration, portfolio_resolver=resolver)

    # Nothing changed, so the second run writes neither the Portfolio row nor the
    # signal's metadata (#136).
    assert writes == []
    # Each run reads the ledger, the rebalance state and the prices once, in the ledger's
    # update (this rebalance computes nothing, so it read no prices to share); the weights
    # and values use the rows the ledger kept (#139).
    assert reads == {"PortfolioEngine": 2, "PortfolioRebalance": 2, "Prices": 2}
    assert first.first_rebalance is True
    assert first.weights.written == 2
    assert first.values.written == 3
    assert first.portfolio.signal_uid == signal.signal_uid
    assert (second.first_rebalance, second.weights, second.values) == (False, None, None)
    # One invocation per run: the prices and calendar events, the rebalance, the ledger.
    assert len(rebalance_state.invocations) == 2
    assert rebalance_state.kinds_of(0) == ["Prices", "Prices", "PortfolioRebalance", "PortfolioEngine"]
    assert set(rebalance_state.invocations[0][:2]) == {"prices", "calendar-events"}
    values = recipes.portfolio_history("model-a-portfolio")
    assert values.count == 3
    # The ledger opens with its initial NAV in cash at T0, buys 6 AAA at 100 and 8 BBB
    # at 50 at T1, and AAA is at 110 at T2: 660 + 400 = 1,060.
    assert list(values.values.index.get_level_values("time_index")) == [
        pd.Timestamp(T2),
        pd.Timestamp(T1),
        pd.Timestamp(T0),
    ]
    assert values.values["close"].tolist() == pytest.approx([1.06, 1.0, 1.0])
    weights = recipes.weights_as_of(["model-a-portfolio"], at=T2)
    assert weights["weight"].to_dict() == {
        (pd.Timestamp(T1), "model-a-portfolio", "AAA"): 0.6,
        (pd.Timestamp(T1), "model-a-portfolio", "BBB"): 0.4,
    }
    (row,) = _rows(markets.engine, "SELECT managed_by FROM ms_markets__portfolio")
    assert row["managed_by"] == (f"branch:{BRANCH}" if markets.backend == "remote" else None)


def test_run_portfolios_runs_a_shared_dependency_once_in_one_invocation(
    markets, rebalance_state
) -> None:
    """Two portfolios on the same prices and calendar events run in one invocation (#133).

    Each portfolio has its own signal, rebalance and ledger; the prices and the
    calendar events they share run once, before both rebalances, and both ledgers run
    after their own rebalance.
    """

    prices, events = _prices(), _prices("calendar-events")
    signals = {name: _signal(name) for name in ("model-a", "model-b")}
    configurations = {
        name: _configuration(
            signal, prices=prices, calendar_events=events, name=f"{name}-portfolio"
        )
        for name, signal in signals.items()
    }
    resolver = Resolver(
        markets.calendar["uid"],
        {
            compute_portfolio_configuration_hash(configuration): f"{name}-portfolio"
            for name, configuration in configurations.items()
        },
    )
    for signal in signals.values():
        recipes.publish_signal_weights(signal.signal_uid, {T0: {"AAA": 0.6, "BBB": 0.4}})

    runs = recipes.run_portfolios(list(configurations.values()), portfolio_resolver=resolver)

    assert runs.failed == ()
    assert [run.portfolio.unique_identifier for run in runs.ran] == [
        "model-a-portfolio",
        "model-b-portfolio",
    ]
    assert all(run.first_rebalance and run.values.written == 3 for run in runs.ran)
    (invocation,) = rebalance_state.invocations
    assert invocation.count("prices") == 1
    assert invocation.count("calendar-events") == 1
    assert set(invocation[:2]) == {"prices", "calendar-events"}
    # Every node after what it reads, and the ledgers, the heads, last.
    assert rebalance_state.kinds_of(0) == [
        "Prices",
        "Prices",
        "PortfolioRebalance",
        "PortfolioRebalance",
        "PortfolioEngine",
        "PortfolioEngine",
    ]
    for run in runs.ran:
        values = recipes.portfolio_history(run.portfolio.unique_identifier)
        assert values.values["close"].tolist() == pytest.approx([1.06, 1.0, 1.0])


def test_run_portfolios_lists_a_portfolio_that_cannot_run_and_runs_the_others(
    markets, rebalance_state
) -> None:
    ready, unpublished = _signal("model-a"), _signal("model-b")
    configurations = [
        _configuration(ready, name="model-a-portfolio"),
        _configuration(unpublished, name="model-b-portfolio"),
    ]
    resolver = Resolver(
        markets.calendar["uid"],
        {
            compute_portfolio_configuration_hash(configurations[0]): "model-a-portfolio",
            compute_portfolio_configuration_hash(configurations[1]): "model-b-portfolio",
        },
    )
    recipes.publish_signal_weights(ready.signal_uid, {T0: {"AAA": 0.6, "BBB": 0.4}})

    runs = recipes.run_portfolios(configurations, portfolio_resolver=resolver)

    assert [run.portfolio.unique_identifier for run in runs.ran] == ["model-a-portfolio"]
    (failure,) = runs.failed
    assert failure.position == 1 and failure.portfolio_identifier is None
    assert "has no published observation" in failure.detail
    assert len(rebalance_state.invocations) == 1


class SignalTableBase(DeclarativeBase):
    metadata = MetaData(naming_convention=sqlalchemy_naming_convention())


class SignalTable(SignalWeightsInstance, SignalTableBase):
    __instance_key__ = "signals"
    __metatable_namespace__ = "an-application"
    __markets_storage_app__ = "an_application"


def test_a_computed_signal_is_its_own_node_that_runs_before_the_rebalance(
    markets, rebalance_state, monkeypatch
) -> None:
    """2026-11-24: the signal node writes its own table and publishes to Markets; the
    rebalance depends on it, so it runs first. Nothing is published before the run, and
    the preflight refuses nothing: the run computes it."""

    table: list[pd.DataFrame] = []  # the producer's signal table, as MetaTables writes it
    calculate = rebalance_state.calculate

    def calculate_signal(updater):
        if not isinstance(updater, SignalWeights):
            return calculate(updater)
        progress: dict = {}
        for frame in table:
            for time, signal_uid, asset in frame.index:
                progress.setdefault(signal_uid, {})[asset] = time
        updater.update_statistics = SimpleNamespace(index_progress=progress)
        frame = updater.update()
        if not frame.empty:
            table.append(frame)
        return frame

    rebalance_state.calculate = calculate_signal
    with _bound(SignalTable, "a0000000-0000-4000-8000-0000000000cc"):
        signal = FixedWeights.from_signal_configuration(
            FixedWeightsConfig(
                asset_unique_identifier_weights=[
                    AUIDWeight(unique_identifier="AAA", weight=0.6),
                    AUIDWeight(unique_identifier="BBB", weight=0.4),
                ],
                signal_time_index=T0,
            ),
            output_table=SignalTable,
        )
        configuration = _configuration(signal)
        resolver = Resolver(markets.calendar["uid"])

        assert recipes.portfolio_preflight(configuration).ready is True
        first = recipes.run_portfolio(configuration, portfolio_resolver=resolver)
        second = recipes.run_portfolio(configuration, portfolio_resolver=resolver)

    for invocation in (0, 1):
        kinds = rebalance_state.kinds_of(invocation)
        assert kinds.count("FixedWeights") == 1
        assert kinds.index("FixedWeights") < kinds.index("PortfolioRebalance")
    assert len(table) == 1 and len(table[0]) == 2
    (bounds,) = SignalWeightsSeries.bounds([signal.signal_uid])
    assert (bounds.first_time, bounds.last_time, bounds.row_count) == (T0, T0, 2)
    assert first.first_rebalance is True and first.portfolio.signal_uid == signal.signal_uid
    assert (second.first_rebalance, second.weights, second.values) == (False, None, None)


def test_portfolio_preflight_reports_why_a_portfolio_cannot_run(markets) -> None:
    signal = _signal()

    blocked = recipes.portfolio_preflight(_configuration(signal))
    recipes.publish_signal_weights(signal.signal_uid, {T0: {"AAA": 1.0}})
    ready = recipes.portfolio_preflight(_configuration(signal))

    assert blocked.ready is False and "has no published observation" in blocked.reasons[0]
    assert ready.ready is True and ready.signal_first_time == T0


# Private rows --------------------------------------------------------------------------------


def test_delete_private_series_clears_the_producers_rows_in_key_order(
    tmp_path, monkeypatch, sqlite_revisions
):
    from msm_portfolios.time_index.contract_instances import (
        PortfolioCalendarEventsInstance,
        PortfolioRebalanceStateInstance,
    )

    class ProducerBase(DeclarativeBase):
        metadata = MetaData(naming_convention=sqlalchemy_naming_convention())

    class Producer:
        __instance_key__ = "private"
        __metatable_namespace__ = "my-app"
        __markets_storage_app__ = "my_app"

    class PrivateRebalanceState(PortfolioRebalanceStateInstance, Producer, ProducerBase):
        pass

    class PrivateCalendarEvents(PortfolioCalendarEventsInstance, Producer, ProducerBase):
        pass

    class PrivateSignals(SignalWeightsInstance, Producer, ProducerBase):
        pass

    def prepare(engine):
        PrivateRebalanceState.__table__.create(engine)
        PrivateCalendarEvents.__table__.create(engine)
        PrivateSignals.__table__.create(engine)

    markets = make_sqlite_markets(
        tmp_path, monkeypatch, template=sqlite_revisions.file("head"), prepare=prepare
    )
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
            PrivateRebalanceState.__table__.name,
            time_index=T0,
            portfolio_identifier=identifier,
            asset_identifier="AAA",
            target_signal_time_index=T0,
        )
    _insert(markets.engine, PrivateCalendarEvents.__table__.name, time_index=T0, calendar_identifier="XNYS")
    for signal_uid in ("kept-signal", "ended-signal"):
        _insert(markets.engine, "ms_markets__signalmetadata", signal_uid=signal_uid)
        _insert(
            markets.engine,
            PrivateSignals.__table__.name,
            time_index=T0,
            signal_uid=signal_uid,
            asset_identifier="AAA",
            signal_weight=1.0,
        )

    deleted = recipes.delete_private_series(
        [PrivateRebalanceState, PrivateCalendarEvents, PrivateSignals],
        portfolios=["deleted"],
        calendars=["XNYS"],
        signals=["ended-signal"],
    )

    assert deleted == {
        PrivateRebalanceState.__table__.name: 1,
        PrivateCalendarEvents.__table__.name: 1,
        PrivateSignals.__table__.name: 1,
    }
    assert _rows(markets.engine, f"SELECT signal_uid FROM {PrivateSignals.__table__.name}") == [
        {"signal_uid": "kept-signal"}
    ]
    remaining = _rows(
        markets.engine, f"SELECT portfolio_identifier FROM {PrivateRebalanceState.__table__.name}"
    )
    assert remaining == [{"portfolio_identifier": "kept"}]
    with pytest.raises(ValueError, match="has none of the columns"):
        recipes.delete_private_series([PrivateCalendarEvents], portfolios=["kept"])
