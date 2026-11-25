from __future__ import annotations

import inspect
from datetime import date, timedelta
from types import SimpleNamespace

import pandas as pd
import pytest
from pydantic import ValidationError

from metatables import TimeIndexMetaTable, TimeIndexTableUpdater
from metatables.updaters.configuration import (
    hash_signature,
)
from msm.time_index.utils.storage_schema import storage_column_dtypes_map
from msm.models import AssetTable, PortfolioTable
from msm_portfolios.contrib.signals import ApplicationWeights, ApplicationWeightsConfig
from msm_portfolios.configuration import (
    PortfolioBuildConfiguration,
    canonical_rebalance_strategy_configuration,
    canonical_valuation_source_configuration,
)
from msm_portfolios.time_index import (
    PortfolioAnalytics,
    PortfolioAnalyticsConfiguration,
    PortfolioCalendarEvents,
    PortfolioCalendarEventsConfiguration,
    PortfolioCanonicalUpdaterConfiguration,
    PortfolioRebalance,
    PortfolioValues,
    PortfolioWeights,
    SignalWeights,
    SignalWeightsConfiguration,
)
from msm_portfolios.time_index.constants import ASSET_IDENTIFIER, PORTFOLIO_IDENTIFIER
from msm_portfolios.time_index.portfolios.storage import (
    PortfolioAnalyticsStorage,
    PortfolioCalendarEventsStorage,
    PortfolioRebalanceStateStorage,
    PortfolioWeightsStorage,
    PortfoliosStorage,
)
from msm_portfolios.time_index.portfolios.rebalance import normalize_rebalance_input
from msm_portfolios.time_index.portfolios.temporal import fetch_asset_observations
from msm_portfolios.time_index.signals.storage import SignalWeightsStorage
from msm_portfolios.models import portfolio_sqlalchemy_models
from msm_portfolios.rebalance_strategy import (
    observed_prices,
    CalendarEventSignal,
    ImmediateSignal,
    LiquidityConstrained,
    RebalanceInputContract,
    TimeWeighted,
    TrailingAverageDailyVolumeParticipation,
    VolumeParticipation,
)


class ExplicitValuationSource(TimeIndexTableUpdater):
    def update(self) -> pd.DataFrame:
        return pd.DataFrame()

    def dependencies(self) -> dict:
        return {}


def output_table_stub(uid: str = "valuation-table") -> SimpleNamespace:
    metadata = TimeIndexMetaTable.model_construct(uid=uid, data_source_uid="source")
    return SimpleNamespace(
        get_time_index_meta_table=lambda: metadata,
        get_data_source_uid=lambda: "source",
    )


def valuation_source(update_hash: str = "valuations") -> ExplicitValuationSource:
    source = object.__new__(ExplicitValuationSource)
    source.update_hash = update_hash
    source._output_table = output_table_stub()
    return source


@pytest.mark.parametrize(
    ("node_cls", "storage_cls"),
    [
        (PortfolioRebalance, PortfolioRebalanceStateStorage),
        (PortfolioCalendarEvents, PortfolioCalendarEventsStorage),
        (PortfolioAnalytics, PortfolioAnalyticsStorage),
    ],
)
def test_portfolio_nodes_source_schema_from_storage(node_cls, storage_cls) -> None:
    assert node_cls._column_dtypes_map_for_storage(storage_cls) == storage_column_dtypes_map(
        storage_cls
    )
    assert node_cls._required_output_table() is storage_cls


@pytest.mark.parametrize(
    ("node_cls", "storage_cls"),
    [
        (PortfolioWeights, PortfolioWeightsStorage),
        (PortfolioValues, PortfoliosStorage),
    ],
)
def test_published_nodes_validate_against_the_markets_contract(node_cls, storage_cls) -> None:
    """ADR 0060: these nodes publish to Markets' own table, so its contract is theirs."""

    assert node_cls._column_dtypes_map_for_storage() == storage_column_dtypes_map(storage_cls)
    assert node_cls._required_output_table() is storage_cls
    assert not issubclass(node_cls, TimeIndexTableUpdater)


def test_a_computed_signal_is_a_node_of_the_signal_weights_contract() -> None:
    """It writes its producer's own instance of the contract, and publishes to Markets'."""

    assert SignalWeights._column_dtypes_map_for_storage() == storage_column_dtypes_map(
        SignalWeightsStorage
    )
    assert SignalWeights._required_output_table() is SignalWeightsStorage
    assert issubclass(SignalWeights, TimeIndexTableUpdater)


def test_portfolio_configurations_do_not_carry_storage_schema() -> None:
    assert "index_names" not in PortfolioCanonicalUpdaterConfiguration.model_fields
    assert "index_names" not in SignalWeightsConfiguration.model_fields


def test_portfolio_storage_grains_and_foreign_keys_remain_stable() -> None:
    assert PortfolioCalendarEventsStorage.__index_names__ == [
        "time_index",
        "calendar_identifier",
        "session_label",
        "event_type",
    ]
    assert PortfolioRebalanceStateStorage.__index_names__ == [
        "time_index",
        PORTFOLIO_IDENTIFIER,
        "rebalance_intent_id",
        ASSET_IDENTIFIER,
    ]
    assert PortfolioWeightsStorage.__index_names__ == [
        "time_index",
        PORTFOLIO_IDENTIFIER,
        ASSET_IDENTIFIER,
    ]
    assert PortfoliosStorage.__index_names__ == ["time_index", PORTFOLIO_IDENTIFIER]
    assert PortfolioAnalyticsStorage.__index_names__ == [
        "time_index",
        PORTFOLIO_IDENTIFIER,
        "analysis_identifier",
    ]
    portfolio_targets = {
        foreign_key.target_fullname
        for foreign_key in PortfolioWeightsStorage.__table__.c.portfolio_identifier.foreign_keys
    }
    asset_targets = {
        foreign_key.target_fullname
        for foreign_key in PortfolioWeightsStorage.__table__.c.asset_identifier.foreign_keys
    }
    assert portfolio_targets == {f"{PortfolioTable.__table__.fullname}.unique_identifier"}
    assert asset_targets == {f"{AssetTable.__table__.fullname}.unique_identifier"}
    state_portfolio_targets = {
        foreign_key.target_fullname
        for foreign_key in (
            PortfolioRebalanceStateStorage.__table__.c.portfolio_identifier.foreign_keys
        )
    }
    state_asset_targets = {
        foreign_key.target_fullname
        for foreign_key in (
            PortfolioRebalanceStateStorage.__table__.c.asset_identifier.foreign_keys
        )
    }
    assert state_portfolio_targets == {f"{PortfolioTable.__table__.fullname}.unique_identifier"}
    assert state_asset_targets == {f"{AssetTable.__table__.fullname}.unique_identifier"}


def test_analytics_storage_is_in_migration_provider_scope() -> None:
    models = portfolio_sqlalchemy_models()
    assert PortfolioAnalyticsStorage in models
    assert PortfolioCalendarEventsStorage in models
    assert PortfolioRebalanceStateStorage in models
    assert models.index(PortfolioTable) < models.index(PortfolioAnalyticsStorage)
    assert models.index(PortfolioTable) < models.index(PortfolioRebalanceStateStorage)


def test_calendar_event_node_configuration_is_hash_bearing() -> None:
    payload = PortfolioCalendarEventsConfiguration(calendar_identifier="XNYS").model_dump()
    assert payload["calendar_identifier"] == "XNYS"
    assert payload["session_label"] == "regular"
    assert payload["event_types"] == ("market_open", "market_close")


def test_analytics_configuration_declares_full_sampling_semantics() -> None:
    config = PortfolioAnalyticsConfiguration(
        portfolio_identifier="portfolio",
        frequency="1W",
        label="right",
        closed="right",
        timezone="Europe/Athens",
    )
    assert config.model_dump()["frequency"] == "1W"
    assert config.model_dump()["timezone"] == "Europe/Athens"


def test_portfolio_build_configuration_is_observation_driven() -> None:
    assert "valuation_source_instance" in PortfolioBuildConfiguration.model_fields
    assert "valuation_column" in PortfolioBuildConfiguration.model_fields
    assert PortfolioBuildConfiguration.model_fields["accounting_configuration"].is_required()


def test_valuation_source_configuration_uses_sdk_identity() -> None:
    source = valuation_source("source-a")
    payload = canonical_valuation_source_configuration(source)
    assert payload
    assert "source-a" in str(payload)


def test_rebalance_strategy_serialization_distinguishes_temporal_owners() -> None:
    events = valuation_source("calendar-events")
    immediate = canonical_rebalance_strategy_configuration(
        ImmediateSignal(calendar_events_instance=events, calendar_identifier="XNYS")
    )
    close = canonical_rebalance_strategy_configuration(
        CalendarEventSignal(
            calendar_events_instance=events,
            calendar_identifier="XNYS",
            rebalance_event="market_close",
        )
    )
    open_ = canonical_rebalance_strategy_configuration(
        CalendarEventSignal(
            calendar_events_instance=events,
            calendar_identifier="XNYS",
            rebalance_event="market_open",
        )
    )
    assert immediate != close
    assert close != open_
    assert "signal_time" in str(immediate)
    assert "calendar_event" in str(close)


def test_rebalance_strategy_serialization_includes_declared_dependency_identity() -> None:
    first = canonical_rebalance_strategy_configuration(
        VolumeParticipation(execution_bars_instance=valuation_source("bars-a"))
    )
    second = canonical_rebalance_strategy_configuration(
        VolumeParticipation(execution_bars_instance=valuation_source("bars-b"))
    )

    assert first != second
    assert "bars-a" in str(first)
    assert "bars-b" in str(second)


def test_calendar_strategy_requires_a_persisted_calendar_identifier() -> None:
    with pytest.raises(ValidationError, match="calendar_identifier"):
        CalendarEventSignal(calendar_events_instance=valuation_source("events"))


def test_calendar_strategy_offset_changes_execution_and_hash() -> None:
    event = pd.Timestamp("2026-01-02T21:00:00Z")
    events_source = valuation_source("calendar-events")
    observations = pd.DataFrame(
        [(event, "XNYS", "regular", "market_close", date(2026, 1, 2))],
        columns=[
            "time_index",
            "calendar_identifier",
            "session_label",
            "event_type",
            "local_date",
        ],
    ).set_index("time_index")
    base = CalendarEventSignal(
        calendar_events_instance=events_source,
        calendar_identifier="XNYS",
    )
    shifted = CalendarEventSignal(
        calendar_events_instance=events_source,
        calendar_identifier="XNYS",
        event_offset=timedelta(minutes=5),
    )
    result = shifted.select_events(
        event - pd.Timedelta(hours=1),
        event + pd.Timedelta(hours=1),
        signal_observations=pd.DataFrame(),
        observed_inputs={"calendar_events": observations},
    )

    base_configuration = canonical_rebalance_strategy_configuration(base)
    shifted_configuration = canonical_rebalance_strategy_configuration(shifted)

    assert result["time_index"].tolist() == [event + pd.Timedelta(minutes=5)]
    assert base_configuration["config"]["event_offset"] == "PT0S"
    assert shifted_configuration["config"]["event_offset"] == "PT5M"
    assert hash_signature(base_configuration)[0] != hash_signature(shifted_configuration)[0]


def always_open_event_frame(first: str, last: str) -> pd.DataFrame:
    """CRYPTO_24_7 events: each session closes at the instant the next one opens."""
    rows = []
    for day in pd.date_range(first, last, freq="D", tz="UTC"):
        rows.extend(
            [
                (day, "CRYPTO_24_7", "regular", "market_open", day.date()),
                (day + pd.Timedelta(days=1), "CRYPTO_24_7", "regular", "market_close", day.date()),
            ]
        )
    return pd.DataFrame(
        rows,
        columns=["time_index", "calendar_identifier", "session_label", "event_type", "local_date"],
    ).set_index("time_index")


def always_open_immediate_signal() -> ImmediateSignal:
    return ImmediateSignal(
        calendar_events_instance=valuation_source("calendar-events"),
        calendar_identifier="CRYPTO_24_7",
    )


def test_immediate_signal_on_24_7_selects_only_signals_inside_the_window() -> None:
    signal_times = pd.DatetimeIndex(
        ["2026-01-02T14:00:00Z", "2026-01-02T16:00:00Z"],
        name="time_index",
    )
    signals = pd.DataFrame(
        {
            "time_index": signal_times,
            ASSET_IDENTIFIER: ["btc", "btc"],
            "signal_weight": [0.4, 0.6],
        }
    ).set_index(["time_index", ASSET_IDENTIFIER])
    result = always_open_immediate_signal().select_events(
        pd.Timestamp("2026-01-02T15:00:00Z"),
        pd.Timestamp("2026-01-02T17:00:00Z"),
        signal_observations=signals,
        observed_inputs={"calendar_events": always_open_event_frame("2026-01-01", "2026-01-02")},
    )
    assert result["time_index"].tolist() == [pd.Timestamp("2026-01-02T16:00:00Z")]


def calendar_schedule() -> pd.DataFrame:
    return pd.DataFrame(
        {
            "market_open": pd.to_datetime(
                ["2026-03-06T14:30:00Z", "2026-03-09T13:30:00Z", "2026-03-10T13:30:00Z"]
            ),
            "market_close": pd.to_datetime(
                ["2026-03-06T21:00:00Z", "2026-03-09T20:00:00Z", "2026-03-10T17:00:00Z"]
            ),
        },
        index=[date(2026, 3, 6), date(2026, 3, 9), date(2026, 3, 10)],
    )


def calendar_event_frame() -> pd.DataFrame:
    rows = []
    for local_date, row in calendar_schedule().iterrows():
        rows.extend(
            [
                (row.market_open, "XNYS", "regular", "market_open", local_date),
                (row.market_close, "XNYS", "regular", "market_close", local_date),
            ]
        )
    return pd.DataFrame(
        rows,
        columns=[
            "time_index",
            "calendar_identifier",
            "session_label",
            "event_type",
            "local_date",
        ],
    ).set_index("time_index")


def test_calendar_event_node_publishes_persisted_session_timestamps(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class PersistedCalendar:
        name = "XNYS"

        def schedule(self, *, start_date, end_date):
            del start_date, end_date
            return calendar_schedule()

    monkeypatch.setattr(
        "msm_portfolios.time_index.portfolios.calendar_events.resolve_rebalance_calendar",
        lambda _identifier: PersistedCalendar(),
    )
    node = object.__new__(PortfolioCalendarEvents)
    node.config = PortfolioCalendarEventsConfiguration(
        calendar_identifier="XNYS",
        event_types=("market_open", "market_close"),
    )
    node.update_statistics = SimpleNamespace(max_time_index_value=None)
    node._output_table = PortfolioCalendarEventsStorage

    result = node.update().reset_index()

    expected = set(calendar_schedule()[["market_open", "market_close"]].to_numpy().ravel())
    assert set(result["time_index"]) == expected
    assert set(result["event_type"]) == {"market_open", "market_close"}


def test_calendar_event_node_starts_from_its_own_calendars_events(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """One events table holds every calendar's events (#119)."""

    class PersistedCalendar:
        name = "XNYS"

        def schedule(self, *, start_date, end_date):
            del end_date
            schedule = calendar_schedule()
            return schedule[schedule["market_close"] >= start_date]

    monkeypatch.setattr(
        "msm_portfolios.time_index.portfolios.calendar_events.resolve_rebalance_calendar",
        lambda _identifier: PersistedCalendar(),
    )
    schedule = calendar_schedule()
    later = schedule["market_close"].max() + pd.Timedelta(days=30)

    def publish(progress):
        node = object.__new__(PortfolioCalendarEvents)
        node.config = PortfolioCalendarEventsConfiguration(calendar_identifier="XNYS")
        node.update_statistics = SimpleNamespace(
            index_progress=progress, max_time_index_value=later
        )
        node._output_table = PortfolioCalendarEventsStorage
        return set(node.update().reset_index()[["time_index", "event_type"]].itertuples(index=False))

    every_event = {
        (row[event], event) for _, row in schedule.iterrows() for event in ("market_open", "market_close")
    }
    # Another calendar's later events, and another session label's, start nothing here.
    other = {"XLON": {"regular": {"market_close": later}}, "XNYS": {"extended": {"market_close": later}}}
    assert publish(other) == every_event
    # Its own events start where each type left off: the first day's close is still due.
    first_open = schedule["market_open"].iloc[0]
    own = {**other, "XNYS": {"regular": {"market_open": first_open}}}
    assert publish(own) == every_event - {(first_open, "market_open")}
    first_close = schedule["market_close"].iloc[0]
    own["XNYS"]["regular"]["market_close"] = first_close
    assert publish(own) == every_event - {(first_open, "market_open"), (first_close, "market_close")}


def test_calendar_event_node_rejects_noncanonical_calendar_alias(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calendar = SimpleNamespace(name="XNYS")
    monkeypatch.setattr(
        "msm_portfolios.time_index.portfolios.calendar_events.resolve_rebalance_calendar",
        lambda _identifier: calendar,
    )
    node = object.__new__(PortfolioCalendarEvents)
    node.config = PortfolioCalendarEventsConfiguration(
        calendar_identifier="NYSE",
        event_types=("market_close",),
    )
    node.update_statistics = SimpleNamespace(max_time_index_value=None)
    node._output_table = PortfolioCalendarEventsStorage

    with pytest.raises(ValueError, match="canonical Calendar.unique_identifier"):
        node.update()


def test_calendar_strategy_preserves_persisted_dst_holiday_and_early_close_events() -> None:
    strategy = CalendarEventSignal(
        calendar_events_instance=valuation_source("calendar-events"),
        calendar_identifier="XNYS",
        rebalance_event="market_close",
    )
    result = strategy.select_events(
        pd.Timestamp("2026-03-06T00:00:00Z"),
        pd.Timestamp("2026-03-10T23:59:00Z"),
        signal_observations=pd.DataFrame(),
        observed_inputs={"calendar_events": calendar_event_frame()},
    )
    assert result["time_index"].tolist() == [
        pd.Timestamp("2026-03-06T21:00:00Z"),
        pd.Timestamp("2026-03-09T20:00:00Z"),
        pd.Timestamp("2026-03-10T17:00:00Z"),
    ]
    assert pd.Timestamp("2026-03-07T21:00:00Z") not in result


def test_calendar_strategy_weekly_cadence_produces_sparse_execution_events() -> None:
    strategy = CalendarEventSignal(
        calendar_events_instance=valuation_source("calendar-events"),
        calendar_identifier="XNYS",
        rebalance_cadence="weekly",
        rebalance_weekday=0,
    )
    result = strategy.select_events(
        pd.Timestamp("2026-03-06T00:00:00Z"),
        pd.Timestamp("2026-03-10T23:59:00Z"),
        signal_observations=pd.DataFrame(),
        observed_inputs={"calendar_events": calendar_event_frame()},
    )
    assert result["time_index"].tolist() == [pd.Timestamp("2026-03-09T20:00:00Z")]


def test_the_rebalance_depends_on_a_computed_signal_and_only_reads_a_published_one() -> None:
    """A computed signal is its own node; the rebalance's edge to it is ``signal_weights``.

    The signal's inputs are its own dependencies, not the rebalance's: MetaTables runs
    them before the signal, and the signal before the rebalance (2026-11-24). A signal
    whose weights arrive only by publication has no node and no edge.
    """
    prices = valuation_source("signal-prices")
    events = valuation_source("calendar-events")

    class PricedSignal(SignalWeights):
        def dependencies(self):
            return {"price_source": prices}

    node = object.__new__(PortfolioRebalance)
    node._portfolio_configuration = object()
    node.valuation_source = valuation_source()
    node.fx_source = None
    node.rebalance_strategy = ImmediateSignal(
        calendar_events_instance=events, calendar_identifier="XNYS"
    )
    computed = object.__new__(PricedSignal)
    node.signal_weights = computed
    assert node.dependencies() == {
        "signal_weights": computed,
        "valuation_source": node.valuation_source,
        "calendar_events": events,
    }
    assert computed.dependencies() == {"price_source": prices}

    node.signal_weights = ApplicationWeights.from_signal_configuration(
        ApplicationWeightsConfig(provider="an-application", key="model-a")
    )
    assert node.dependencies() == {
        "valuation_source": node.valuation_source,
        "calendar_events": events,
    }


def test_portfolio_rebalance_merges_arbitrary_strategy_dependencies_without_dispatch() -> None:
    signal = ApplicationWeights.from_signal_configuration(
        ApplicationWeightsConfig(provider="an-application", key="model-a")
    )
    liquidity = valuation_source("liquidity")
    node = object.__new__(PortfolioRebalance)
    node._portfolio_configuration = object()
    node.signal_weights = signal
    node.rebalance_strategy = LiquidityConstrained(
        liquidity_source_instance=liquidity
    )

    # A published signal is read by the rebalance; it is no node and has no edge.
    assert node.dependencies() == {"available_liquidity": liquidity}
    source = inspect.getsource(PortfolioRebalance)
    assert "timing_mode" not in source
    assert "ImmediateSignal" not in source
    assert "VolumeParticipation" not in source
    assert "LiquidityConstrained" not in source


def test_rebalance_and_projection_progress_resolve_nested_asset_state(monkeypatch) -> None:
    earlier = pd.Timestamp("2026-01-01T01:00:00Z")
    latest = pd.Timestamp("2026-01-01T02:00:00Z")
    rebalance = object.__new__(PortfolioRebalance)
    rebalance._resolve_portfolio_identifier = lambda: "portfolio"
    rebalance.update_statistics = SimpleNamespace(
        index_progress={
            "portfolio": {
                "intent-a": {"btc": earlier},
                "intent-b": {"btc": latest},
            }
        },
        max_time_index_value=pd.Timestamp("2026-02-01T00:00:00Z"),
    )
    projection = object.__new__(PortfolioWeights)
    projection._resolve_portfolio_identifier = lambda: "portfolio"
    bounds_calls: list[str] = []

    class Reader:
        def bounds(self, key):
            bounds_calls.append(key)
            return SimpleNamespace(last_time=latest.to_pydatetime())

    monkeypatch.setattr(PortfolioWeights, "reader", property(lambda self: Reader()))

    assert rebalance._latest_transition_time_index_value() == latest
    # The projection's progress is its published series (ADR 0060).
    assert projection._latest_projection_time_index_value() == latest
    assert bounds_calls == ["portfolio"]


def test_rebalance_and_analytics_progress_is_their_portfolios_own(monkeypatch) -> None:
    """In a shared table, the table's latest time belongs to another portfolio (#118)."""

    theirs = pd.Timestamp("2026-02-01T00:00:00Z")
    mine = pd.Timestamp("2026-01-01T02:00:00Z")
    statistics = SimpleNamespace(
        index_progress={"other": {"intent": {"btc": theirs}, "returns": theirs}},
        max_time_index_value=theirs,
    )
    rebalance = object.__new__(PortfolioRebalance)
    rebalance._resolve_portfolio_identifier = lambda: "portfolio"
    rebalance.update_statistics = statistics
    analytics = object.__new__(PortfolioAnalytics)
    analytics.portfolio_identifier = "portfolio"
    monkeypatch.setattr(PortfolioAnalytics, "analysis_identifier", property(lambda self: "returns"))
    analytics.update_statistics = statistics

    assert rebalance._latest_transition_time_index_value() is None
    assert rebalance._execution_window(None)[0] == PortfolioRebalance.OFFSET_START
    assert analytics._latest_analytics_time_index() is None

    statistics.index_progress["portfolio"] = {"intent": {"btc": mine}, "returns": mine}
    assert rebalance._latest_transition_time_index_value() == mine
    assert analytics._latest_analytics_time_index() == mine
    rebalance.update_statistics = analytics.update_statistics = None
    assert rebalance._latest_transition_time_index_value() is None
    assert analytics._latest_analytics_time_index() is None


def test_rebalance_input_contract_rejects_missing_strategy_fields() -> None:
    observations = pd.DataFrame(
        [("2026-01-01T00:00:00Z", "btc", 100.0)],
        columns=["time_index", ASSET_IDENTIFIER, "close"],
    ).set_index(["time_index", ASSET_IDENTIFIER])
    contract = RebalanceInputContract(
        index_names=("time_index", ASSET_IDENTIFIER),
        required_columns=("close", "volume"),
    )
    with pytest.raises(ValueError, match="missing columns: volume"):
        normalize_rebalance_input(
            observations,
            dependency_name="execution_bars",
            contract=contract,
        )


def test_seed_lookup_is_one_set_based_request_for_all_assets() -> None:
    calls: list[dict] = []

    def signal_frame(rows: list[tuple[str, str, str, float]]) -> pd.DataFrame:
        frame = pd.DataFrame(
            rows,
            columns=["time_index", "signal_uid", ASSET_IDENTIFIER, "signal_weight"],
        )
        frame["time_index"] = pd.to_datetime(frame["time_index"], utc=True)
        return frame.set_index(["time_index", "signal_uid", ASSET_IDENTIFIER])

    class SourceManager:
        def get_df_between_dates(self, **kwargs):
            calls.append({"kind": "window", **kwargs})
            return signal_frame([("2026-01-03T00:00:00Z", "signal-a", "btc", 0.6)])

        def get_last_observation(self, **kwargs):
            calls.append({"kind": "seed", **kwargs})
            return signal_frame(
                [
                    ("2026-01-01T00:00:00Z", "signal-a", "btc", 0.5),
                    ("2026-01-02T00:00:00Z", "signal-a", "eth", 0.5),
                ]
            )

    source = SourceManager()
    _window, seed = fetch_asset_observations(
        source,
        start=pd.Timestamp("2026-01-03T00:00:00Z"),
        end=pd.Timestamp("2026-01-04T00:00:00Z"),
        asset_identifiers=["btc", "eth"],
        extra_dimension_filters={"signal_uid": ["signal-a"]},
    )
    seed_calls = [call for call in calls if call["kind"] == "seed"]
    assert len(seed_calls) == 1
    assert seed_calls[0]["dimension_filters"] == {
        ASSET_IDENTIFIER: ["btc", "eth"],
        "signal_uid": ["signal-a"],
    }
    assert seed_calls[0]["dimension_range_map"] == [
        {
            "coordinate": {
                "signal_uid": "signal-a",
                ASSET_IDENTIFIER: asset_identifier,
            },
            "end_date": pd.Timestamp("2026-01-03T00:00:00Z").to_pydatetime(),
            "end_date_operand": "<",
        }
        for asset_identifier in ["btc", "eth"]
    ]
    assert set(seed.index.get_level_values(ASSET_IDENTIFIER)) == {"btc", "eth"}
    assert set(seed["signal_uid"]) == {"signal-a"}


def test_signal_after_calendar_cutoff_is_not_applied_retroactively() -> None:
    observations = pd.DataFrame(
        [
            ("2026-01-02T20:59:00Z", "signal", "btc", 0.6),
            ("2026-01-02T20:59:00Z", "signal", "eth", 0.4),
            ("2026-01-02T21:01:00Z", "signal", "btc", 0.2),
            ("2026-01-02T21:01:00Z", "signal", "eth", 0.8),
        ],
        columns=["time_index", "signal_uid", ASSET_IDENTIFIER, "signal_weight"],
    )
    observations["time_index"] = pd.to_datetime(observations["time_index"], utc=True)
    observations = observations.set_index(["time_index", "signal_uid", ASSET_IDENTIFIER])

    class CanonicalSource:
        update_statistics = None

        def get_df_between_dates(self, **kwargs):
            start = pd.Timestamp(kwargs["start_date"])
            end = pd.Timestamp(kwargs["end_date"])
            times = observations.index.get_level_values("time_index")
            return observations[(times >= start) & (times <= end)]

        def get_last_observation(self, **kwargs):
            end = pd.Timestamp(kwargs["dimension_range_map"][0]["end_date"])
            times = observations.index.get_level_values("time_index")
            return observations[times < end]

    class TestSignal(SignalWeights):
        @property
        def signal_uid(self) -> str:
            return "signal"

        def get_asset_list(self):
            return ["btc", "eth"]

        def maximum_forward_fill(self):
            return timedelta(days=1)

    signal = object.__new__(TestSignal)
    events = pd.DatetimeIndex(
        ["2026-01-02T21:00:00Z", "2026-01-03T21:00:00Z"],
        name="time_index",
    )
    result = signal.interpolate_index(events, signal_weights_node=CanonicalSource())
    assert result.loc[events[0], "btc"] == pytest.approx(0.6)
    assert result.loc[events[0], "eth"] == pytest.approx(0.4)
    assert result.loc[events[1], "btc"] == pytest.approx(0.2)
    assert result.loc[events[1], "eth"] == pytest.approx(0.8)


class ExecutedWeightsSource:
    def __init__(self, *, window: pd.DataFrame, seed: pd.DataFrame) -> None:
        self.window = window
        self.seed = seed
        self.window_calls: list[dict[str, object]] = []
        self.seed_calls: list[dict[str, object]] = []

    @staticmethod
    def _asset_unique_identifier(asset: object) -> str:
        return str(asset)

    def get_df_between_dates(self, **kwargs):
        self.window_calls.append(kwargs)
        return self.window.copy()

    def get_last_observation(self, **kwargs):
        self.seed_calls.append(kwargs)
        return self.seed.copy()


def executed_weights_frame(rows: list[dict[str, object]]) -> pd.DataFrame:
    return pd.DataFrame(rows).set_index(["time_index", PORTFOLIO_IDENTIFIER, ASSET_IDENTIFIER])


def test_immediate_strategy_builds_complete_rebalance_state_at_the_next_prices() -> None:
    timestamps = pd.DatetimeIndex(
        ["2026-01-01T00:00:00Z", "2026-01-02T00:00:00Z"],
        name="time_index",
    )
    signal_frame = pd.DataFrame(
        [
            (timestamp, "signal", asset, weight)
            for timestamp, btc_weight in zip(timestamps, [0.5, 0.6], strict=True)
            for asset, weight in (("btc", btc_weight), ("eth", 1.0 - btc_weight))
        ],
        columns=["time_index", "signal_uid", ASSET_IDENTIFIER, "signal_weight"],
    ).set_index(["time_index", "signal_uid", ASSET_IDENTIFIER])
    signal_frame = signal_frame.reset_index("signal_uid")
    # Each signal fills at the first price observed strictly after it; the first
    # rebalance sizes its shares from the price observed before it.
    fill_times = timestamps + pd.Timedelta(hours=1)
    observed_times = fill_times.insert(0, timestamps[0] - pd.Timedelta(hours=1))
    prices = pd.DataFrame(
        [(time, asset, 100.0) for time in observed_times for asset in ("btc", "eth")],
        columns=["time_index", ASSET_IDENTIFIER, "close"],
    )
    result = always_open_immediate_signal().build_transitions(
        start=timestamps[0],
        end=fill_times[-1],
        signal_observations=signal_frame,
        observed_inputs={"calendar_events": always_open_event_frame("2026-01-01", "2026-01-02")},
        previous_state=None,
        fill_prices=observed_prices(prices, price_column="close"),
    )
    assert set(result["time_index"]) == set(fill_times)
    assert set(result[ASSET_IDENTIFIER]) == {"btc", "eth"}
    assert set(result["execution_status"]) == {"complete"}
    btc = result[
        (result["time_index"] == fill_times[1]) & (result[ASSET_IDENTIFIER] == "btc")
    ].iloc[0]
    assert btc["weight_after"] == pytest.approx(0.6)
    assert btc["weight_before"] == pytest.approx(0.5)


def test_portfolio_core_contains_no_generic_date_range_or_resample() -> None:
    weights_source = inspect.getsource(PortfolioWeights)
    values_source = inspect.getsource(PortfolioValues)
    assert "pd.date_range" not in weights_source + values_source
    assert ".resample(" not in values_source
    assert not hasattr(PortfolioValues, "_generate_new_index")


def test_analytics_uses_actual_source_timestamp_not_bucket_label() -> None:
    source_frame = pd.DataFrame(
        {
            "time_index": pd.to_datetime(
                ["2026-01-01T21:00:00Z", "2026-01-02T20:30:00Z", "2026-01-03T19:00:00Z"]
            ),
            PORTFOLIO_IDENTIFIER: ["portfolio"] * 3,
            "close": [1.0, 1.1, 1.2],
        }
    ).set_index(["time_index", PORTFOLIO_IDENTIFIER])

    class ValuesSource:
        def get_df_between_dates(self, **_kwargs):
            return source_frame

    node = object.__new__(PortfolioAnalytics)
    node.portfolio_values = ValuesSource()
    node.portfolio_identifier = "portfolio"
    node.frequency = "2D"
    node.label = "right"
    node.closed = "right"
    node.timezone = "UTC"
    node.aggregation = "last"
    node.update_hash = "analysis"
    node.update_statistics = None
    node._output_table = PortfolioAnalyticsStorage
    result = node.update()
    assert set(result.index.get_level_values("time_index")) <= set(
        source_frame.index.get_level_values("time_index")
    )
    assert (result.reset_index()["time_index"] == result.reset_index()["source_time_index"]).all()


def test_general_rebalance_strategies_are_supported_exports() -> None:
    import msm_portfolios.rebalance_strategy as strategies

    bars = valuation_source("bars")
    assert strategies.TimeWeighted is TimeWeighted
    assert (
        strategies.TrailingAverageDailyVolumeParticipation
        is TrailingAverageDailyVolumeParticipation
    )
    assert strategies.VolumeParticipation is VolumeParticipation
    assert strategies.LiquidityConstrained is LiquidityConstrained
    assert TimeWeighted(execution_bars_instance=bars).declared_dependencies() == {
        "execution_bars": bars
    }


def test_trailing_daily_volume_strategy_declares_both_observed_sources() -> None:
    daily = valuation_source("daily-liquidity")
    intraday = valuation_source("execution-bars")
    strategy = TrailingAverageDailyVolumeParticipation(
        daily_liquidity_instance=daily,
        execution_bars_instance=intraday,
    )

    assert strategy.declared_dependencies() == {
        "daily_liquidity": daily,
        "execution_bars": intraday,
    }
    assert strategy.required_input_contract()["daily_liquidity"].required_columns == (
        "vwap",
        "volume",
    )
    assert strategy.required_input_contract()["execution_bars"].required_columns == (
        "close",
        "volume",
    )
    serialized = canonical_rebalance_strategy_configuration(strategy)
    assert "daily-liquidity" in str(serialized)
    assert "execution-bars" in str(serialized)
    start = pd.Timestamp("2026-01-01T00:00:00Z")
    source_start, source_end = strategy.dependency_window(
        "daily_liquidity",
        start,
        start + pd.Timedelta(days=1),
    )
    assert source_start == start - pd.Timedelta(days=60)
    assert source_end == start + pd.Timedelta(days=1)


def test_rebalance_base_allows_new_descriptive_strategy_categories() -> None:
    from msm_portfolios.rebalance_strategy import RebalanceStrategyBase

    strategy = RebalanceStrategyBase(timing_mode="custom_simulation_events")
    assert strategy.timing_mode == "custom_simulation_events"


def test_strategy_must_consolidate_same_timestamp_input_precedence() -> None:
    duplicate_time = pd.Timestamp("2026-01-01T01:00:00Z")
    with pytest.raises(ValueError, match="must consolidate strategy input precedence"):
        ImmediateSignal._normalize_events(
            pd.DataFrame(
                {
                    "time_index": [duplicate_time, duplicate_time],
                    "event_source": ["quotes", "fills"],
                }
            )
        )


def test_volume_participation_persists_partial_progress_and_restarts() -> None:
    bars_source = valuation_source("bars")
    strategy = VolumeParticipation(
        execution_bars_instance=bars_source,
        rebalance_start="00:00",
        rebalance_end="23:59",
        max_percent_volume_in_bar=0.1,
    )
    signal_time = pd.Timestamp("2026-01-01T00:00:00Z")
    event_times = pd.DatetimeIndex(["2026-01-01T01:00:00Z", "2026-01-01T02:00:00Z"])
    signals = pd.DataFrame(
        [(signal_time, "signal", "btc", 1.0)],
        columns=["time_index", "signal_uid", ASSET_IDENTIFIER, "signal_weight"],
    ).set_index(["time_index", ASSET_IDENTIFIER])
    # The signal's own bar sizes the order: 1 / 100 of the book (#90).
    bars = pd.DataFrame(
        [(timestamp, "btc", 100.0, 2.0) for timestamp in event_times.insert(0, signal_time)],
        columns=["time_index", ASSET_IDENTIFIER, "close", "volume"],
    ).set_index(["time_index", ASSET_IDENTIFIER])

    first = strategy.build_transitions(
        book_unit_value=1_000.0,
        start=event_times[0],
        end=event_times[0],
        signal_observations=signals,
        observed_inputs={"execution_bars": bars.loc[[signal_time, event_times[0]]]},
        previous_state=None,
    )
    assert first.iloc[0]["execution_status"] == "partial"
    # 10% of the bar's 2 shares, on a $1,000 book: 0.0002 of the book, 2% of its NAV.
    assert first.iloc[0]["executed_quantity"] == pytest.approx(0.0002)
    assert first.iloc[0]["weight_after"] == pytest.approx(0.02)

    resumed = strategy.build_transitions(
        book_unit_value=1_000.0,
        start=event_times[1],
        end=event_times[1],
        signal_observations=pd.DataFrame(),
        observed_inputs={"execution_bars": bars.loc[[event_times[1]]]},
        previous_state=first,
    )
    assert resumed.iloc[0]["weight_before"] == pytest.approx(0.02)
    assert resumed.iloc[0]["weight_after"] == pytest.approx(0.04)
    assert resumed.iloc[0]["remaining_weight_delta"] == pytest.approx(0.96)


def test_liquidity_strategy_writes_no_row_when_capacity_is_zero() -> None:
    """Only a step of an order writes a row (#90): without liquidity the order waits."""
    liquidity_source = valuation_source("liquidity")
    strategy = LiquidityConstrained(
        liquidity_source_instance=liquidity_source,
    )
    signal_time = pd.Timestamp("2026-01-01T00:00:00Z")
    event_time = pd.Timestamp("2026-01-01T01:00:00Z")
    signals = pd.DataFrame(
        [(signal_time, "signal", "btc", 1.0)],
        columns=["time_index", "signal_uid", ASSET_IDENTIFIER, "signal_weight"],
    ).set_index(["time_index", ASSET_IDENTIFIER])
    observations = pd.DataFrame(
        [(signal_time, "btc", 100.0, 0.0), (event_time, "btc", 100.0, 0.0)],
        columns=["time_index", ASSET_IDENTIFIER, "mid_price", "available_notional"],
    ).set_index(["time_index", ASSET_IDENTIFIER])

    result = strategy.build_transitions(
        book_unit_value=1_000.0,
        start=event_time,
        end=event_time,
        signal_observations=signals,
        observed_inputs={"available_liquidity": observations},
        previous_state=None,
    )
    assert result.empty


def test_new_signal_supersedes_unfinished_intent_before_partial_execution() -> None:
    bars_source = valuation_source("bars")
    strategy = VolumeParticipation(
        execution_bars_instance=bars_source,
        rebalance_start="00:00",
        rebalance_end="23:59",
        max_percent_volume_in_bar=0.1,
    )
    first_event = pd.Timestamp("2026-01-01T01:00:00Z")
    second_event = pd.Timestamp("2026-01-01T02:00:00Z")
    first_signal = pd.DataFrame(
        [(pd.Timestamp("2026-01-01T00:00:00Z"), "btc", 1.0)],
        columns=["time_index", ASSET_IDENTIFIER, "signal_weight"],
    ).set_index(["time_index", ASSET_IDENTIFIER])
    # The signal's own bar sizes the first order; the 01:00 bar sizes the second.
    first_bar = pd.DataFrame(
        [(pd.Timestamp("2026-01-01T00:00:00Z"), "btc", 100.0, 2.0), (first_event, "btc", 100.0, 2.0)],
        columns=["time_index", ASSET_IDENTIFIER, "close", "volume"],
    ).set_index(["time_index", ASSET_IDENTIFIER])
    first = strategy.build_transitions(
        book_unit_value=1_000.0,
        start=first_event,
        end=first_event,
        signal_observations=first_signal,
        observed_inputs={"execution_bars": first_bar},
        previous_state=None,
    )

    second_signal = pd.DataFrame(
        [
            (pd.Timestamp("2026-01-01T00:00:00Z"), "btc", 1.0),
            (pd.Timestamp("2026-01-01T01:30:00Z"), "btc", 0.5),
        ],
        columns=["time_index", ASSET_IDENTIFIER, "signal_weight"],
    ).set_index(["time_index", ASSET_IDENTIFIER])
    second_bar = pd.DataFrame(
        [(second_event, "btc", 100.0, 2.0)],
        columns=["time_index", ASSET_IDENTIFIER, "close", "volume"],
    ).set_index(["time_index", ASSET_IDENTIFIER])
    second = strategy.build_transitions(
        book_unit_value=1_000.0,
        start=second_event,
        end=second_event,
        signal_observations=second_signal,
        observed_inputs={"execution_bars": pd.concat([first_bar, second_bar])},
        previous_state=first,
    )

    # The newer target replaces the running rebalance at its first bar; the old
    # orders end without a row (#90, as at the next observed price).
    assert second["execution_status"].tolist() == ["partial"]
    assert second.iloc[0]["rebalance_intent_id"] != first.iloc[0]["rebalance_intent_id"]
    assert second.iloc[0]["target_weight"] == 0.5
    assert second.iloc[0]["weight_before"] == pytest.approx(0.02)
    assert second.iloc[0]["weight_after"] == pytest.approx(0.04)


def test_trailing_daily_volume_uses_prior_capacity_but_intraday_execution_price() -> None:
    strategy = TrailingAverageDailyVolumeParticipation(
        daily_liquidity_instance=valuation_source("daily-liquidity"),
        execution_bars_instance=valuation_source("execution-bars"),
        lookback_observations=2,
        history_lookback_days=10,
        execution_start="00:00",
        execution_end="23:59",
        max_daily_participation=0.10,
        max_bar_participation=0.20,
    )
    signal_time = pd.Timestamp("2025-12-31T22:00:00Z")
    event_times = pd.DatetimeIndex(
        [
            "2026-01-01T10:00:00Z",
            "2026-01-01T11:00:00Z",
            "2026-01-01T12:00:00Z",
        ]
    )
    signals = pd.DataFrame(
        [(signal_time, "btc", 1.0)],
        columns=["time_index", ASSET_IDENTIFIER, "signal_weight"],
    ).set_index(["time_index", ASSET_IDENTIFIER])
    daily = pd.DataFrame(
        [
            (pd.Timestamp("2025-12-30T21:00:00Z"), "btc", 100.0, 100.0),
            (pd.Timestamp("2025-12-31T21:00:00Z"), "btc", 200.0, 100.0),
            # This completed-daily value is not available at the execution session start.
            (pd.Timestamp("2026-01-01T23:59:00Z"), "btc", 1_000.0, 1_000.0),
        ],
        columns=["time_index", ASSET_IDENTIFIER, "vwap", "volume"],
    ).set_index(["time_index", ASSET_IDENTIFIER])
    bars = pd.DataFrame(
        [
            # The signal's own bar sizes the order: 1 / 50 of the book (#90).
            (signal_time, "btc", 50.0, 100.0),
            (event_times[0], "btc", 50.0, 100.0),
            (event_times[1], "btc", 60.0, 100.0),
            (event_times[2], "btc", 70.0, 100.0),
        ],
        columns=["time_index", ASSET_IDENTIFIER, "close", "volume"],
    ).set_index(["time_index", ASSET_IDENTIFIER])

    result = strategy.build_transitions(
        book_unit_value=10_000.0,
        start=event_times[0],
        end=event_times[-1],
        signal_observations=signals,
        observed_inputs={"daily_liquidity": daily, "execution_bars": bars},
        previous_state=None,
    )

    # $1,000 at 10:00, then the $500 left of the daily cap at 11:00. The cap leaves
    # nothing to trade at 12:00: no trade, no row.
    assert result["time_index"].tolist() == list(event_times[:2])
    assert result["execution_price"].tolist() == [50.0, 60.0]
    # Shares of the $10,000 book: 20 and 500 / 60 shares of the asset.
    assert (result["executed_quantity"] * 10_000.0).tolist() == pytest.approx(
        [20.0, 500.0 / 60.0]
    )
    # The weights come from the book's shares at each bar's price: 0.17 of a NAV of 1.02.
    assert result["weight_after"].tolist() == pytest.approx([0.10, 0.17 / 1.02])
    states = [strategy.parse_strategy_state(row)["bar"] for row in result.to_dict("records")]
    assert [state["daily_notional_consumed"] for state in states] == pytest.approx(
        [1_000.0, 1_500.0]
    )
    assert states[-1]["trailing_average_daily_notional"] == pytest.approx(15_000.0)
    assert states[-1]["daily_notional_limit"] == pytest.approx(1_500.0)
    assert states[-1]["daily_notional_remaining"] == pytest.approx(0.0)


def test_trailing_daily_volume_daily_cap_survives_restart_and_target_supersession() -> None:
    strategy = TrailingAverageDailyVolumeParticipation(
        daily_liquidity_instance=valuation_source("daily-liquidity"),
        execution_bars_instance=valuation_source("execution-bars"),
        lookback_observations=2,
        history_lookback_days=10,
        execution_start="00:00",
        execution_end="23:59",
        max_daily_participation=0.10,
        max_bar_participation=1.0,
    )
    first_event = pd.Timestamp("2026-01-01T10:00:00Z")
    second_event = pd.Timestamp("2026-01-01T11:00:00Z")
    daily = pd.DataFrame(
        [
            (pd.Timestamp("2025-12-30T21:00:00Z"), "btc", 100.0, 100.0),
            (pd.Timestamp("2025-12-31T21:00:00Z"), "btc", 200.0, 100.0),
        ],
        columns=["time_index", ASSET_IDENTIFIER, "vwap", "volume"],
    ).set_index(["time_index", ASSET_IDENTIFIER])
    first_signal = pd.DataFrame(
        [(pd.Timestamp("2025-12-31T22:00:00Z"), "btc", 1.0)],
        columns=["time_index", ASSET_IDENTIFIER, "signal_weight"],
    ).set_index(["time_index", ASSET_IDENTIFIER])
    first_bar = pd.DataFrame(
        [(pd.Timestamp("2025-12-31T22:00:00Z"), "btc", 50.0, 20.0), (first_event, "btc", 50.0, 20.0)],
        columns=["time_index", ASSET_IDENTIFIER, "close", "volume"],
    ).set_index(["time_index", ASSET_IDENTIFIER])
    first = strategy.build_transitions(
        book_unit_value=10_000.0,
        start=first_event,
        end=first_event,
        signal_observations=first_signal,
        observed_inputs={"daily_liquidity": daily, "execution_bars": first_bar},
        previous_state=None,
    )

    second_signal = pd.DataFrame(
        [
            (pd.Timestamp("2025-12-31T22:00:00Z"), "btc", 1.0),
            (pd.Timestamp("2026-01-01T10:30:00Z"), "btc", 0.5),
        ],
        columns=["time_index", ASSET_IDENTIFIER, "signal_weight"],
    ).set_index(["time_index", ASSET_IDENTIFIER])
    second_bar = pd.DataFrame(
        [(second_event, "btc", 50.0, 20.0)],
        columns=["time_index", ASSET_IDENTIFIER, "close", "volume"],
    ).set_index(["time_index", ASSET_IDENTIFIER])
    resumed = strategy.build_transitions(
        book_unit_value=10_000.0,
        start=second_event,
        end=second_event,
        signal_observations=second_signal,
        observed_inputs={
            "daily_liquidity": daily,
            "execution_bars": pd.concat([first_bar, second_bar]),
        },
        previous_state=first,
    )

    first_state = strategy.parse_strategy_state(first.iloc[0].to_dict())["bar"]
    assert first_state["daily_notional_consumed"] == pytest.approx(1_000.0)
    # The newer target replaces the running one and trades the $500 left of the cap.
    assert resumed["execution_status"].tolist() == ["partial"]
    assert resumed.iloc[-1]["target_weight"] == 0.5
    assert resumed.iloc[-1]["executed_quantity"] * 10_000.0 * 50.0 == (
        pytest.approx(500.0)
    )
    assert resumed.iloc[-1]["weight_after"] == pytest.approx(0.15)
    state = strategy.parse_strategy_state(resumed.iloc[-1].to_dict())["bar"]
    assert state["daily_notional_consumed"] == pytest.approx(1_500.0)


def test_trailing_daily_volume_waits_for_required_completed_history() -> None:
    strategy = TrailingAverageDailyVolumeParticipation(
        daily_liquidity_instance=valuation_source("daily-liquidity"),
        execution_bars_instance=valuation_source("execution-bars"),
        lookback_observations=2,
        history_lookback_days=10,
        execution_start="00:00",
        execution_end="23:59",
    )
    event_time = pd.Timestamp("2026-01-01T10:00:00Z")
    signals = pd.DataFrame(
        [(pd.Timestamp("2025-12-31T22:00:00Z"), "btc", 1.0)],
        columns=["time_index", ASSET_IDENTIFIER, "signal_weight"],
    ).set_index(["time_index", ASSET_IDENTIFIER])
    daily = pd.DataFrame(
        [(pd.Timestamp("2025-12-31T21:00:00Z"), "btc", 100.0, 100.0)],
        columns=["time_index", ASSET_IDENTIFIER, "vwap", "volume"],
    ).set_index(["time_index", ASSET_IDENTIFIER])
    bars = pd.DataFrame(
        [(pd.Timestamp("2025-12-31T22:00:00Z"), "btc", 50.0, 100.0), (event_time, "btc", 50.0, 100.0)],
        columns=["time_index", ASSET_IDENTIFIER, "close", "volume"],
    ).set_index(["time_index", ASSET_IDENTIFIER])

    result = strategy.build_transitions(
        book_unit_value=10_000.0,
        start=event_time,
        end=event_time,
        signal_observations=signals,
        observed_inputs={"daily_liquidity": daily, "execution_bars": bars},
        previous_state=None,
    )

    # One completed day of the two required: no capacity, so the order waits and only
    # a step of it would write a row (#90).
    assert result.empty
    context = strategy.prepare_execution_context(
        events=pd.DataFrame({"time_index": [event_time], "event_source": "execution_bars"}),
        observed_inputs={"daily_liquidity": daily, "execution_bars": bars},
    )
    capacity = context.capacity_by_event_asset[(event_time, "btc")]
    assert capacity.history_observations == 1
    assert capacity.average_daily_notional is None


def test_trailing_daily_volume_resets_consumption_for_the_next_session() -> None:
    strategy = TrailingAverageDailyVolumeParticipation(
        daily_liquidity_instance=valuation_source("daily-liquidity"),
        execution_bars_instance=valuation_source("execution-bars"),
        lookback_observations=2,
        history_lookback_days=10,
        execution_start="00:00",
        execution_end="23:59",
        max_daily_participation=0.10,
        max_bar_participation=1.0,
    )
    first_event = pd.Timestamp("2026-01-01T10:00:00Z")
    next_event = pd.Timestamp("2026-01-02T10:00:00Z")
    signals = pd.DataFrame(
        [(pd.Timestamp("2025-12-31T22:00:00Z"), "btc", 1.0)],
        columns=["time_index", ASSET_IDENTIFIER, "signal_weight"],
    ).set_index(["time_index", ASSET_IDENTIFIER])
    first_history = pd.DataFrame(
        [
            (pd.Timestamp("2025-12-30T21:00:00Z"), "btc", 100.0, 100.0),
            (pd.Timestamp("2025-12-31T21:00:00Z"), "btc", 200.0, 100.0),
        ],
        columns=["time_index", ASSET_IDENTIFIER, "vwap", "volume"],
    ).set_index(["time_index", ASSET_IDENTIFIER])
    first_bar = pd.DataFrame(
        [(pd.Timestamp("2025-12-31T22:00:00Z"), "btc", 50.0, 30.0), (first_event, "btc", 50.0, 30.0)],
        columns=["time_index", ASSET_IDENTIFIER, "close", "volume"],
    ).set_index(["time_index", ASSET_IDENTIFIER])
    first = strategy.build_transitions(
        book_unit_value=10_000.0,
        start=first_event,
        end=first_event,
        signal_observations=signals,
        observed_inputs={"daily_liquidity": first_history, "execution_bars": first_bar},
        previous_state=None,
    )

    next_history = pd.concat(
        [
            first_history,
            pd.DataFrame(
                [(pd.Timestamp("2026-01-01T21:00:00Z"), "btc", 300.0, 100.0)],
                columns=["time_index", ASSET_IDENTIFIER, "vwap", "volume"],
            ).set_index(["time_index", ASSET_IDENTIFIER]),
        ]
    )
    next_bar = pd.DataFrame(
        [(next_event, "btc", 50.0, 20.0)],
        columns=["time_index", ASSET_IDENTIFIER, "close", "volume"],
    ).set_index(["time_index", ASSET_IDENTIFIER])
    resumed = strategy.build_transitions(
        book_unit_value=10_000.0,
        start=next_event,
        end=next_event,
        signal_observations=pd.DataFrame(),
        observed_inputs={"daily_liquidity": next_history, "execution_bars": next_bar},
        previous_state=first,
    )

    first_state = strategy.parse_strategy_state(first.iloc[0].to_dict())["bar"]
    assert first_state["daily_notional_consumed"] == pytest.approx(1_500.0)
    state = strategy.parse_strategy_state(resumed.iloc[0].to_dict())["bar"]
    assert state["session_date"] == "2026-01-02"
    assert state["daily_notional_consumed"] == pytest.approx(1_000.0)
    assert state["trailing_average_daily_notional"] == pytest.approx(25_000.0)


def test_portfolio_value_node_is_not_asset_scoped() -> None:
    assert PortfolioValues.asset_column is None
    assert PortfolioWeights.asset_column == ASSET_IDENTIFIER
    assert SignalWeights.asset_identity_dimension == ASSET_IDENTIFIER


def test_retired_fixed_frame_strategy_api_is_not_exposed() -> None:
    strategy = always_open_immediate_signal()
    assert not hasattr(strategy, "execution_timestamps")
    assert not hasattr(strategy, "apply_rebalance_logic")
