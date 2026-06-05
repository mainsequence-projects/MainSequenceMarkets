from __future__ import annotations

from msm.models import (
    AccountGroupTable,
    AccountHoldingsSetTable,
    AccountModelPortfolioTable,
    AccountTable,
    AccountTargetPortfolioTable,
    AssetTable,
    AssetTypeTable,
    CalendarTable,
    IndexTable,
    IndexTypeTable,
    PositionSetTable,
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
        ExternalPricesStorage,
        PortfoliosStorage,
        PortfolioWeightsStorage,
        SignalWeightsStorage,
        TargetPositionsStorage,
        VirtualFundHoldingsStorage,
    )

    return [
        AssetTypeTable,
        AssetTable,
        IndexTypeTable,
        IndexTable,
        AccountGroupTable,
        AccountModelPortfolioTable,
        AccountTable,
        AccountTargetPortfolioTable,
        AccountHoldingsSetTable,
        PositionSetTable,
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
        ExternalPricesStorage,
        TargetPositionsStorage,
        VirtualFundHoldingsStorage,
    ]


__all__ = [
    "AccountGroupTable",
    "AccountHoldingsSetTable",
    "AccountModelPortfolioTable",
    "AccountTable",
    "AccountTargetPortfolioTable",
    "AssetTable",
    "AssetTypeTable",
    "CalendarTable",
    "IndexTable",
    "IndexTypeTable",
    "PositionSetTable",
    "PortfolioMetadataTable",
    "PortfolioTable",
    "RebalanceStrategyMetadataTable",
    "SignalMetadataTable",
    "VirtualFundHoldingsSetTable",
    "VirtualFundTable",
    "portfolio_sqlalchemy_models",
]
