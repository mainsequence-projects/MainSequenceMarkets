from __future__ import annotations

from types import SimpleNamespace

import pandas as pd
import pytest
import msm_portfolios.data_nodes.portfolios as portfolios_module

from mainsequence.meta_tables import APIDataNode, DataNode
from msm.data_nodes.utils.storage_schema import storage_column_dtypes_map
from msm_portfolios.configuration import (
    PortfolioBuildConfiguration,
    PriceAlignmentPolicy,
    canonical_price_source_configuration,
)
from msm_portfolios.contrib.signals.external_weights import ExternalWeightsConfig
from msm_portfolios.contrib.signals.fixed_weights import FixedWeightsConfig
from msm_portfolios.contrib.signals.intraday_trend import IntradayTrend, IntradayTrendConfig
from msm_portfolios.contrib.signals.market_cap import MarketCapConfig
from msm_portfolios.contrib.signals.portfolio_replicator import (
    ETFReplicator,
    ETFReplicatorConfig,
    TrackingStrategyConfiguration,
)
from msm_portfolios.data_nodes.constants import ASSET_IDENTIFIER
from msm_portfolios.data_nodes.base import (
    AssetScopedPortfolioCanonicalDataNode,
    PortfolioCanonicalDataNode,
    PortfolioCanonicalDataNodeConfiguration,
)
from msm_portfolios.enums import PriceTypeNames
from msm_portfolios.data_nodes.portfolios.weights import PortfolioWeights
from msm_portfolios.data_nodes.portfolios import PortfoliosDataNode
from msm_portfolios.data_nodes.portfolios.storage import (
    PortfolioWeightsStorage,
    PortfoliosStorage,
)
from msm_portfolios.rebalance_strategy import ImmediateSignal
from msm_portfolios.data_nodes.signals import SignalWeights
from msm_portfolios.data_nodes import SignalWeightsConfiguration
from msm_portfolios.data_nodes.signals.storage import SignalWeightsStorage
from msm_portfolios.models import SignalMetadataTable, portfolio_sqlalchemy_models
from msm_portfolios.data_nodes.metadata import emit_signal_metadata

PORTFOLIO_NODE_STORAGE = (
    (PortfolioWeights, PortfolioWeightsStorage),
    (SignalWeights, SignalWeightsStorage),
    (PortfoliosDataNode, PortfoliosStorage),
)


class ExplicitPriceSource(DataNode):
    def update(self) -> pd.DataFrame:
        return pd.DataFrame()

    def dependencies(self) -> dict:
        return {}


def explicit_price_source(
    *,
    update_hash: str = "test-price-source",
    data_source_uid: str = "test-data-source",
    source_cls: type[ExplicitPriceSource] = ExplicitPriceSource,
) -> ExplicitPriceSource:
    price_source = object.__new__(source_cls)
    price_source.update_hash = update_hash
    price_source._storage_table = SimpleNamespace(
        get_data_source_uid=lambda: data_source_uid,
    )
    return price_source


class ExamplePriceSource(ExplicitPriceSource):
    def get_df_between_dates(self, **_kwargs):
        frame = pd.DataFrame(
            [
                {
                    "time_index": "2026-01-01T00:00:00Z",
                    ASSET_IDENTIFIER: "btc",
                    "close": 100.0,
                },
                {
                    "time_index": "2026-01-01T00:00:00Z",
                    ASSET_IDENTIFIER: "eth",
                    "close": 200.0,
                },
                {
                    "time_index": "2026-01-01T00:00:00Z",
                    ASSET_IDENTIFIER: "sol",
                    "close": 300.0,
                },
            ]
        )
        frame["time_index"] = pd.to_datetime(frame["time_index"], utc=True)
        return frame.set_index(["time_index", ASSET_IDENTIFIER])


class ProgressSignal(SignalWeights):
    @property
    def signal_uid(self) -> str:
        return "this-signal"


@pytest.mark.parametrize(("node_cls", "storage_cls"), PORTFOLIO_NODE_STORAGE)
def test_portfolio_nodes_source_column_dtypes_from_storage_classes(
    node_cls,
    storage_cls,
) -> None:
    assert not hasattr(node_cls, "_required_column_dtypes_map")
    assert not hasattr(node_cls, "_required_index_names")
    assert node_cls._column_dtypes_map_for_storage(storage_cls) == storage_column_dtypes_map(
        storage_cls
    )
    assert node_cls._required_storage_table() is storage_cls


def test_portfolio_configurations_do_not_carry_storage_schema() -> None:
    assert "index_names" not in PortfolioCanonicalDataNodeConfiguration.model_fields
    assert "index_names" not in SignalWeightsConfiguration.model_fields


def test_portfolio_weights_storage_keys_by_portfolio_identifier() -> None:
    assert PortfolioWeightsStorage.__index_names__ == [
        "time_index",
        "portfolio_identifier",
        ASSET_IDENTIFIER,
    ]
    assert hasattr(PortfolioWeightsStorage, "portfolio_identifier")
    assert not hasattr(PortfolioWeightsStorage, "portfolio_index_identifier")


def test_signal_weights_storage_references_signal_metadata() -> None:
    foreign_keys = SignalWeightsStorage.__table__.c.signal_uid.foreign_keys

    assert len(foreign_keys) == 1
    foreign_key = next(iter(foreign_keys))
    assert foreign_key.column is SignalMetadataTable.__table__.c.signal_uid
    assert foreign_key.ondelete == "RESTRICT"


def test_signal_metadata_emission_uses_registry_upsert_by_default(monkeypatch) -> None:
    captured: dict[str, object] = {}

    def fake_upsert(**kwargs):
        captured.update(kwargs)
        return {"row": kwargs}

    from msm_portfolios.api.market_metadata import SignalMetadata

    monkeypatch.setattr(SignalMetadata, "upsert", staticmethod(fake_upsert))

    result = emit_signal_metadata(
        signal_uid="example-signal",
        signal_description="Example signal",
        updater=None,
    )

    assert result == {"row": captured}
    assert captured == {
        "signal_uid": "example-signal",
        "signal_description": "Example signal",
    }


def test_portfolio_build_configuration_uses_explicit_price_source_contract() -> None:
    assert "price_source_instance" in PortfolioBuildConfiguration.model_fields
    assert "price_column" in PortfolioBuildConfiguration.model_fields
    assert "price_alignment_policy" in PortfolioBuildConfiguration.model_fields
    assert "assets_configuration" not in PortfolioBuildConfiguration.model_fields


def test_price_source_configuration_uses_sdk_data_node_identity() -> None:
    price_source = explicit_price_source(update_hash="prices-node", data_source_uid="source")

    assert canonical_price_source_configuration(price_source) == {
        "is_time_serie_instance": True,
        "update_hash": "prices-node",
        "data_source_uid": "source",
    }

    api_price_source = APIDataNode(data_source_uid="source", storage_hash="registered_prices")
    assert canonical_price_source_configuration(api_price_source) == {
        "is_api_time_serie_instance": True,
        "update_hash": "API_registered_prices",
        "data_source_uid": "source",
    }


def test_fixed_weights_configuration_does_not_require_asset_configuration() -> None:
    assert "signal_assets_configuration" not in FixedWeightsConfig.model_fields


def test_contributed_signal_configs_do_not_hide_price_interpolation() -> None:
    assert "signal_assets_configuration" not in ExternalWeightsConfig.model_fields
    assert "asset_list" in ExternalWeightsConfig.model_fields

    assert "signal_assets_configuration" not in MarketCapConfig.model_fields
    assert "asset_list" in MarketCapConfig.model_fields

    assert "signal_assets_configuration" not in ETFReplicatorConfig.model_fields
    assert "price_source_instance" in ETFReplicatorConfig.model_fields
    assert "etf_price_source_instance" in ETFReplicatorConfig.model_fields

    assert "signal_assets_configuration" not in IntradayTrendConfig.model_fields
    assert "price_source_instance" in IntradayTrendConfig.model_fields


def test_contributed_price_signals_expose_explicit_dependency_names() -> None:
    basket_price_source = explicit_price_source()
    etf_price_source = explicit_price_source()
    replicator = object.__new__(ETFReplicator)
    replicator.signal_configuration = ETFReplicatorConfig(
        asset_list=["btc", "eth"],
        price_source_instance=basket_price_source,
        etf_price_source_instance=etf_price_source,
        etf_ticker="ETF",
        tracking_strategy_configuration=TrackingStrategyConfiguration(),
        etf_asset="ETF",
    )

    assert replicator.dependencies() == {
        "price_source": basket_price_source,
        "etf_price_source": etf_price_source,
    }

    intraday_price_source = explicit_price_source()
    intraday = object.__new__(IntradayTrend)
    intraday.signal_configuration = IntradayTrendConfig(
        price_source_instance=intraday_price_source,
        asset_symbols_by_exchange={"crypto": ["btc", "eth"]},
        calendar="24/7",
    )

    assert intraday.dependencies() == {"price_source": intraday_price_source}


def test_portfolio_values_dependencies_expose_explicit_price_source() -> None:
    signal_weights = object()
    price_source = object()
    node = object.__new__(PortfoliosDataNode)
    node.portfolio_configuration = object()
    node.signal_weights = signal_weights
    node.price_source = price_source

    assert node.dependencies() == {
        "signal_weights": signal_weights,
        "price_source": price_source,
    }


def test_portfolio_values_updates_portfolio_data_node_pointers(monkeypatch) -> None:
    from msm.api.portfolios import Portfolio

    captured: dict[str, object] = {}

    def fake_upsert(**kwargs):
        captured.update(kwargs)
        return SimpleNamespace(uid="portfolio-uid", **kwargs)

    node = object.__new__(PortfoliosDataNode)
    node.signal_weights = object()
    node._required_data_node_update_uid = lambda _node, label: {
        "signal weights": "signal-node-uid",
        "portfolio weights": "weights-node-uid",
        "portfolio values": "values-node-uid",
    }[label]
    portfolio = SimpleNamespace(
        unique_identifier="example-portfolio",
        calendar_uid="calendar-uid",
        calendar_name="CRYPTO_24_7",
        published_index_uid="index-uid",
        backtest_table_price_column_name="close",
    )

    monkeypatch.setattr(Portfolio, "upsert", staticmethod(fake_upsert))

    updated = node._update_portfolio_pointers(
        portfolio=portfolio,
        portfolio_weights_node=object(),
    )

    assert updated.uid == "portfolio-uid"
    assert node.target_portfolio is updated
    assert captured == {
        "unique_identifier": "example-portfolio",
        "calendar_uid": "calendar-uid",
        "calendar_name": "CRYPTO_24_7",
        "published_index_uid": "index-uid",
        "backtest_table_price_column_name": "close",
        "signal_weights_data_node_uid": "signal-node-uid",
        "portfolio_weights_data_node_uid": "weights-node-uid",
        "portfolio_data_node_uid": "values-node-uid",
    }


def test_portfolio_values_identifier_resolution_does_not_stringify_method(monkeypatch) -> None:
    portfolio_configuration = object()
    node = object.__new__(PortfoliosDataNode)
    node._explicit_portfolio_identifier = None
    node._portfolio_configuration = portfolio_configuration
    node._portfolio_resolver = None

    monkeypatch.setattr(
        portfolios_module,
        "get_or_create_portfolio",
        lambda *args, **kwargs: SimpleNamespace(unique_identifier="example-portfolio"),
    )

    assert node._resolve_unique_identifier() == "example-portfolio"


def test_portfolio_values_noop_when_existing_output_is_ahead_of_price_source() -> None:
    class ExplodingCalendar:
        def schedule(self, **_kwargs):
            raise AssertionError("calendar.schedule must not be called")

    node = object.__new__(PortfoliosDataNode)
    node.update_hash = "portfolio-node"
    node._storage_table = SimpleNamespace(get_data_source_uid=lambda: "test-data-source")
    node.price_source = explicit_price_source(update_hash="prices")
    node.rebalancer = SimpleNamespace(calendar=ExplodingCalendar())
    node._calculate_start_end_dates = lambda: (
        pd.Timestamp("2026-01-03T00:00:00Z"),
        pd.Timestamp("2026-01-02T00:00:00Z"),
    )

    frame = node._calculate_portfolio_workflow_values()

    assert frame.empty


def test_portfolio_latest_value_ignores_other_portfolio_global_progress() -> None:
    node = object.__new__(PortfoliosDataNode)
    node._resolved_unique_identifier = "this-portfolio"
    node.update_statistics = SimpleNamespace(
        index_progress={
            "other-portfolio": pd.Timestamp("2026-05-27T00:00:00Z"),
        },
        max_time_index_value=pd.Timestamp("2026-05-27T00:00:00Z"),
    )

    assert node._latest_portfolio_time_index_value() is None


def test_portfolio_latest_value_handles_empty_progress_for_current_portfolio() -> None:
    node = object.__new__(PortfoliosDataNode)
    node._resolved_unique_identifier = "this-portfolio"
    node.update_statistics = SimpleNamespace(
        index_progress=None,
        max_time_index_value=pd.Timestamp("2026-05-27T00:00:00Z"),
    )

    assert node._latest_portfolio_time_index_value() is None


def test_portfolio_latest_value_uses_this_portfolio_progress() -> None:
    this_portfolio_value = pd.Timestamp("2025-01-01T00:00:00Z")
    node = object.__new__(PortfoliosDataNode)
    node._resolved_unique_identifier = "this-portfolio"
    node.update_statistics = SimpleNamespace(
        index_progress={
            "other-portfolio": pd.Timestamp("2026-05-27T00:00:00Z"),
            "this-portfolio": this_portfolio_value,
        },
        max_time_index_value=pd.Timestamp("2026-05-27T00:00:00Z"),
    )

    assert node._latest_portfolio_time_index_value() == this_portfolio_value


def test_signal_latest_value_ignores_other_signal_global_progress() -> None:
    node = object.__new__(ProgressSignal)
    node.update_statistics = SimpleNamespace(
        index_progress={
            "other-signal": {
                "btc": pd.Timestamp("2026-05-27T00:00:00Z"),
            },
        },
        max_time_index_value=pd.Timestamp("2026-05-27T00:00:00Z"),
        _initial_fallback_date=pd.Timestamp("2018-01-01T00:00:00Z"),
    )

    assert node._latest_signal_time_index_value() is None


def test_signal_latest_value_handles_empty_progress_for_current_signal() -> None:
    node = object.__new__(ProgressSignal)
    node.update_statistics = SimpleNamespace(
        index_progress=None,
        max_time_index_value=pd.Timestamp("2026-05-27T00:00:00Z"),
        _initial_fallback_date=pd.Timestamp("2018-01-01T00:00:00Z"),
    )

    assert node._latest_signal_time_index_value() is None


def test_signal_latest_value_uses_current_signal_progress() -> None:
    latest_current_signal_value = pd.Timestamp("2025-01-03T00:00:00Z")
    node = object.__new__(ProgressSignal)
    node.update_statistics = SimpleNamespace(
        index_progress={
            "other-signal": {
                "btc": pd.Timestamp("2026-05-27T00:00:00Z"),
            },
            "this-signal": {
                "btc": pd.Timestamp("2025-01-01T00:00:00Z"),
                "eth": latest_current_signal_value,
            },
        },
        max_time_index_value=pd.Timestamp("2026-05-27T00:00:00Z"),
        _initial_fallback_date=pd.Timestamp("2018-01-01T00:00:00Z"),
    )

    assert node._latest_signal_time_index_value() == latest_current_signal_value


def test_signal_asset_start_date_uses_current_signal_asset_or_fallback() -> None:
    fallback_date = pd.Timestamp("2018-01-01T00:00:00Z")
    btc_signal_value = pd.Timestamp("2025-01-01T00:00:00Z")
    node = object.__new__(ProgressSignal)
    node.update_statistics = SimpleNamespace(
        index_progress={
            "other-signal": {
                "eth": pd.Timestamp("2026-05-27T00:00:00Z"),
            },
            "this-signal": {
                "btc": btc_signal_value,
            },
        },
        max_time_index_value=pd.Timestamp("2026-05-27T00:00:00Z"),
        _initial_fallback_date=fallback_date,
    )

    assert node._signal_asset_start_date("btc") == btc_signal_value
    assert node._signal_asset_start_date("eth") == fallback_date


def test_portfolio_update_window_uses_only_required_price_assets() -> None:
    class ScopedProgress:
        def __init__(self) -> None:
            self.requested_identities: list[str] = []

        def get_index_progress_leaf_values(self):
            raise AssertionError("portfolio update window must not use global source progress")

        def get_earliest_update_for_identity(self, identity):
            self.requested_identities.append(identity)
            return {
                "btc": pd.Timestamp("2026-01-05T00:00:00Z"),
                "eth": pd.Timestamp("2026-01-03T00:00:00Z"),
            }[identity]

    progress = ScopedProgress()
    node = object.__new__(PortfoliosDataNode)
    node.price_source = SimpleNamespace(update_statistics=progress)
    node.signal_weights = SimpleNamespace(
        get_asset_list=lambda: ["btc", "eth"],
        get_asset_uid_to_override_portfolio_price=lambda: None,
    )
    node.required_price_asset_preflight = ["btc", "eth"]
    node.price_alignment_policy = PriceAlignmentPolicy()
    node.portfolio_prices_frequency = "1d"
    node._get_last_weights = lambda: None

    _start_date, end_date = node._calculate_start_end_dates()

    assert end_date == pd.Timestamp("2026-01-04T00:00:00Z")
    assert progress.requested_identities == ["btc", "eth"]


def test_portfolio_update_window_includes_existing_weight_assets() -> None:
    class ScopedProgress:
        def __init__(self) -> None:
            self.requested_identities: list[str] = []

        def get_index_progress_leaf_values(self):
            raise AssertionError("portfolio update window must not use global source progress")

        def get_earliest_update_for_identity(self, identity):
            self.requested_identities.append(identity)
            return {
                "btc": pd.Timestamp("2026-01-05T00:00:00Z"),
                "eth": pd.Timestamp("2026-01-03T00:00:00Z"),
                "sol": pd.Timestamp("2026-01-02T00:00:00Z"),
            }[identity]

    progress = ScopedProgress()
    last_weights = pd.DataFrame(
        {"weights_current": [1.0]},
        index=pd.MultiIndex.from_tuples(
            [(pd.Timestamp("2026-01-01T00:00:00Z"), "sol")],
            names=["time_index", ASSET_IDENTIFIER],
        ),
    )
    node = object.__new__(PortfoliosDataNode)
    node.price_source = SimpleNamespace(update_statistics=progress)
    node.signal_weights = SimpleNamespace(
        get_asset_list=lambda: ["btc", "eth"],
        get_asset_uid_to_override_portfolio_price=lambda: None,
    )
    node.required_price_asset_preflight = ["btc", "eth"]
    node.price_alignment_policy = PriceAlignmentPolicy()
    node.portfolio_prices_frequency = "1d"
    node._get_last_weights = lambda: last_weights

    _start_date, end_date = node._calculate_start_end_dates()

    assert end_date == pd.Timestamp("2026-01-03T00:00:00Z")
    assert progress.requested_identities == ["btc", "eth", "sol"]


def test_portfolio_update_window_requires_price_asset_scope() -> None:
    node = object.__new__(PortfoliosDataNode)
    node.price_source = SimpleNamespace(update_statistics=SimpleNamespace())
    node.signal_weights = SimpleNamespace(
        get_asset_list=lambda: None,
        get_asset_uid_to_override_portfolio_price=lambda: None,
    )
    node.price_alignment_policy = PriceAlignmentPolicy()
    node.portfolio_prices_frequency = "1d"
    node._get_last_weights = lambda: None

    with pytest.raises(ValueError, match="required asset scope"):
        node._calculate_start_end_dates()


def test_portfolio_value_node_is_not_asset_scoped() -> None:
    assert issubclass(PortfoliosDataNode, PortfolioCanonicalDataNode)
    assert not issubclass(PortfoliosDataNode, AssetScopedPortfolioCanonicalDataNode)
    assert issubclass(PortfolioWeights, AssetScopedPortfolioCanonicalDataNode)
    assert issubclass(SignalWeights, AssetScopedPortfolioCanonicalDataNode)


def test_portfolio_bound_dtype_map_uses_instance_storage_table() -> None:
    node = SimpleNamespace(storage_table=SignalWeightsStorage)

    assert PortfolioWeights._bound_column_dtypes_map(node) == storage_column_dtypes_map(
        SignalWeightsStorage
    )


@pytest.mark.parametrize(("_node_cls", "storage_cls"), PORTFOLIO_NODE_STORAGE)
def test_portfolio_storage_classes_are_registered_metatables(_node_cls, storage_cls) -> None:
    assert storage_cls in set(portfolio_sqlalchemy_models())


def test_portfolio_price_alignment_ignores_extra_price_source_assets() -> None:
    node = object.__new__(PortfoliosDataNode)
    node.price_column = PriceTypeNames.CLOSE
    node.price_alignment_policy = PriceAlignmentPolicy()
    node.portfolio_prices_frequency = "1d"

    _raw_prices, aligned_prices = node._interpolate_bars_index(
        new_index=pd.DatetimeIndex([pd.Timestamp("2026-01-01T00:00:00Z")]),
        unique_identifiers=["btc", "eth"],
        index_freq="1D",
        price_source=explicit_price_source(source_cls=ExamplePriceSource),
    )

    assert set(aligned_prices.index.get_level_values(ASSET_IDENTIFIER)) == {"btc", "eth"}


def test_immediate_signal_does_not_require_price_source_volume() -> None:
    time_index = pd.DatetimeIndex(
        [
            pd.Timestamp("2026-01-01T00:00:00Z"),
            pd.Timestamp("2026-01-02T00:00:00Z"),
        ]
    )
    signal_weights = pd.DataFrame(
        [[0.6, 0.4], [0.5, 0.5]],
        index=time_index,
        columns=pd.Index(["btc", "eth"], name=ASSET_IDENTIFIER),
    )
    prices = pd.DataFrame(
        [
            {"time_index": time_index[0], ASSET_IDENTIFIER: "btc", "close": 100.0},
            {"time_index": time_index[0], ASSET_IDENTIFIER: "eth", "close": 200.0},
            {"time_index": time_index[1], ASSET_IDENTIFIER: "btc", "close": 110.0},
            {"time_index": time_index[1], ASSET_IDENTIFIER: "eth", "close": 190.0},
        ]
    ).set_index(["time_index", ASSET_IDENTIFIER])

    weights = ImmediateSignal().apply_rebalance_logic(
        last_rebalance_weights=None,
        signal_weights=signal_weights,
        prices_df=prices,
        price_type=PriceTypeNames.CLOSE,
    )

    assert "volume_current" in weights.columns.get_level_values(0)
    assert "volume_before" in weights.columns.get_level_values(0)
    assert weights["volume_current"].isna().all().all()
    assert weights["volume_before"].isna().all().all()
    assert weights["price_current"].notna().all().all()


def test_required_price_assets_include_previous_portfolio_weights() -> None:
    node = object.__new__(PortfoliosDataNode)
    node.signal_weights = SimpleNamespace(
        get_asset_uid_to_override_portfolio_price=lambda: None,
    )
    signal_weights = pd.DataFrame(
        [[0.6, 0.4]],
        index=pd.DatetimeIndex([pd.Timestamp("2026-01-02T00:00:00Z")]),
        columns=pd.Index(["btc", "eth"], name=ASSET_IDENTIFIER),
    )
    last_weights = pd.DataFrame(
        {"weights_current": [1.0]},
        index=pd.MultiIndex.from_tuples(
            [(pd.Timestamp("2026-01-01T00:00:00Z"), "sol")],
            names=["time_index", ASSET_IDENTIFIER],
        ),
    )

    assert node._required_price_asset_identifiers(
        signal_weights=signal_weights,
        last_rebalance_weights=last_weights,
    ) == ["btc", "eth", "sol"]


def test_missing_required_prices_continue_by_default() -> None:
    node = object.__new__(PortfoliosDataNode)
    node.update_hash = "test-update"
    node._storage_table = SimpleNamespace(get_data_source_uid=lambda: "test-data-source")
    node.price_column = PriceTypeNames.CLOSE
    node.price_alignment_policy = PriceAlignmentPolicy()
    raw_prices = pd.DataFrame(
        [
            {
                "time_index": "2026-01-01T00:00:00Z",
                ASSET_IDENTIFIER: "btc",
                "close": 100.0,
            },
        ]
    )
    raw_prices["time_index"] = pd.to_datetime(raw_prices["time_index"], utc=True)
    raw_prices = raw_prices.set_index(["time_index", ASSET_IDENTIFIER])

    node._diagnose_price_source_coverage(
        raw_prices,
        requested_asset_identifiers=["btc", "eth"],
        price_source=explicit_price_source(update_hash="prices"),
        start_date=pd.Timestamp("2026-01-01T00:00:00Z"),
        end_date=pd.Timestamp("2026-01-02T00:00:00Z"),
    )


def test_missing_required_prices_fail_under_strict_policy() -> None:
    node = object.__new__(PortfoliosDataNode)
    node.update_hash = "test-update"
    node._storage_table = SimpleNamespace(get_data_source_uid=lambda: "test-data-source")
    node.price_column = PriceTypeNames.CLOSE
    node.price_alignment_policy = PriceAlignmentPolicy(fail_on_missing_prices=True)
    raw_prices = pd.DataFrame(
        [
            {
                "time_index": "2026-01-01T00:00:00Z",
                ASSET_IDENTIFIER: "btc",
                "close": 100.0,
            },
        ]
    )
    raw_prices["time_index"] = pd.to_datetime(raw_prices["time_index"], utc=True)
    raw_prices = raw_prices.set_index(["time_index", ASSET_IDENTIFIER])

    with pytest.raises(ValueError, match="missing required signal assets"):
        node._diagnose_price_source_coverage(
            raw_prices,
            requested_asset_identifiers=["btc", "eth"],
            price_source=explicit_price_source(update_hash="prices"),
            start_date=pd.Timestamp("2026-01-01T00:00:00Z"),
            end_date=pd.Timestamp("2026-01-02T00:00:00Z"),
        )
