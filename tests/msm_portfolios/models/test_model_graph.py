from __future__ import annotations

from msm.models import (
    VirtualFundHoldingsSetTable,
    VirtualFundTable,
    markets_sqlalchemy_models,
)
from msm.models.accounts import AccountTargetAllocationTable, PositionSetTable
from msm.models import PortfolioTable
from msm.data_nodes.accounts.storage import TargetPositionsStorage
from msm.models.indices import IndexTable, IndexTypeTable
from msm.models.calendars import CalendarTable
from msm_portfolios.models import (
    PortfolioMetadataTable,
    RebalanceStrategyMetadataTable,
    SignalMetadataTable,
    portfolio_sqlalchemy_models,
)


def test_portfolio_model_graph_includes_core_portfolio_dependencies() -> None:
    model_graph = portfolio_sqlalchemy_models()

    assert PortfolioTable in model_graph
    assert CalendarTable in model_graph
    assert IndexTypeTable in model_graph
    assert IndexTable in model_graph
    assert AccountTargetAllocationTable in model_graph
    assert PositionSetTable in model_graph
    assert PortfolioMetadataTable in model_graph
    assert TargetPositionsStorage in model_graph
    assert VirtualFundTable in model_graph
    assert VirtualFundHoldingsSetTable not in model_graph
    assert SignalMetadataTable in model_graph
    assert RebalanceStrategyMetadataTable in model_graph


def test_core_model_graph_owns_portfolio_identity_and_account_allocation() -> None:
    core_graph = set(markets_sqlalchemy_models())

    assert PortfolioTable in core_graph
    assert TargetPositionsStorage in core_graph
    assert PortfolioMetadataTable not in core_graph
    assert VirtualFundTable in core_graph
    assert VirtualFundHoldingsSetTable in core_graph
    assert SignalMetadataTable in core_graph
    assert RebalanceStrategyMetadataTable not in core_graph
