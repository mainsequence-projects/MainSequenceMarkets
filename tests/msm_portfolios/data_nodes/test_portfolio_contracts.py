from __future__ import annotations

from types import SimpleNamespace

import pytest

from msm.data_nodes.utils.storage_schema import storage_column_dtypes_map
from msm_portfolios.data_nodes.base import (
    AssetScopedPortfolioCanonicalDataNode,
    PortfolioCanonicalDataNode,
    PortfolioCanonicalDataNodeConfiguration,
)
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
