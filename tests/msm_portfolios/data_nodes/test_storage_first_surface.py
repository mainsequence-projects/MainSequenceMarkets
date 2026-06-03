from __future__ import annotations

from msm.data_nodes.utils.storage_schema import storage_column_dtypes_map
from msm.settings import ASSET_IDENTIFIER_DIMENSION
from msm_portfolios.asset_scope import ASSET_IDENTIFIER
from msm_portfolios.data_nodes.portfolio_weights import PortfolioWeights
from msm_portfolios.data_nodes.portfolios import PortfoliosDataNode
from msm_portfolios.data_nodes.signal_weights import SignalWeights
from msm_portfolios.data_nodes.storage import (
    InterpolatedPricesStorage,
    PortfolioWeightsStorage,
    PortfoliosStorage,
    SignalWeightsStorage,
    VirtualFundHoldingsStorage,
)
from msm_portfolios.models import portfolio_sqlalchemy_models


def test_portfolio_asset_scope_uses_markets_asset_dimension() -> None:
    assert ASSET_IDENTIFIER == ASSET_IDENTIFIER_DIMENSION


def test_portfolio_nodes_expose_storage_first_surface() -> None:
    registered = set(portfolio_sqlalchemy_models())

    for node_cls in (PortfolioWeights, PortfoliosDataNode, SignalWeights):
        assert "__data_node_identifier__" not in node_cls.__dict__
        assert "_default_identifier" not in node_cls.__dict__
        assert "_default_description" not in node_cls.__dict__
        storage_table = node_cls._required_storage_table()
        assert node_cls._default_identifier() == storage_table.metatable_identifier()
        assert node_cls._default_description() == storage_table.__metatable_description__
        assert storage_table in registered
        assert not hasattr(node_cls, "_required_column_dtypes_map")
        assert not hasattr(node_cls, "_required_index_names")
        assert not hasattr(node_cls, "_required_time_index_name")
        assert node_cls._column_dtypes_map_for_storage(storage_table) == storage_column_dtypes_map(
            storage_table
        )
        assert not hasattr(node_cls, "build_mock_frame")
        assert not hasattr(node_cls, "build_schema_bootstrap_frame")
        assert not hasattr(node_cls, "build_initialization_frame")


def test_portfolio_storage_identifiers_use_camel_case_ts_suffix() -> None:
    assert PortfolioWeightsStorage.metatable_identifier() == "PortfolioWeightsTS"
    assert SignalWeightsStorage.metatable_identifier() == "SignalWeightsTS"
    assert PortfoliosStorage.metatable_identifier() == "PortfoliosTS"
    assert InterpolatedPricesStorage.metatable_identifier() == "InterpolatedPricesTS"
    assert VirtualFundHoldingsStorage.metatable_identifier() == "VirtualFundHoldingsTS"
