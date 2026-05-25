from __future__ import annotations

from .account_groups import AccountGroup, AccountModelPortfolio
from .accounts import Account, AccountTargetPositionAssignment
from .asset_categories import AssetCategory, AssetCategoryMembership
from .asset_master_lists import AssetMasterList
from .assets import Asset
from .calendars import Calendar
from .funds import Fund
from .execution import (
    ExecutionError,
    Order,
    OrderManager,
    OrderStatusEvent,
    OrderTargetQuantity,
    Trade,
)
from .instruments import InstrumentsConfiguration
from .portfolios import Portfolio, PortfolioAssetDetail, PortfolioMetadata
from .provider_details import OpenFigiDetails
from .rebalancing import RebalanceStrategyMetadata
from .signals import SignalMetadata


def markets_sqlalchemy_models() -> list[type]:
    """Return markets SQLAlchemy models in MetaTable dependency order."""

    return [
        Asset,
        AssetMasterList,
        Calendar,
        AccountModelPortfolio,
        AccountGroup,
        Account,
        Portfolio,
        AssetCategory,
        SignalMetadata,
        RebalanceStrategyMetadata,
        PortfolioMetadata,
        InstrumentsConfiguration,
        AssetCategoryMembership,
        OpenFigiDetails,
        PortfolioAssetDetail,
        AccountTargetPositionAssignment,
        Fund,
        OrderManager,
        OrderTargetQuantity,
        Order,
        OrderStatusEvent,
        Trade,
        ExecutionError,
    ]


__all__ = [
    "Account",
    "AccountGroup",
    "AccountModelPortfolio",
    "AccountTargetPositionAssignment",
    "Asset",
    "AssetCategory",
    "AssetCategoryMembership",
    "AssetMasterList",
    "Calendar",
    "ExecutionError",
    "Fund",
    "InstrumentsConfiguration",
    "OpenFigiDetails",
    "Order",
    "OrderManager",
    "OrderStatusEvent",
    "OrderTargetQuantity",
    "Portfolio",
    "PortfolioAssetDetail",
    "PortfolioMetadata",
    "RebalanceStrategyMetadata",
    "SignalMetadata",
    "Trade",
    "markets_sqlalchemy_models",
]
