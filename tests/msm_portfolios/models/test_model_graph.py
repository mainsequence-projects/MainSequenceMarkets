from __future__ import annotations

from msm.models import markets_sqlalchemy_models
from msm.models.indices import IndexTable
from msm_portfolios.models import (
    FundTable,
    PortfolioMetadataTable,
    PortfolioTable,
    RebalanceStrategyMetadataTable,
    SignalMetadataTable,
    portfolio_sqlalchemy_models,
)


def test_portfolio_model_graph_owns_portfolio_tables() -> None:
    model_graph = portfolio_sqlalchemy_models()

    assert PortfolioTable in model_graph
    assert IndexTable in model_graph
    assert PortfolioMetadataTable in model_graph
    assert FundTable in model_graph
    assert SignalMetadataTable in model_graph
    assert RebalanceStrategyMetadataTable in model_graph


def test_core_model_graph_does_not_include_portfolio_tables() -> None:
    core_graph = set(markets_sqlalchemy_models())

    assert PortfolioTable not in core_graph
    assert PortfolioMetadataTable not in core_graph
    assert FundTable not in core_graph
    assert SignalMetadataTable not in core_graph
    assert RebalanceStrategyMetadataTable not in core_graph
