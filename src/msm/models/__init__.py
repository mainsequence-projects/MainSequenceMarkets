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
    BondAssetDetailsTable,
    CurrencySpotAssetDetailsTable,
    OpenFigiAssetDetailsTable,
)
from .calendars import CalendarTable
from .derivatives import FutureAssetDetailsTable
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
from .indices import IndexTable, IndexTypeTable
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
        IndexTypeTable,
        IndexTable,
        IssuerTable,
        CurrencySpotAssetDetailsTable,
        BondAssetDetailsTable,
        FutureAssetDetailsTable,
        CalendarTable,
        AccountModelPortfolioTable,
        AccountGroupTable,
        AccountTable,
        PortfolioTable,
        AssetCategoryTable,
        SignalMetadataTable,
        RebalanceStrategyMetadataTable,
        PortfolioMetadataTable,
        AssetCategoryMembershipTable,
        OpenFigiAssetDetailsTable,
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
    "BondAssetDetailsTable",
    "CalendarTable",
    "CurrencySpotAssetDetailsTable",
    "ExecutionErrorTable",
    "FundTable",
    "FutureAssetDetailsTable",
    "IndexTable",
    "IndexTypeTable",
    "IssuerTable",
    "OpenFigiAssetDetailsTable",
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
