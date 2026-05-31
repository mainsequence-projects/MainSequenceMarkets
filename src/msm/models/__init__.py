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
        FundHoldingsStorage,
        OrderEventsStorage,
        OrdersStorage,
        TargetPositionsStorage,
        TradesStorage,
    )
    from msm.portfolios.data_nodes.storage import (
        ExternalPricesStorage,
        InterpolatedPricesStorage,
        PortfoliosStorage,
        PortfolioWeightsStorage,
        SignalWeightsStorage,
    )

    return [
        AssetSnapshotsStorage,
        AccountHoldingsStorage,
        FundHoldingsStorage,
        TargetPositionsStorage,
        OrdersStorage,
        OrderEventsStorage,
        TradesStorage,
        ExecutionErrorsStorage,
        PortfolioWeightsStorage,
        SignalWeightsStorage,
        PortfoliosStorage,
        InterpolatedPricesStorage,
        ExternalPricesStorage,
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
