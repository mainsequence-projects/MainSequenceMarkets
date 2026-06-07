from __future__ import annotations

from .accounts import (
    AccountGroupTable,
    AccountHoldingsSetTable,
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
from .calendars import (
    CalendarDateTable,
    CalendarEventTable,
    CalendarSessionTable,
    CalendarTable,
)
from .derivatives import FutureAssetDetailsTable
from .execution import OrderManagerTable
from .issuers import IssuerTable
from .indices import IndexTable, IndexTypeTable


def markets_sqlalchemy_models() -> list[type]:
    """Return markets SQLAlchemy models in MetaTable dependency order.

    Includes the ADR 0017 DataNode output storage MetaTables after their FK
    target domain MetaTables, so the SDK migration provider registers DataNode
    storage in dependency order alongside the domain tables.
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
        CalendarDateTable,
        CalendarSessionTable,
        CalendarEventTable,
        AccountModelPortfolioTable,
        AccountGroupTable,
        AccountTable,
        AccountHoldingsSetTable,
        AssetCategoryTable,
        AssetCategoryMembershipTable,
        OpenFigiAssetDetailsTable,
        AccountTargetPortfolioTable,
        PositionSetTable,
        OrderManagerTable,
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
        OrderEventsStorage,
        OrdersStorage,
        TradesStorage,
    )

    return [
        AssetSnapshotsStorage,
        AccountHoldingsStorage,
        OrdersStorage,
        OrderEventsStorage,
        TradesStorage,
    ]


__all__ = [
    "AccountGroupTable",
    "AccountHoldingsSetTable",
    "AccountModelPortfolioTable",
    "AccountTable",
    "AccountTargetPortfolioTable",
    "AssetCategoryMembershipTable",
    "AssetCategoryTable",
    "AssetTable",
    "AssetTypeTable",
    "BondAssetDetailsTable",
    "CalendarDateTable",
    "CalendarEventTable",
    "CalendarSessionTable",
    "CalendarTable",
    "CurrencySpotAssetDetailsTable",
    "FutureAssetDetailsTable",
    "IndexTable",
    "IndexTypeTable",
    "IssuerTable",
    "OpenFigiAssetDetailsTable",
    "OrderManagerTable",
    "PositionSetTable",
    "markets_sqlalchemy_models",
]
