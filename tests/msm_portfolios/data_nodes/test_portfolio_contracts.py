from __future__ import annotations

import inspect
from datetime import date, timedelta
from types import SimpleNamespace

import pandas as pd
import pytest

from mainsequence.client.metatables import TimeIndexMetaTable
from mainsequence.meta_tables import TimeIndexTableUpdater
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
    PortfolioCanonicalDataNode,
    PortfolioCanonicalDataNodeConfiguration,
    PortfolioWeights,
    PortfoliosDataNode,
    SignalWeights,
    SignalWeightsConfiguration,
)
from msm_portfolios.data_nodes.constants import ASSET_IDENTIFIER, PORTFOLIO_IDENTIFIER
from msm_portfolios.data_nodes.portfolios.storage import (
    PortfolioAnalyticsStorage,
    PortfolioWeightsStorage,
    PortfoliosStorage,
)
from msm_portfolios.data_nodes.portfolios.temporal import (
    align_asset_observations,
    fetch_asset_observations,
)
from msm_portfolios.data_nodes.signals.storage import SignalWeightsStorage
from msm_portfolios.models import portfolio_sqlalchemy_models
from msm_portfolios.rebalance_strategy import CalendarEventSignal, ImmediateSignal


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


def test_analytics_storage_is_in_migration_provider_scope() -> None:
    models = portfolio_sqlalchemy_models()
    assert PortfolioAnalyticsStorage in models
    assert models.index(PortfolioTable) < models.index(PortfolioAnalyticsStorage)


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
    immediate = canonical_rebalance_strategy_configuration(ImmediateSignal())
    close = canonical_rebalance_strategy_configuration(
        CalendarEventSignal(calendar_identifier="XNYS", rebalance_event="market_close")
    )
    open_ = canonical_rebalance_strategy_configuration(
        CalendarEventSignal(calendar_identifier="XNYS", rebalance_event="market_open")
    )
    assert immediate != close
    assert close != open_
    assert "signal_time" in str(immediate)
    assert "calendar_event" in str(close)


def test_immediate_signal_uses_only_signal_observation_timestamps() -> None:
    signal_times = pd.DatetimeIndex(
        ["2026-01-02T14:00:00Z", "2026-01-02T16:00:00Z"],
        name="time_index",
    )
    result = ImmediateSignal().execution_timestamps(
        pd.Timestamp("2026-01-02T15:00:00Z"),
        pd.Timestamp("2026-01-02T17:00:00Z"),
        signal_timestamps=signal_times,
    )
    assert result.tolist() == [pd.Timestamp("2026-01-02T16:00:00Z")]


class FakeCalendar:
    def __init__(self, schedule: pd.DataFrame):
        self._schedule = schedule

    def schedule(self, **_kwargs) -> pd.DataFrame:
        return self._schedule


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


def test_calendar_strategy_preserves_dst_holiday_and_early_close_events() -> None:
    strategy = CalendarEventSignal(calendar_identifier="XNYS", rebalance_event="market_close")
    strategy._calendar_obj = FakeCalendar(calendar_schedule())
    result = strategy.execution_timestamps(
        pd.Timestamp("2026-03-06T00:00:00Z"),
        pd.Timestamp("2026-03-10T23:59:00Z"),
        signal_timestamps=pd.DatetimeIndex([]),
    )
    assert result.tolist() == [
        pd.Timestamp("2026-03-06T21:00:00Z"),
        pd.Timestamp("2026-03-09T20:00:00Z"),
        pd.Timestamp("2026-03-10T17:00:00Z"),
    ]
    assert pd.Timestamp("2026-03-07T21:00:00Z") not in result


def test_calendar_strategy_weekly_cadence_produces_sparse_execution_events() -> None:
    strategy = CalendarEventSignal(
        calendar_identifier="XNYS",
        rebalance_cadence="weekly",
        rebalance_weekday=0,
    )
    strategy._calendar_obj = FakeCalendar(calendar_schedule())
    result = strategy.execution_timestamps(
        pd.Timestamp("2026-03-06T00:00:00Z"),
        pd.Timestamp("2026-03-10T23:59:00Z"),
        signal_timestamps=pd.DatetimeIndex([]),
    )
    assert result.tolist() == [pd.Timestamp("2026-03-09T20:00:00Z")]


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


def test_portfolio_weights_owns_signal_and_execution_valuation_dependencies() -> None:
    node = object.__new__(PortfolioWeights)
    node._portfolio_configuration = object()
    node.signal_weights = object()
    node.execution_valuation_source = object()
    assert node.dependencies() == {
        "signal_weights": node.signal_weights,
        "execution_valuations": node.execution_valuation_source,
    }


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

    class Source:
        def get_df_between_dates(self, **kwargs):
            calls.append({"kind": "window", **kwargs})
            return asset_frame([("2026-01-03T00:00:00Z", "btc", 110.0)])

        def get_last_observation(self, **kwargs):
            calls.append({"kind": "seed", **kwargs})
            return asset_frame(
                [
                    ("2026-01-01T00:00:00Z", "btc", 100.0),
                    ("2026-01-02T00:00:00Z", "eth", 200.0),
                ]
            )

    _window, seed = fetch_asset_observations(
        Source(),
        start=pd.Timestamp("2026-01-03T00:00:00Z"),
        end=pd.Timestamp("2026-01-04T00:00:00Z"),
        asset_identifiers=["btc", "eth"],
    )
    assert len([call for call in calls if call["kind"] == "seed"]) == 1
    assert len(calls[1]["dimension_range_map"]) == 2
    assert set(seed.index.get_level_values(ASSET_IDENTIFIER)) == {"btc", "eth"}


def test_signal_after_calendar_cutoff_is_not_applied_retroactively() -> None:
    before = pd.DataFrame(
        [
            ("2026-01-02T20:59:00Z", "signal", "btc", 0.6),
            ("2026-01-02T20:59:00Z", "signal", "eth", 0.4),
        ],
        columns=["time_index", "signal_uid", ASSET_IDENTIFIER, "signal_weight"],
    )
    before["time_index"] = pd.to_datetime(before["time_index"], utc=True)
    before = before.set_index(["time_index", "signal_uid", ASSET_IDENTIFIER])

    class CanonicalSource:
        update_statistics = None

        def get_df_between_dates(self, **_kwargs):
            return before.iloc[0:0]

        def get_last_observation(self, **_kwargs):
            return before

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
    event = pd.DatetimeIndex(["2026-01-02T21:00:00Z"], name="time_index")
    result = signal.interpolate_index(event)
    assert result.loc[event[0], "btc"] == pytest.approx(0.6)
    assert result.loc[event[0], "eth"] == pytest.approx(0.4)


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


def test_portfolio_weights_calculates_execution_rows_it_owns() -> None:
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
    valuations = asset_frame(
        [
            ("2026-01-01T00:00:00Z", "btc", 100.0),
            ("2026-01-01T00:00:00Z", "eth", 200.0),
            ("2026-01-02T00:00:00Z", "btc", 110.0),
            ("2026-01-02T00:00:00Z", "eth", 190.0),
        ]
    )

    class ExecutionSignal:
        signal_uid = "signal"

        def get_asset_list(self):
            return ["btc", "eth"]

        def get_asset_uid_to_override_portfolio_price(self):
            return None

        def get_df_between_dates(self, **_kwargs):
            return signal_frame

    node = object.__new__(PortfolioWeights)
    node.signal_weights = ExecutionSignal()
    node.rebalancer = ImmediateSignal()
    node.execution_valuation_source = FrameSource(valuations)
    node.valuation_column = "close"
    node.valuation_alignment_policy = ValuationAlignmentPolicy(
        maximum_staleness=timedelta(days=1)
    )
    node.update_statistics = None
    node._resolve_portfolio_identifier = lambda: "portfolio"
    node._execution_window = lambda _latest: (
        timestamps[0].to_pydatetime(),
        timestamps[-1].to_pydatetime(),
    )
    node._last_executed_weights = lambda _latest: None
    result = node._calculate_executed_weights()
    assert set(result.index.get_level_values("time_index")) == set(timestamps)
    assert set(result.index.get_level_values(ASSET_IDENTIFIER)) == {"btc", "eth"}
    assert result.loc[(timestamps[1], "btc"), "weights_current"] == pytest.approx(0.6)


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
    node.valuation_alignment_policy = ValuationAlignmentPolicy(
        maximum_staleness=timedelta(days=2)
    )
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
    assert (
        result.reset_index()["time_index"] == result.reset_index()["source_time_index"]
    ).all()


def test_unfinished_strategies_are_not_supported_exports() -> None:
    import msm_portfolios.rebalance_strategy as strategies
    from msm_portfolios.rebalance_strategy.volume_participation import VolumeParticipation

    assert not hasattr(strategies, "TimeWeighted")
    assert not hasattr(strategies, "VolumeParticipation")
    assert VolumeParticipation().model_dump()["timing_mode"] == "bar_participation"
    with pytest.raises(NotImplementedError):
        VolumeParticipation().apply_rebalance_logic(
            last_rebalance_weights=None,
            start_date=pd.Timestamp("2026-01-01T00:00:00Z"),
            end_date=pd.Timestamp("2026-01-02T00:00:00Z"),
            signal_weights=pd.DataFrame(),
            valuations_df=pd.DataFrame(),
            valuation_column="close",
        )


def test_portfolio_value_node_is_not_asset_scoped() -> None:
    assert issubclass(PortfoliosDataNode, PortfolioCanonicalDataNode)
    assert not issubclass(PortfoliosDataNode, AssetScopedPortfolioCanonicalDataNode)
    assert issubclass(PortfolioWeights, AssetScopedPortfolioCanonicalDataNode)


def test_immediate_signal_calculation_does_not_require_volume() -> None:
    timestamps = pd.DatetimeIndex(["2026-01-01T00:00:00Z", "2026-01-02T00:00:00Z"])
    signal = pd.DataFrame({"btc": [0.5, 0.6], "eth": [0.5, 0.4]}, index=timestamps)
    signal.columns.name = ASSET_IDENTIFIER
    valuations = asset_frame(
        [
            ("2026-01-01T00:00:00Z", "btc", 100.0),
            ("2026-01-01T00:00:00Z", "eth", 200.0),
            ("2026-01-02T00:00:00Z", "btc", 110.0),
            ("2026-01-02T00:00:00Z", "eth", 190.0),
        ]
    )
    result = ImmediateSignal().apply_rebalance_logic(
        last_rebalance_weights=None,
        signal_weights=signal,
        valuations_df=valuations,
        valuation_column="close",
    )
    assert "volume_current" in result.columns.get_level_values(0)
    assert result["volume_current"].isna().all().all()
