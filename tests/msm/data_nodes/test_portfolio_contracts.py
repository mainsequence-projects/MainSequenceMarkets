from __future__ import annotations

from types import SimpleNamespace

import pytest

from msm.data_nodes.utils.storage_schema import storage_column_dtypes_map
from msm.models import markets_sqlalchemy_models
from msm.portfolios.data_nodes import storage_initialization
from msm.portfolios.data_nodes.portfolio_weights import PortfolioWeights
from msm.portfolios.data_nodes.portfolios import PortfoliosDataNode
from msm.portfolios.data_nodes.signal_weights import SignalWeights
from msm.portfolios.data_nodes.storage import (
    PortfolioWeightsStorage,
    PortfoliosStorage,
    SignalWeightsStorage,
)

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
    assert node_cls._column_dtypes_map_for_storage(storage_cls) == storage_column_dtypes_map(
        storage_cls
    )
    assert node_cls._required_storage_table() is storage_cls


def test_portfolio_bound_dtype_map_uses_instance_storage_table() -> None:
    node = SimpleNamespace(storage_table=SignalWeightsStorage)

    assert PortfolioWeights._bound_column_dtypes_map(node) == storage_column_dtypes_map(
        SignalWeightsStorage
    )


@pytest.mark.parametrize(("_node_cls", "storage_cls"), PORTFOLIO_NODE_STORAGE)
def test_portfolio_storage_classes_are_registered_metatables(_node_cls, storage_cls) -> None:
    assert storage_cls in set(markets_sqlalchemy_models())


@pytest.mark.skip(reason="requires platform backend (Stage 5 registration)")
def test_portfolio_storage_initialization_full_flow() -> None:
    """End-to-end source-table provisioning needs storage uids from the backend."""

    storage_initialization.initialize_portfolio_storage_source_tables()
