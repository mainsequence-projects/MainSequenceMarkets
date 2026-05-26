from __future__ import annotations

from .account_groups import (
    AccountGroup,
    AccountGroupTable,
    AccountModelPortfolio,
    AccountModelPortfolioTable,
)
from .accounts import (
    Account,
    AccountTable,
    AccountTargetPositionAssignment,
    AccountTargetPositionAssignmentTable,
)
from .asset_categories import (
    AssetCategory,
    AssetCategoryMembership,
    AssetCategoryMembershipTable,
    AssetCategoryTable,
)
from .asset_master_lists import AssetMasterList, AssetMasterListTable
from .assets import Asset, AssetTable
from .calendars import Calendar, CalendarTable
from .funds import Fund
from .execution import (
    ExecutionError,
    ExecutionErrorTable,
    Order,
    OrderManager,
    OrderManagerTable,
    OrderStatusEvent,
    OrderStatusEventTable,
    OrderTable,
    OrderTargetQuantity,
    OrderTargetQuantityTable,
    Trade,
    TradeTable,
)
from .funds import FundTable
from .instruments import InstrumentsConfiguration, InstrumentsConfigurationTable
from .portfolios import (
    Portfolio,
    PortfolioAssetDetail,
    PortfolioAssetDetailTable,
    PortfolioMetadata,
    PortfolioMetadataTable,
    PortfolioTable,
)
from .provider_details import OpenFigiDetails, OpenFigiDetailsTable
from .rebalancing import RebalanceStrategyMetadata, RebalanceStrategyMetadataTable
from .signals import SignalMetadata, SignalMetadataTable


def markets_sqlalchemy_models() -> list[type]:
    """Return markets SQLAlchemy models in MetaTable dependency order."""

    return [
        AssetTable,
        AssetMasterListTable,
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
    "Account",
    "AccountGroup",
    "AccountGroupTable",
    "AccountModelPortfolio",
    "AccountModelPortfolioTable",
    "AccountTable",
    "AccountTargetPositionAssignment",
    "AccountTargetPositionAssignmentTable",
    "Asset",
    "AssetCategory",
    "AssetCategoryMembership",
    "AssetCategoryMembershipTable",
    "AssetCategoryTable",
    "AssetMasterList",
    "AssetMasterListTable",
    "AssetTable",
    "Calendar",
    "CalendarTable",
    "ExecutionError",
    "ExecutionErrorTable",
    "Fund",
    "FundTable",
    "InstrumentsConfiguration",
    "InstrumentsConfigurationTable",
    "OpenFigiDetails",
    "OpenFigiDetailsTable",
    "Order",
    "OrderManager",
    "OrderManagerTable",
    "OrderStatusEvent",
    "OrderStatusEventTable",
    "OrderTable",
    "OrderTargetQuantity",
    "OrderTargetQuantityTable",
    "Portfolio",
    "PortfolioAssetDetail",
    "PortfolioAssetDetailTable",
    "PortfolioMetadata",
    "PortfolioMetadataTable",
    "PortfolioTable",
    "RebalanceStrategyMetadata",
    "RebalanceStrategyMetadataTable",
    "SignalMetadata",
    "SignalMetadataTable",
    "Trade",
    "TradeTable",
    "markets_sqlalchemy_models",
]
