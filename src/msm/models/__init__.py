from __future__ import annotations

from .account_groups import (
    AccountGroupTable,
    AccountModelPortfolioTable,
)
from .accounts import (
    AccountTable,
    AccountTargetPositionAssignmentTable,
)
from .assets import (
    AssetCategoryMembershipTable,
    AssetCategoryTable,
    AssetTable,
    AssetTypeTable,
    BondDetailsTable,
    CurrencySpotTable,
    OpenFigiDetailsTable,
)
from .calendars import CalendarTable
from .derivatives import FutureDetailsTable
from .execution import (
    ExecutionErrorTable,
    OrderManagerTable,
    OrderStatusEventTable,
    OrderTable,
    OrderTargetQuantityTable,
    TradeTable,
)
from .funds import FundTable
from .issuers import IssuerTable
from .indices import IndexTable
from .instruments import InstrumentsConfigurationTable
from .portfolios import (
    PortfolioAssetDetailTable,
    PortfolioMetadataTable,
    PortfolioTable,
)
from .rebalancing import RebalanceStrategyMetadataTable
from .signals import SignalMetadataTable


def markets_sqlalchemy_models() -> list[type]:
    """Return markets SQLAlchemy models in MetaTable dependency order."""

    return [
        AssetTypeTable,
        AssetTable,
        IndexTable,
        IssuerTable,
        CurrencySpotTable,
        BondDetailsTable,
        FutureDetailsTable,
        CalendarTable,
        AccountModelPortfolioTable,
        AccountGroupTable,
        AccountTable,
        PortfolioTable,
        AssetCategoryTable,
        SignalMetadataTable,
        RebalanceStrategyMetadataTable,
        PortfolioMetadataTable,
        InstrumentsConfigurationTable,
        AssetCategoryMembershipTable,
        OpenFigiDetailsTable,
        PortfolioAssetDetailTable,
        AccountTargetPositionAssignmentTable,
        FundTable,
        OrderManagerTable,
        OrderTargetQuantityTable,
        OrderTable,
        OrderStatusEventTable,
        TradeTable,
        ExecutionErrorTable,
    ]


__all__ = [
    "AccountGroupTable",
    "AccountModelPortfolioTable",
    "AccountTable",
    "AccountTargetPositionAssignmentTable",
    "AssetCategoryMembershipTable",
    "AssetCategoryTable",
    "AssetTable",
    "AssetTypeTable",
    "BondDetailsTable",
    "CalendarTable",
    "CurrencySpotTable",
    "ExecutionErrorTable",
    "FundTable",
    "FutureDetailsTable",
    "IndexTable",
    "IssuerTable",
    "InstrumentsConfigurationTable",
    "OpenFigiDetailsTable",
    "OrderManagerTable",
    "OrderStatusEventTable",
    "OrderTable",
    "OrderTargetQuantityTable",
    "PortfolioAssetDetailTable",
    "PortfolioMetadataTable",
    "PortfolioTable",
    "RebalanceStrategyMetadataTable",
    "SignalMetadataTable",
    "TradeTable",
    "markets_sqlalchemy_models",
]
