from __future__ import annotations

from msm.models import (
    AccountGroupTable,
    AccountHoldingsSetTable,
    AccountAllocationModelTable,
    AccountTable,
    AccountTargetAllocationTable,
    AssetTable,
    AssetTypeTable,
    CalendarTable,
    IndexTable,
    IndexTypeTable,
    PositionSetTable,
    PortfolioGroupMembershipTable,
    PortfolioGroupTable,
    PortfolioTable,
    VirtualFundTable,
)

from .portfolios import PortfolioMetadataTable
from .rebalancing import RebalanceStrategyMetadataTable
from .signals import SignalMetadataTable


def portfolio_sqlalchemy_models() -> list[type]:
    from msm.data_nodes.accounts.storage import TargetPositionsStorage
    from msm_portfolios.data_nodes.portfolios.storage import (
        PortfoliosStorage,
        PortfolioWeightsStorage,
    )
    from msm_portfolios.data_nodes.prices.storage import ExternalPricesStorage
    from msm_portfolios.data_nodes.signals.storage import SignalWeightsStorage

    return [
        AssetTypeTable,
        AssetTable,
        IndexTypeTable,
        IndexTable,
        AccountGroupTable,
        AccountAllocationModelTable,
        AccountTable,
        AccountTargetAllocationTable,
        AccountHoldingsSetTable,
        PositionSetTable,
        CalendarTable,
        SignalMetadataTable,
        PortfolioTable,
        PortfolioGroupTable,
        PortfolioGroupMembershipTable,
        VirtualFundTable,
        RebalanceStrategyMetadataTable,
        PortfolioMetadataTable,
        PortfolioWeightsStorage,
        SignalWeightsStorage,
        PortfoliosStorage,
        ExternalPricesStorage,
        TargetPositionsStorage,
    ]


__all__ = [
    "AccountGroupTable",
    "AccountHoldingsSetTable",
    "AccountAllocationModelTable",
    "AccountTable",
    "AccountTargetAllocationTable",
    "AssetTable",
    "AssetTypeTable",
    "CalendarTable",
    "IndexTable",
    "IndexTypeTable",
    "PositionSetTable",
    "PortfolioGroupMembershipTable",
    "PortfolioGroupTable",
    "PortfolioMetadataTable",
    "VirtualFundTable",
    "RebalanceStrategyMetadataTable",
    "SignalMetadataTable",
    "portfolio_sqlalchemy_models",
]
