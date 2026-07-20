from __future__ import annotations

from .accounts import (
    AccountGroupTable,
    AccountHoldingsSetTable,
    AccountAllocationModelTable,
    AccountTable,
    AccountTargetAllocationTable,
    PositionSetTable,
    VirtualFundHoldingsSetTable,
    VirtualFundTable,
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
from .index_dataset_availability import IndexDatasetAvailabilityTable
from .index_calculations import (
    IndexCalculationDefinitionTable,
    IndexCalculationLegTable,
)
from .portfolios import PortfolioGroupMembershipTable, PortfolioGroupTable, PortfolioTable
from .portfolios import SignalMetadataTable


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
        IndexDatasetAvailabilityTable,
        IndexCalculationDefinitionTable,
        IndexCalculationLegTable,
        IssuerTable,
        CurrencySpotAssetDetailsTable,
        BondAssetDetailsTable,
        FutureAssetDetailsTable,
        CalendarTable,
        CalendarDateTable,
        CalendarSessionTable,
        CalendarEventTable,
        SignalMetadataTable,
        PortfolioTable,
        PortfolioGroupTable,
        PortfolioGroupMembershipTable,
        AccountAllocationModelTable,
        AccountGroupTable,
        AccountTable,
        AccountHoldingsSetTable,
        VirtualFundTable,
        VirtualFundHoldingsSetTable,
        AssetCategoryTable,
        AssetCategoryMembershipTable,
        OpenFigiAssetDetailsTable,
        AccountTargetAllocationTable,
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

    from msm.data_nodes.accounts.storage import AccountHoldingsStorage, TargetPositionsStorage
    from msm.data_nodes.accounts.virtual_funds.storage import VirtualFundHoldingsStorage
    from msm.data_nodes.assets.storage import AssetSnapshotsStorage
    from msm.data_nodes.execution.storage import (
        OrderEventsStorage,
        OrdersStorage,
        TradesStorage,
    )
    from msm.data_nodes.indices.storage import IndexResolvedLegsStorage, IndexValuesStorage

    return [
        AssetSnapshotsStorage,
        IndexValuesStorage,
        IndexResolvedLegsStorage,
        AccountHoldingsStorage,
        VirtualFundHoldingsStorage,
        TargetPositionsStorage,
        OrdersStorage,
        OrderEventsStorage,
        TradesStorage,
    ]


__all__ = [
    "AccountGroupTable",
    "AccountHoldingsSetTable",
    "AccountAllocationModelTable",
    "AccountTable",
    "AccountTargetAllocationTable",
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
    "IndexDatasetAvailabilityTable",
    "IndexCalculationDefinitionTable",
    "IndexCalculationLegTable",
    "IssuerTable",
    "OpenFigiAssetDetailsTable",
    "OrderManagerTable",
    "PositionSetTable",
    "PortfolioGroupMembershipTable",
    "PortfolioGroupTable",
    "PortfolioTable",
    "SignalMetadataTable",
    "VirtualFundHoldingsSetTable",
    "VirtualFundTable",
    "markets_sqlalchemy_models",
]
