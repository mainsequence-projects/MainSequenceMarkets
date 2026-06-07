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
    PortfolioTable,
)

from .portfolios import PortfolioMetadataTable
from .rebalancing import RebalanceStrategyMetadataTable
from .signals import SignalMetadataTable
from .virtual_funds import VirtualFundHoldingsSetTable, VirtualFundTable


def portfolio_sqlalchemy_models() -> list[type]:
    from msm.data_nodes.accounts.storage import TargetPositionsStorage
    from msm_portfolios.data_nodes.portfolios.storage import (
        PortfoliosStorage,
        PortfolioWeightsStorage,
    )
    from msm_portfolios.data_nodes.prices.storage import ExternalPricesStorage
    from msm_portfolios.data_nodes.signals.storage import SignalWeightsStorage
    from msm_portfolios.data_nodes.virtual_funds.storage import (
        VirtualFundHoldingsStorage,
    )

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
    "AccountAllocationModelTable",
    "AccountTable",
    "AccountTargetAllocationTable",
    "AssetTable",
    "AssetTypeTable",
    "CalendarTable",
    "IndexTable",
    "IndexTypeTable",
    "PositionSetTable",
    "PortfolioMetadataTable",
    "RebalanceStrategyMetadataTable",
    "SignalMetadataTable",
    "VirtualFundHoldingsSetTable",
    "VirtualFundTable",
    "portfolio_sqlalchemy_models",
]
