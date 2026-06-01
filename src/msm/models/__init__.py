from __future__ import annotations

from .accounts import (
    AccountGroupTable,
    AccountModelPortfolioTable,
    AccountTable,
    AccountTargetPortfolioTable,
    PositionSetTable,
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
from .issuers import IssuerTable
from .indices import IndexTable, IndexTypeTable


def markets_sqlalchemy_models() -> list[type]:
    """Return markets SQLAlchemy models in MetaTable dependency order.

    Includes the ADR 0017 DataNode output storage MetaTables after their FK
    target domain MetaTables, so the catalog bootstrap registers DataNode storage
    in dependency order alongside the domain tables.
    """

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
        AssetCategoryTable,
        AssetCategoryMembershipTable,
        OpenFigiAssetDetailsTable,
        AccountTargetPortfolioTable,
        PositionSetTable,
        OrderManagerTable,
        OrderTargetQuantityTable,
        OrderTable,
        OrderStatusEventTable,
        TradeTable,
        ExecutionErrorTable,
        *_markets_data_node_storage_models(),
    ]


def _markets_data_node_storage_models() -> list[type]:
    """Return ADR 0017 DataNode output storage MetaTables in FK order.

    Imported lazily so importing ``msm.models`` never eagerly pulls in the
    DataNode packages (avoids an import cycle: the storage modules import
    ``msm.models`` domain tables for their FK targets).
    """

    from msm.data_nodes.storage import (
        AccountHoldingsStorage,
        AssetSnapshotsStorage,
        ExecutionErrorsStorage,
        OrderEventsStorage,
        OrdersStorage,
        TargetPositionsStorage,
        TradesStorage,
    )

    return [
        AssetSnapshotsStorage,
        AccountHoldingsStorage,
        TargetPositionsStorage,
        OrdersStorage,
        OrderEventsStorage,
        TradesStorage,
        ExecutionErrorsStorage,
    ]


__all__ = [
    "AccountGroupTable",
    "AccountModelPortfolioTable",
    "AccountTable",
    "AccountTargetPortfolioTable",
    "AssetCategoryMembershipTable",
    "AssetCategoryTable",
    "AssetTable",
    "AssetTypeTable",
    "BondAssetDetailsTable",
    "CalendarTable",
    "CurrencySpotAssetDetailsTable",
    "ExecutionErrorTable",
    "FutureAssetDetailsTable",
    "IndexTable",
    "IndexTypeTable",
    "IssuerTable",
    "OpenFigiAssetDetailsTable",
    "OrderManagerTable",
    "OrderStatusEventTable",
    "OrderTable",
    "OrderTargetQuantityTable",
    "PositionSetTable",
    "TradeTable",
    "markets_sqlalchemy_models",
]
