from __future__ import annotations

from .account_groups import (
    AccountGroupTable,
    AccountModelPortfolioTable,
)
from .accounts import (
    AccountTable,
    AccountTargetPositionAssignmentTable,
)
from .asset_categories import (
    AssetCategoryMembershipTable,
    AssetCategoryTable,
)
from .asset_master_lists import AssetMasterListTable
from .assets import AssetTable
from .calendars import CalendarTable
from .execution import (
    ExecutionErrorTable,
    OrderManagerTable,
    OrderStatusEventTable,
    OrderTable,
    OrderTargetQuantityTable,
    TradeTable,
)
from .funds import FundTable
from .instruments import InstrumentsConfigurationTable
from .portfolios import (
    PortfolioAssetDetailTable,
    PortfolioMetadataTable,
    PortfolioTable,
)
from .provider_details import OpenFigiDetailsTable
from .rebalancing import RebalanceStrategyMetadataTable
from .signals import SignalMetadataTable


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
    "AccountGroupTable",
    "AccountModelPortfolioTable",
    "AccountTable",
    "AccountTargetPositionAssignmentTable",
    "AssetCategoryMembershipTable",
    "AssetCategoryTable",
    "AssetMasterListTable",
    "AssetTable",
    "CalendarTable",
    "ExecutionErrorTable",
    "FundTable",
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
