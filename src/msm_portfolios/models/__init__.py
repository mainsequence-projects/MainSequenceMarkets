from __future__ import annotations

from msm.models import IndexTable

from .portfolios import (
    PortfolioMetadataTable,
    PortfolioTable,
)
from .rebalancing import RebalanceStrategyMetadataTable
from .signals import SignalMetadataTable
from .virtual_funds import FundTable


def portfolio_sqlalchemy_models() -> list[type]:
    from msm_portfolios.data_nodes.storage import (
        FundHoldingsStorage,
        InterpolatedPricesStorage,
        PortfoliosStorage,
        PortfolioWeightsStorage,
        SignalWeightsStorage,
    )

    return [
        IndexTable,
        PortfolioTable,
        SignalMetadataTable,
        RebalanceStrategyMetadataTable,
        PortfolioMetadataTable,
        FundTable,
        PortfolioWeightsStorage,
        SignalWeightsStorage,
        PortfoliosStorage,
        InterpolatedPricesStorage,
        FundHoldingsStorage,
    ]


__all__ = [
    "FundTable",
    "IndexTable",
    "PortfolioMetadataTable",
    "PortfolioTable",
    "RebalanceStrategyMetadataTable",
    "SignalMetadataTable",
    "portfolio_sqlalchemy_models",
]
