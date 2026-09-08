from __future__ import annotations

import inspect
from datetime import date, timedelta
from types import SimpleNamespace

import pandas as pd
import pytest
from pydantic import ValidationError

from mainsequence.client.metatables import TimeIndexMetaTable
from mainsequence.meta_tables import TimeIndexTableUpdater
from mainsequence.meta_tables.time_index_table_updates.configuration import (
    ConfigRebuilder,
    Serializer,
    hash_signature,
)
from msm.data_nodes.utils.storage_schema import storage_column_dtypes_map
from msm.models import AssetTable, PortfolioTable
from msm_portfolios.configuration import (
    PortfolioBuildConfiguration,
    ValuationAlignmentPolicy,
    canonical_rebalance_strategy_configuration,
    canonical_valuation_source_configuration,
)
from msm_portfolios.data_nodes import (
    AssetScopedPortfolioCanonicalDataNode,
    PortfolioAnalytics,
    PortfolioAnalyticsConfiguration,
    PortfolioCalendarEvents,
    PortfolioCalendarEventsConfiguration,
    PortfolioCanonicalDataNode,
    PortfolioCanonicalDataNodeConfiguration,
    PortfolioRebalance,
    PortfolioWeights,
    PortfoliosDataNode,
    SignalWeights,
    SignalWeightsConfiguration,
)
from msm_portfolios.data_nodes.constants import ASSET_IDENTIFIER, PORTFOLIO_IDENTIFIER
from msm_portfolios.data_nodes.portfolios.storage import (
    PortfolioAnalyticsStorage,
    PortfolioCalendarEventsStorage,
    PortfolioRebalanceStateStorage,
    PortfolioWeightsStorage,
    PortfoliosStorage,
)
from msm_portfolios.data_nodes.portfolios.rebalance import normalize_rebalance_input
from msm_portfolios.data_nodes.portfolios.temporal import (
    align_asset_observations,
    fetch_asset_observations,
)
from msm_portfolios.data_nodes.signals.storage import SignalWeightsStorage
from msm_portfolios.models import portfolio_sqlalchemy_models
from msm_portfolios.rebalance_strategy import (
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
        (PortfolioWeights, PortfolioWeightsStorage),
        (PortfolioRebalance, PortfolioRebalanceStateStorage),
        (PortfolioCalendarEvents, PortfolioCalendarEventsStorage),
        (SignalWeights, SignalWeightsStorage),
        (PortfoliosDataNode, PortfoliosStorage),
        (PortfolioAnalytics, PortfolioAnalyticsStorage),
    ],
)
def test_portfolio_nodes_source_schema_from_storage(node_cls, storage_cls) -> None:
    assert node_cls._column_dtypes_map_for_storage(storage_cls) == storage_column_dtypes_map(
        storage_cls
    )
    assert node_cls._required_output_table() is storage_cls


def test_portfolio_run_matches_sdk_8_1_runtime_controls() -> None:
    parameters = inspect.signature(PortfoliosDataNode.run).parameters
    assert {"update_tree", "update_only_tree", "override_update_stats", "update_pointers"} <= set(
        parameters
    )
    assert "force_update" not in parameters


def test_portfolio_configurations_do_not_carry_storage_schema() -> None:
    assert "index_names" not in PortfolioCanonicalDataNodeConfiguration.model_fields
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
        portfolio_values_instance=valuation_source("portfolio-values"),
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
    assert "valuation_alignment_policy" in PortfolioBuildConfiguration.model_fields
    assert "portfolio_prices_frequency" not in PortfolioBuildConfiguration.model_fields
    assert "price_alignment_policy" not in PortfolioBuildConfiguration.model_fields
    assert ValuationAlignmentPolicy().fail_on_missing_values is True


def test_valuation_source_configuration_uses_sdk_identity() -> None:
    source = valuation_source("source-a")
    payload = canonical_valuation_source_configuration(source)
    assert payload
    assert "source-a" in str(payload)


def test_rebalance_strategy_serialization_distinguishes_temporal_owners() -> None:
    events = valuation_source("calendar-events")
    immediate = canonical_rebalance_strategy_configuration(ImmediateSignal())
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


def test_valuation_staleness_is_sdk_hash_serializable_and_reversible() -> None:
    serialized = Serializer().serialize_init_kwargs(
        {
            "policy": ValuationAlignmentPolicy(
                maximum_staleness=timedelta(days=2),
            )
        }
    )

    assert serialized["policy"]["serialized_model"]["maximum_staleness"] == "P2D"
    assert hash_signature(serialized)[0]
    assert ConfigRebuilder().rebuild(serialized)["policy"].maximum_staleness == timedelta(days=2)


def test_immediate_signal_uses_only_signal_observation_timestamps() -> None:
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
    result = ImmediateSignal().select_events(
        pd.Timestamp("2026-01-02T15:00:00Z"),
        pd.Timestamp("2026-01-02T17:00:00Z"),
        signal_observations=signals,
        observed_inputs={},
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
        "msm_portfolios.data_nodes.portfolios.calendar_events.resolve_rebalance_calendar",
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


def test_calendar_event_node_rejects_noncanonical_calendar_alias(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calendar = SimpleNamespace(name="XNYS")
    monkeypatch.setattr(
        "msm_portfolios.data_nodes.portfolios.calendar_events.resolve_rebalance_calendar",
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


def test_portfolio_values_depend_on_executed_weights_not_signal_directly() -> None:
    node = object.__new__(PortfoliosDataNode)
    node.portfolio_configuration = object()
    weights = object()
    valuations = object()
    node.valuation_source = valuations
    node._ensure_portfolio_weights_node = lambda: weights
    assert node.dependencies() == {
        "portfolio_weights": weights,
        "valuation_source": valuations,
    }


def test_portfolio_weights_depends_only_on_rebalance_state() -> None:
    node = object.__new__(PortfolioWeights)
    node._portfolio_configuration = object()
    node.portfolio_rebalance = object()
    assert node.dependencies() == {"portfolio_rebalance": node.portfolio_rebalance}


def test_portfolio_rebalance_merges_arbitrary_strategy_dependencies_without_dispatch() -> None:
    signal = valuation_source("signal")
    liquidity = valuation_source("liquidity")
    node = object.__new__(PortfolioRebalance)
    node._portfolio_configuration = object()
    node.signal_weights = signal
    node.rebalance_strategy = LiquidityConstrained(liquidity_source_instance=liquidity)

    assert node.dependencies() == {
        "signal_weights": signal,
        "available_liquidity": liquidity,
    }
    source = inspect.getsource(PortfolioRebalance)
    assert "timing_mode" not in source
    assert "ImmediateSignal" not in source
    assert "VolumeParticipation" not in source
    assert "LiquidityConstrained" not in source


def test_rebalance_and_projection_progress_resolve_nested_asset_state() -> None:
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
    projection.update_statistics = SimpleNamespace(
        index_progress={"portfolio": {"btc": earlier, "eth": latest}},
        max_time_index_value=pd.Timestamp("2026-02-01T00:00:00Z"),
    )

    assert rebalance._latest_transition_time_index_value() == latest
    assert projection._latest_projection_time_index_value() == latest


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


def asset_frame(rows: list[tuple[str, str, float]]) -> pd.DataFrame:
    frame = pd.DataFrame(rows, columns=["time_index", ASSET_IDENTIFIER, "close"])
    frame["time_index"] = pd.to_datetime(frame["time_index"], utc=True)
    return frame.set_index(["time_index", ASSET_IDENTIFIER])


def test_per_asset_asof_alignment_uses_distinct_seed_observations() -> None:
    observations = asset_frame(
        [
            ("2026-01-01T20:00:00Z", "btc", 100.0),
            ("2026-01-02T19:00:00Z", "eth", 200.0),
            ("2026-01-03T20:00:00Z", "btc", 110.0),
        ]
    )
    target = pd.DatetimeIndex(["2026-01-03T20:00:00Z"])
    aligned = align_asset_observations(
        observations,
        target_index=target,
        asset_identifiers=["btc", "eth"],
        value_columns=["close"],
        maximum_staleness=timedelta(days=2),
        fail_on_missing_values=True,
    )
    assert aligned.loc[(pd.Timestamp("2026-01-03T20:00:00Z"), "btc"), "close"] == 110.0
    assert aligned.loc[(pd.Timestamp("2026-01-03T20:00:00Z"), "eth"), "close"] == 200.0


def test_per_asset_asof_alignment_enforces_staleness() -> None:
    observations = asset_frame([("2026-01-01T20:00:00Z", "btc", 100.0)])
    with pytest.raises(ValueError, match="No sufficiently fresh valuation"):
        align_asset_observations(
            observations,
            target_index=pd.DatetimeIndex(["2026-01-03T20:00:00Z"]),
            asset_identifiers=["btc"],
            value_columns=["close"],
            maximum_staleness=timedelta(hours=24),
            fail_on_missing_values=True,
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

    source = object.__new__(SignalWeights)
    source._update_manager = SourceManager()
    source.asset_list = ["btc", "eth"]
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
    signal.use_canonical_signal_weights = True
    signal.canonical_signal_weights_node = CanonicalSource()
    events = pd.DatetimeIndex(
        ["2026-01-02T21:00:00Z", "2026-01-03T21:00:00Z"],
        name="time_index",
    )
    result = signal.interpolate_index(events)
    assert result.loc[events[0], "btc"] == pytest.approx(0.6)
    assert result.loc[events[0], "eth"] == pytest.approx(0.4)
    assert result.loc[events[1], "btc"] == pytest.approx(0.2)
    assert result.loc[events[1], "eth"] == pytest.approx(0.8)


class FrameSource:
    def __init__(self, frame: pd.DataFrame):
        self.frame = frame

    def get_df_between_dates(self, **kwargs):
        start = pd.Timestamp(kwargs["start_date"])
        end = pd.Timestamp(kwargs["end_date"])
        times = self.frame.index.get_level_values("time_index")
        return self.frame[(times >= start) & (times <= end)]

    def get_last_observation(self, **_kwargs):
        return self.frame.iloc[0:0]


def test_immediate_strategy_builds_complete_rebalance_state_at_signal_events() -> None:
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
    result = ImmediateSignal().build_transitions(
        start=timestamps[0],
        end=timestamps[-1],
        signal_observations=signal_frame,
        observed_inputs={},
        previous_state=None,
    )
    assert set(result["time_index"]) == set(timestamps)
    assert set(result[ASSET_IDENTIFIER]) == {"btc", "eth"}
    assert set(result["execution_status"]) == {"complete"}
    btc = result[
        (result["time_index"] == timestamps[1]) & (result[ASSET_IDENTIFIER] == "btc")
    ].iloc[0]
    assert btc["weight_after"] == pytest.approx(0.6)
    assert btc["weight_before"] == pytest.approx(0.5)


def test_portfolio_weights_projects_only_state_events_that_change_execution() -> None:
    first_event = pd.Timestamp("2026-03-09T20:00:00Z")
    next_event = pd.Timestamp("2026-03-10T17:00:00Z")
    state = pd.DataFrame(
        [
            (
                first_event,
                "portfolio",
                "intent-a",
                "btc",
                first_event,
                "available_liquidity",
                "pending",
                1.0,
                0.0,
                0.0,
                0.0,
                1.0,
                100.0,
                None,
                0.0,
                None,
                0.0,
                "{}",
            ),
            (
                next_event,
                "portfolio",
                "intent-a",
                "btc",
                first_event,
                "available_liquidity",
                "partial",
                1.0,
                0.0,
                0.25,
                0.25,
                0.75,
                101.0,
                1.0,
                25.0,
                None,
                2500.0,
                "{}",
            ),
        ],
        columns=[
            "time_index",
            PORTFOLIO_IDENTIFIER,
            "rebalance_intent_id",
            ASSET_IDENTIFIER,
            "target_signal_time_index",
            "event_source",
            "execution_status",
            "target_weight",
            "weight_before",
            "weight_after",
            "executed_weight_delta",
            "remaining_weight_delta",
            "execution_price",
            "executed_quantity",
            "executed_notional",
            "observed_volume",
            "observed_available_liquidity",
            "strategy_state",
        ],
    ).set_index(["time_index", PORTFOLIO_IDENTIFIER, "rebalance_intent_id", ASSET_IDENTIFIER])
    node = object.__new__(PortfolioWeights)
    node.portfolio_rebalance = FrameSource(state)
    node.update_statistics = None
    node._resolve_portfolio_identifier = lambda: "portfolio"
    node._projection_window = lambda _latest: (
        first_event.to_pydatetime(),
        next_event.to_pydatetime(),
    )
    node._last_projected_weights = lambda _latest: None
    result = node._calculate_projected_weights()
    assert result.index.get_level_values("time_index").unique().tolist() == [next_event]
    assert result.index.get_level_values(ASSET_IDENTIFIER).tolist() == ["btc"]
    assert result.loc[(next_event, "btc"), "weight"] == pytest.approx(0.25)


def test_weekly_weights_can_drive_daily_canonical_valuations() -> None:
    days = pd.date_range("2026-01-01", periods=10, freq="D", tz="UTC")
    valuation_rows = [
        (timestamp, asset, 100.0 + day_number)
        for day_number, timestamp in enumerate(days)
        for asset in ("btc", "eth")
    ]
    valuations = pd.DataFrame(
        valuation_rows,
        columns=["time_index", ASSET_IDENTIFIER, "close"],
    ).set_index(["time_index", ASSET_IDENTIFIER])
    weight_times = [days[0], days[7]]
    weights = pd.DataFrame(
        [
            (timestamp, asset, 0.5, 0.0 if timestamp == days[0] else 0.5)
            for timestamp in weight_times
            for asset in ("btc", "eth")
        ],
        columns=["time_index", ASSET_IDENTIFIER, "weight", "weight_before"],
    ).set_index(["time_index", ASSET_IDENTIFIER])

    node = object.__new__(PortfoliosDataNode)
    node.valuation_source = FrameSource(valuations)
    node.valuation_column = "close"
    node.valuation_alignment_policy = ValuationAlignmentPolicy(maximum_staleness=timedelta(days=2))
    node.signal_weights = SimpleNamespace(get_asset_uid_to_override_portfolio_price=lambda: None)
    node.commission_fee = 0.0
    node._latest_portfolio_time_index_value = lambda: None
    node._valuation_window = lambda _latest: (days[0].to_pydatetime(), days[-1].to_pydatetime())
    node._executed_weights_between = lambda **_kwargs: weights
    node._apply_cumulative_portfolio_values = lambda frame: frame.assign(
        close=(frame["return"] + 1.0).cumprod()
    )

    result = node._calculate_portfolio_workflow_values()
    assert result.index.tolist() == days.tolist()
    assert len(weight_times) == 2
    assert len(result) == 10


def test_portfolio_values_preserve_persisted_close_timestamps_and_rerun_noop() -> None:
    close_times = pd.DatetimeIndex(
        calendar_schedule()["market_close"],
        name="time_index",
    )
    valuations = asset_frame(
        [
            (timestamp.isoformat(), "btc", 100.0 + offset)
            for offset, timestamp in enumerate(close_times)
        ]
    )
    weights = pd.DataFrame(
        [(close_times[0], "btc", 1.0, 0.0)],
        columns=["time_index", ASSET_IDENTIFIER, "weight", "weight_before"],
    ).set_index(["time_index", ASSET_IDENTIFIER])

    node = object.__new__(PortfoliosDataNode)
    node.valuation_source = FrameSource(valuations)
    node.valuation_column = "close"
    node.valuation_alignment_policy = ValuationAlignmentPolicy(maximum_staleness=timedelta(days=4))
    node.signal_weights = SimpleNamespace(get_asset_uid_to_override_portfolio_price=lambda: None)
    node.commission_fee = 0.0
    node._latest_portfolio_time_index_value = lambda: None
    node._valuation_window = lambda _latest: (
        close_times[0].to_pydatetime(),
        close_times[-1].to_pydatetime(),
    )
    node._executed_weights_between = lambda **_kwargs: weights
    node._apply_cumulative_portfolio_values = lambda frame: frame.assign(
        close=(frame["return"] + 1.0).cumprod()
    )

    result = node._calculate_portfolio_workflow_values()

    assert result.index.tolist() == close_times.tolist()
    assert result["close_time"].tolist() == close_times.tolist()

    latest = close_times[-1]
    node._latest_portfolio_time_index_value = lambda: latest
    node._valuation_window = lambda _latest: (
        latest.to_pydatetime(),
        (latest + pd.Timedelta(hours=1)).to_pydatetime(),
    )
    assert node._calculate_portfolio_workflow_values().empty


def test_portfolio_core_contains_no_generic_date_range_or_resample() -> None:
    weights_source = inspect.getsource(PortfolioWeights)
    values_source = inspect.getsource(PortfoliosDataNode)
    assert "pd.date_range" not in weights_source + values_source
    assert ".resample(" not in values_source
    assert not hasattr(PortfoliosDataNode, "_generate_new_index")


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

    strategy = RebalanceStrategyBase(timing_mode="external_fill_events")
    assert strategy.timing_mode == "external_fill_events"


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
        total_notional=1_000.0,
    )
    signal_time = pd.Timestamp("2026-01-01T00:00:00Z")
    event_times = pd.DatetimeIndex(["2026-01-01T01:00:00Z", "2026-01-01T02:00:00Z"])
    signals = pd.DataFrame(
        [(signal_time, "signal", "btc", 1.0)],
        columns=["time_index", "signal_uid", ASSET_IDENTIFIER, "signal_weight"],
    ).set_index(["time_index", ASSET_IDENTIFIER])
    bars = pd.DataFrame(
        [(timestamp, "btc", 100.0, 2.0) for timestamp in event_times],
        columns=["time_index", ASSET_IDENTIFIER, "close", "volume"],
    ).set_index(["time_index", ASSET_IDENTIFIER])

    first = strategy.build_transitions(
        start=event_times[0],
        end=event_times[0],
        signal_observations=signals,
        observed_inputs={"execution_bars": bars.loc[[event_times[0]]]},
        previous_state=None,
    )
    assert first.iloc[0]["execution_status"] == "partial"
    assert first.iloc[0]["weight_after"] == pytest.approx(0.02)

    resumed = strategy.build_transitions(
        start=event_times[1],
        end=event_times[1],
        signal_observations=pd.DataFrame(),
        observed_inputs={"execution_bars": bars.loc[[event_times[1]]]},
        previous_state=first,
    )
    assert resumed.iloc[0]["weight_before"] == pytest.approx(0.02)
    assert resumed.iloc[0]["weight_after"] == pytest.approx(0.04)
    assert resumed.iloc[0]["remaining_weight_delta"] == pytest.approx(0.96)


def test_liquidity_strategy_records_pending_state_when_capacity_is_zero() -> None:
    liquidity_source = valuation_source("liquidity")
    strategy = LiquidityConstrained(
        liquidity_source_instance=liquidity_source,
        total_notional=1_000.0,
    )
    signal_time = pd.Timestamp("2026-01-01T00:00:00Z")
    event_time = pd.Timestamp("2026-01-01T01:00:00Z")
    signals = pd.DataFrame(
        [(signal_time, "signal", "btc", 1.0)],
        columns=["time_index", "signal_uid", ASSET_IDENTIFIER, "signal_weight"],
    ).set_index(["time_index", ASSET_IDENTIFIER])
    observations = pd.DataFrame(
        [(event_time, "btc", 100.0, 0.0)],
        columns=["time_index", ASSET_IDENTIFIER, "mid_price", "available_notional"],
    ).set_index(["time_index", ASSET_IDENTIFIER])

    result = strategy.build_transitions(
        start=event_time,
        end=event_time,
        signal_observations=signals,
        observed_inputs={"available_liquidity": observations},
        previous_state=None,
    )
    assert result.iloc[0]["execution_status"] == "pending"
    assert result.iloc[0]["executed_weight_delta"] == 0.0
    assert result.iloc[0]["remaining_weight_delta"] == 1.0


def test_new_signal_supersedes_unfinished_intent_before_partial_execution() -> None:
    bars_source = valuation_source("bars")
    strategy = VolumeParticipation(
        execution_bars_instance=bars_source,
        rebalance_start="00:00",
        rebalance_end="23:59",
        max_percent_volume_in_bar=0.1,
        total_notional=1_000.0,
    )
    first_event = pd.Timestamp("2026-01-01T01:00:00Z")
    second_event = pd.Timestamp("2026-01-01T02:00:00Z")
    first_signal = pd.DataFrame(
        [(pd.Timestamp("2026-01-01T00:00:00Z"), "btc", 1.0)],
        columns=["time_index", ASSET_IDENTIFIER, "signal_weight"],
    ).set_index(["time_index", ASSET_IDENTIFIER])
    first_bar = pd.DataFrame(
        [(first_event, "btc", 100.0, 2.0)],
        columns=["time_index", ASSET_IDENTIFIER, "close", "volume"],
    ).set_index(["time_index", ASSET_IDENTIFIER])
    first = strategy.build_transitions(
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
        start=second_event,
        end=second_event,
        signal_observations=second_signal,
        observed_inputs={"execution_bars": second_bar},
        previous_state=first,
    )

    assert second["execution_status"].tolist() == ["superseded", "partial"]
    assert second.iloc[0]["rebalance_intent_id"] != second.iloc[1]["rebalance_intent_id"]
    assert second.iloc[1]["weight_before"] == pytest.approx(0.02)
    assert second.iloc[1]["weight_after"] == pytest.approx(0.04)


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
        total_notional=10_000.0,
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
            (event_times[0], "btc", 50.0, 100.0),
            (event_times[1], "btc", 60.0, 100.0),
            (event_times[2], "btc", 70.0, 100.0),
        ],
        columns=["time_index", ASSET_IDENTIFIER, "close", "volume"],
    ).set_index(["time_index", ASSET_IDENTIFIER])

    result = strategy.build_transitions(
        start=event_times[0],
        end=event_times[-1],
        signal_observations=signals,
        observed_inputs={"daily_liquidity": daily, "execution_bars": bars},
        previous_state=None,
    )

    assert result["execution_price"].tolist() == [50.0, 60.0, 70.0]
    assert result["executed_notional"].tolist() == pytest.approx([1_000.0, 500.0, 0.0])
    assert result["weight_after"].tolist() == pytest.approx([0.10, 0.15, 0.15])
    assert result["executed_quantity"].tolist()[:2] == pytest.approx([20.0, 500.0 / 60.0])
    state = strategy.parse_strategy_state(result.iloc[-1].to_dict())
    assert state["trailing_average_daily_notional"] == pytest.approx(15_000.0)
    assert state["daily_notional_limit"] == pytest.approx(1_500.0)
    assert state["daily_notional_consumed"] == pytest.approx(1_500.0)


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
        total_notional=10_000.0,
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
        [(first_event, "btc", 50.0, 20.0)],
        columns=["time_index", ASSET_IDENTIFIER, "close", "volume"],
    ).set_index(["time_index", ASSET_IDENTIFIER])
    first = strategy.build_transitions(
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
        start=second_event,
        end=second_event,
        signal_observations=second_signal,
        observed_inputs={"daily_liquidity": daily, "execution_bars": second_bar},
        previous_state=first,
    )

    assert first.iloc[0]["executed_notional"] == pytest.approx(1_000.0)
    assert resumed["execution_status"].tolist() == ["superseded", "partial"]
    assert resumed.iloc[-1]["executed_notional"] == pytest.approx(500.0)
    assert resumed.iloc[-1]["weight_after"] == pytest.approx(0.15)
    state = strategy.parse_strategy_state(resumed.iloc[-1].to_dict())
    assert state["daily_notional_consumed"] == pytest.approx(1_500.0)


def test_trailing_daily_volume_waits_for_required_completed_history() -> None:
    strategy = TrailingAverageDailyVolumeParticipation(
        daily_liquidity_instance=valuation_source("daily-liquidity"),
        execution_bars_instance=valuation_source("execution-bars"),
        lookback_observations=2,
        history_lookback_days=10,
        execution_start="00:00",
        execution_end="23:59",
        total_notional=10_000.0,
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
        [(event_time, "btc", 50.0, 100.0)],
        columns=["time_index", ASSET_IDENTIFIER, "close", "volume"],
    ).set_index(["time_index", ASSET_IDENTIFIER])

    result = strategy.build_transitions(
        start=event_time,
        end=event_time,
        signal_observations=signals,
        observed_inputs={"daily_liquidity": daily, "execution_bars": bars},
        previous_state=None,
    )

    assert result.iloc[0]["execution_status"] == "pending"
    assert result.iloc[0]["executed_notional"] == 0.0
    state = strategy.parse_strategy_state(result.iloc[0].to_dict())
    assert state["history_observations"] == 1
    assert state["trailing_average_daily_notional"] is None


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
        total_notional=10_000.0,
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
        [(first_event, "btc", 50.0, 30.0)],
        columns=["time_index", ASSET_IDENTIFIER, "close", "volume"],
    ).set_index(["time_index", ASSET_IDENTIFIER])
    first = strategy.build_transitions(
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
        start=next_event,
        end=next_event,
        signal_observations=pd.DataFrame(),
        observed_inputs={"daily_liquidity": next_history, "execution_bars": next_bar},
        previous_state=first,
    )

    assert first.iloc[0]["executed_notional"] == pytest.approx(1_500.0)
    assert resumed.iloc[0]["executed_notional"] == pytest.approx(1_000.0)
    state = strategy.parse_strategy_state(resumed.iloc[0].to_dict())
    assert state["session_date"] == "2026-01-02"
    assert state["daily_notional_consumed"] == pytest.approx(1_000.0)
    assert state["trailing_average_daily_notional"] == pytest.approx(25_000.0)


def test_portfolio_value_node_is_not_asset_scoped() -> None:
    assert issubclass(PortfoliosDataNode, PortfolioCanonicalDataNode)
    assert not issubclass(PortfoliosDataNode, AssetScopedPortfolioCanonicalDataNode)
    assert issubclass(PortfolioWeights, AssetScopedPortfolioCanonicalDataNode)


def test_retired_fixed_frame_strategy_api_is_not_exposed() -> None:
    strategy = ImmediateSignal()
    assert not hasattr(strategy, "execution_timestamps")
    assert not hasattr(strategy, "apply_rebalance_logic")
