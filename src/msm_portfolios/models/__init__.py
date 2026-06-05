from __future__ import annotations

from msm.models import (
    AccountGroupTable,
    AccountHoldingsSetTable,
    AccountTable,
    AssetTable,
    AssetTypeTable,
    CalendarTable,
    IndexTable,
)

from .portfolios import (
    PortfolioMetadataTable,
    PortfolioTable,
)
from .rebalancing import RebalanceStrategyMetadataTable
from .signals import SignalMetadataTable
from .virtual_funds import VirtualFundHoldingsSetTable, VirtualFundTable


def portfolio_sqlalchemy_models() -> list[type]:
    from msm_portfolios.data_nodes.storage import (
        InterpolatedPricesStorage,
        PortfoliosStorage,
        PortfolioWeightsStorage,
        SignalWeightsStorage,
        VirtualFundHoldingsStorage,
    )

    return [
        AssetTypeTable,
        AssetTable,
        IndexTable,
        AccountGroupTable,
        AccountTable,
        AccountHoldingsSetTable,
        CalendarTable,
        PortfolioTable,
        SignalMetadataTable,
        RebalanceStrategyMetadataTable,
        PortfolioMetadataTable,
        VirtualFundTable,
        VirtualFundHoldingsSetTable,
        PortfolioWeightsStorage,
        SignalWeightsStorage,
        PortfoliosStorage,
        InterpolatedPricesStorage,
        VirtualFundHoldingsStorage,
    ]


__all__ = [
    "AccountGroupTable",
    "AccountHoldingsSetTable",
    "AccountTable",
    "AssetTable",
    "AssetTypeTable",
    "CalendarTable",
    "IndexTable",
    "PortfolioMetadataTable",
    "PortfolioTable",
    "RebalanceStrategyMetadataTable",
    "SignalMetadataTable",
    "VirtualFundHoldingsSetTable",
    "VirtualFundTable",
    "portfolio_sqlalchemy_models",
]
