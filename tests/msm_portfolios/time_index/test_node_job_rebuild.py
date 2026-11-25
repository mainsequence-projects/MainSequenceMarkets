"""Every node a portfolio run builds rebuilds in a node Job run (ADR 0067, decision 4).

A node Job run is a new process. Before anything starts, the orchestrator checks each node
(MetaTables' ``job_mode.node_arguments``); the node's Job run then rebuilds its updater from
the saved configuration (``job_mode.rebuild_updater``), importing the updater and table
classes by their address, and refuses a rebuilt update hash that differs.

Both run here, on every node of a portfolio graph for each strategy and each signal
ms-markets ships: the ledger, the rebalance, the computed signal, the interpolated prices,
the calendar events and the strategies' and signals' declared inputs. MetaTables' update
records are stood in from the live graph, and nothing leaves the process.
"""

from __future__ import annotations

import socket
from contextlib import ExitStack
from types import SimpleNamespace

import pandas as pd
import pytest

import metatables.updaters.job_mode as job_mode
from metatables import TimeIndexMetaTable, TimeIndexTableRef, TimeIndexTableUpdater
from msm.time_index.assets import AssetSnapshot
from msm.time_index.assets.storage import AssetSnapshotsStorage
from msm_portfolios.configuration import (
    BacktestingWeightsConfig,
    MarketsTimeSeries,
    PortfolioBuildConfiguration,
    PortfolioConfiguration,
    PortfolioMarketsConfig,
)
from msm_portfolios.contrib.prices.updaters import InterpolatedPrices, InterpolatedPricesConfig
from msm_portfolios.contrib.signals import (
    ApplicationWeights,
    ApplicationWeightsConfig,
    AUIDWeight,
    FixedWeights,
    FixedWeightsConfig,
)
from msm_portfolios.contrib.signals.external_weights import ExternalWeights, ExternalWeightsConfig
from msm_portfolios.contrib.signals.intraday_trend import IntradayTrend, IntradayTrendConfig
from msm_portfolios.contrib.signals.market_cap import MarketCap, MarketCapConfig
from msm_portfolios.contrib.signals.portfolio_replicator import (
    ETFReplicator,
    ETFReplicatorConfig,
    TrackingStrategyConfiguration,
)
from msm_portfolios.rebalance_strategy import (
    CalendarEventSignal,
    ImmediateSignal,
    LiquidityConstrained,
    TimeWeighted,
    TrailingAverageDailyVolumeParticipation,
    VolumeParticipation,
)
from msm_portfolios.time_index import PortfolioValues, compute_portfolio_configuration_hash
from msm_portfolios.time_index.portfolios.calendar_events import (
    PortfolioCalendarEvents,
    PortfolioCalendarEventsConfiguration,
)
from msm_portfolios.time_index.portfolios.rebalance import PortfolioRebalance
from tests.support.portfolio_tables import (
    ProducerCalendarEvents,
    ProducerEventLedger,
    ProducerRebalanceState,
    ProducerSignalWeights,
)
from tests.support.pinned_identities import PINNED_ACCOUNTING, PinnedInterpolatedPrices, _bound

PORTFOLIO = "rebuilt-portfolio"
TABLES = (
    (AssetSnapshotsStorage, {"cadence": "1d", "physical_table_name": "ms_markets__assetsnapshotsts"}),
    (PinnedInterpolatedPrices, {"cadence": "1d"}),
    (ProducerCalendarEvents, {}),
    (ProducerSignalWeights, {}),
    (ProducerRebalanceState, {}),
    (ProducerEventLedger, {}),
)
STRATEGIES = (
    "ImmediateSignal",
    "CalendarEventSignal",
    "LiquidityConstrained",
    "TimeWeighted",
    "VolumeParticipation",
    "TrailingAverageDailyVolumeParticipation",
)
SIGNALS = (
    "FixedWeights",
    "MarketCap",
    "ExternalWeights",
    "IntradayTrend",
    "ETFReplicator",
    "ApplicationWeights",
)
GRAPHS = [(strategy, "FixedWeights") for strategy in STRATEGIES] + [
    ("ImmediateSignal", signal) for signal in SIGNALS if signal != "FixedWeights"
]


@pytest.fixture
def offline(monkeypatch):
    """Refuse every connection: the check and the rebuild make no request."""

    def refuse(*_args, **_kwargs):
        raise AssertionError("A node's check or rebuild made a request.")

    monkeypatch.setattr(socket.socket, "connect", refuse)
    monkeypatch.setattr(socket, "create_connection", refuse)


@pytest.fixture
def inputs(offline):
    """The nodes every graph shares, on bound tables: bars, prices and calendar events."""

    with ExitStack() as stack:
        for position, (table, metadata) in enumerate(TABLES, start=1):
            stack.enter_context(_bound(table, f"a0000000-0000-4000-8000-{position:012d}", **metadata))
        bars = AssetSnapshot()
        prices = InterpolatedPrices(
            InterpolatedPricesConfig(
                source_price_instance=bars,
                intraday_bar_interpolation_rule="ffill",
                upsample_frequency_id="1d",
                asset_list=["ASSET_A", "ASSET_B"],
            ),
            output_table=PinnedInterpolatedPrices,
        )
        events = PortfolioCalendarEvents(
            config=PortfolioCalendarEventsConfiguration(calendar_identifier="XNYS"),
            output_table=ProducerCalendarEvents,
        )
        yield SimpleNamespace(bars=bars, prices=prices, events=events)


def _strategy(name: str, inputs: SimpleNamespace):
    return {
        "ImmediateSignal": lambda: ImmediateSignal(
            calendar_events_instance=inputs.events, calendar_identifier="XNYS"
        ),
        "CalendarEventSignal": lambda: CalendarEventSignal(
            calendar_events_instance=inputs.events,
            calendar_identifier="XNYS",
            session_label="regular",
            rebalance_event="market_close",
        ),
        "LiquidityConstrained": lambda: LiquidityConstrained(liquidity_source_instance=inputs.bars),
        "TimeWeighted": lambda: TimeWeighted(execution_bars_instance=inputs.prices),
        "VolumeParticipation": lambda: VolumeParticipation(execution_bars_instance=inputs.prices),
        "TrailingAverageDailyVolumeParticipation": lambda: TrailingAverageDailyVolumeParticipation(
            daily_liquidity_instance=inputs.bars, execution_bars_instance=inputs.prices
        ),
    }[name]()


def _computed(signal_class: type, configuration, namespace: str | None = None):
    return signal_class.from_signal_configuration(
        configuration, output_table=ProducerSignalWeights, namespace=namespace
    )


def _fixed_weights(namespace: str | None = None) -> FixedWeights:
    return _computed(
        FixedWeights,
        FixedWeightsConfig(
            asset_unique_identifier_weights=[
                AUIDWeight(unique_identifier="ASSET_A", weight=0.6),
                AUIDWeight(unique_identifier="ASSET_B", weight=0.4),
            ],
            signal_time_index=pd.Timestamp("2026-01-02T12:00:00Z").to_pydatetime(),
        ),
        namespace,
    )


def _market_cap() -> MarketCap:
    signal = _computed(
        MarketCap,
        MarketCapConfig(
            asset_list=["ASSET_A", "ASSET_B"],
            market_cap_time_series=MarketsTimeSeries(unique_identifier="market-caps"),
            volatility_control_configuration=None,
        ),
    )
    # The series it reads is a table, looked up by identifier when the run plans; here
    # it is stood in, so the walk makes no request.
    signal._historical_market_cap_ts = TimeIndexTableRef(
        output_table=TimeIndexMetaTable.model_construct(
            uid="b0000000-0000-4000-8000-000000000001", data_source_uid="source"
        )
    )
    return signal


def _signal(name: str, inputs: SimpleNamespace):
    return {
        "FixedWeights": _fixed_weights,
        "MarketCap": _market_cap,
        "ExternalWeights": lambda: _computed(
            ExternalWeights,
            ExternalWeightsConfig(
                artifact_name="weights.csv", bucket_name="signals", asset_list=["ASSET_A"]
            ),
        ),
        "IntradayTrend": lambda: _computed(
            IntradayTrend,
            IntradayTrendConfig(
                price_source_instance=inputs.prices,
                asset_symbols_by_exchange={"XNAS": ["ASSET_A", "ASSET_B"]},
                calendar_identifier="XNAS",
            ),
        ),
        "ETFReplicator": lambda: _computed(
            ETFReplicator,
            ETFReplicatorConfig(
                asset_list=["ASSET_A", "ASSET_B"],
                price_source_instance=inputs.prices,
                etf_price_source_instance=inputs.prices,
                etf_ticker="SPY",
                tracking_strategy_configuration=TrackingStrategyConfiguration(),
            ),
        ),
        "ApplicationWeights": lambda: ApplicationWeights.from_signal_configuration(
            ApplicationWeightsConfig(provider="an-application", key="model-a")
        ),
    }[name]()


def _configuration(signal, strategy, inputs: SimpleNamespace) -> PortfolioConfiguration:
    return PortfolioConfiguration(
        portfolio_build_configuration=PortfolioBuildConfiguration(
            valuation_source_instance=inputs.prices,
            valuation_asset_identifier="USD",
            backtesting_weights_configuration=BacktestingWeightsConfig(
                signal_weights_instance=signal, rebalance_strategy_instance=strategy
            ),
            accounting_configuration=PINNED_ACCOUNTING,
        ),
        portfolio_markets_configuration=PortfolioMarketsConfig(portfolio_name="rebuilt"),
    )


def _ledger(configuration: PortfolioConfiguration, portfolio: str = PORTFOLIO):
    """The ledger ``run_portfolios`` builds for ``configuration``, on the producer's tables."""

    values = PortfolioValues(
        portfolio_configuration=configuration,
        rebalance_output_table=ProducerRebalanceState,
        event_ledger_output_table=ProducerEventLedger,
    )
    values.portfolio_weights.set_portfolio_configuration(
        configuration, portfolio_identifier=portfolio
    )
    return values.portfolio_weights.ensure_portfolio_engine()


def _nodes(head: TimeIndexTableUpdater) -> list[TimeIndexTableUpdater]:
    """Every updater of ``head``'s graph, as MetaTables plans it: by update hash."""

    found: dict[str, TimeIndexTableUpdater] = {}
    pending = [head]
    while pending:
        node = pending.pop()
        if node.update_hash in found:
            continue
        found[node.update_hash] = node
        pending.extend(
            dependency
            for dependency in node.dependencies().values()
            if isinstance(dependency, TimeIndexTableUpdater)
        )
    return list(found.values())


def _records(monkeypatch, nodes: list[TimeIndexTableUpdater]) -> None:
    """MetaTables' update records of ``nodes``, as a run registers and saves them."""

    def record(node: TimeIndexTableUpdater) -> SimpleNamespace:
        return SimpleNamespace(
            uid=f"update-{node.update_hash}",
            update_hash=node.update_hash,
            build_configuration=dict(node.local_initial_configuration),
            output_table=node.output_table_uid,
        )

    class Records:
        @staticmethod
        def get(uid: str) -> SimpleNamespace:
            return next(record(node) for node in nodes if f"update-{node.update_hash}" == uid)

        @staticmethod
        def filter(update_hash: str, output_table__uid: str) -> list[SimpleNamespace]:
            return [
                record(node)
                for node in nodes
                if node.update_hash == update_hash and node.output_table_uid == output_table__uid
            ]

    monkeypatch.setattr(job_mode, "TimeIndexTableUpdate", Records)


def _rebuilt(node: TimeIndexTableUpdater) -> TimeIndexTableUpdater:
    """``node`` as its node Job run builds it, after the orchestrator's check."""

    arguments = job_mode.node_arguments(node)
    return job_mode.rebuild_updater(
        f"update-{node.update_hash}", arguments["output_table"], arguments["argument_tables"]
    )


@pytest.mark.parametrize(("strategy", "signal"), GRAPHS)
def test_every_node_passes_the_check_and_rebuilds_with_its_hash(
    inputs, monkeypatch, strategy, signal
) -> None:
    nodes = _nodes(
        _ledger(_configuration(_signal(signal, inputs), _strategy(strategy, inputs), inputs))
    )
    _records(monkeypatch, nodes)

    kinds = {type(node).__name__ for node in nodes}
    assert {"PortfolioEngine", "PortfolioRebalance", "InterpolatedPrices", "AssetSnapshot"} <= kinds
    assert (signal in kinds) is (signal != "ApplicationWeights")
    for node in nodes:
        rebuilt = _rebuilt(node)

        assert type(rebuilt) is type(node)
        assert rebuilt.update_hash == node.update_hash
        assert rebuilt.output_table is node.output_table


def test_a_rebuilt_rebalance_keeps_its_portfolio_outside_its_hash(inputs, monkeypatch) -> None:
    """Its run resolved the portfolio; the node Job run has no resolver, and reads it back."""

    configuration = _configuration(
        _fixed_weights(), _strategy("ImmediateSignal", inputs), inputs
    )
    ledger = _ledger(configuration)
    nodes = _nodes(ledger)
    _records(monkeypatch, nodes)
    rebalance = next(node for node in nodes if isinstance(node, PortfolioRebalance))

    rebuilt = _rebuilt(rebalance)

    assert rebuilt._resolve_portfolio_identifier() == PORTFOLIO
    assert rebuilt.config.portfolio_identifier == PORTFOLIO
    other = _ledger(configuration, "another-portfolio").config.portfolio_rebalance_instance
    assert other.update_hash == rebalance.update_hash


def test_a_rebalance_saves_its_signal_in_a_form_metatables_rebuilds(inputs) -> None:
    """A computed signal by its update, a published one as its pydantic model."""

    strategy = _strategy("ImmediateSignal", inputs)
    computed = _fixed_weights()
    published = _signal("ApplicationWeights", inputs)

    def saved_signal(signal) -> dict:
        rebalance = _ledger(_configuration(signal, strategy, inputs)).config.portfolio_rebalance_instance
        saved = rebalance.local_initial_configuration["portfolio_configuration"]
        build = saved["serialized_model"]["portfolio_build_configuration"]["serialized_model"]
        backtesting = build["backtesting_weights_configuration"]["serialized_model"]
        return backtesting["signal_weights_instance"]

    assert saved_signal(computed) == {
        "kind": "table_update",
        "update_hash": computed.update_hash,
        "output_table_uid": computed.output_table_uid,
    }
    assert saved_signal(published)["pydantic_model_import_path"] == {
        "module": "msm_portfolios.contrib.signals.application_weights",
        "qualname": "ApplicationWeights",
    }


def test_a_portfolio_names_its_signal_by_its_uid_in_every_namespace(inputs) -> None:
    """The node's update hash and table differ between namespaces; the portfolio does not."""

    strategy = _strategy("ImmediateSignal", inputs)
    one, other = _fixed_weights("producer-a"), _fixed_weights("producer-b")

    assert one.update_hash != other.update_hash
    assert one.signal_uid == other.signal_uid
    assert compute_portfolio_configuration_hash(
        _configuration(one, strategy, inputs)
    ) == compute_portfolio_configuration_hash(_configuration(other, strategy, inputs))
