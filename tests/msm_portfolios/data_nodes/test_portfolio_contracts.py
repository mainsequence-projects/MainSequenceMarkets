from __future__ import annotations

from types import SimpleNamespace

import pandas as pd
import pytest

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
from msm_portfolios.data_nodes.signals import SignalWeights
from msm_portfolios.data_nodes import SignalWeightsConfiguration
from msm_portfolios.data_nodes.signals.storage import SignalWeightsStorage
from msm_portfolios.models import portfolio_sqlalchemy_models

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
