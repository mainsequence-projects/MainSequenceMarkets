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
from .index_formulas import (
    IndexFormulaDefinitionTable,
    IndexFormulaInputTable,
)
from .portfolios import PortfolioGroupMembershipTable, PortfolioGroupTable, PortfolioTable
from .portfolios import SignalMetadataTable
from .portfolio_dataset_availability import PortfolioDatasetAvailabilityTable


def markets_sqlalchemy_models() -> list[type]:
    """Return markets SQLAlchemy models in MetaTable dependency order.

    Includes the ADR 0017 TimeIndexTableUpdater output storage MetaTables after their FK
    target domain MetaTables, so the SDK migration provider registers TimeIndexTableUpdater
    storage in dependency order alongside the domain tables.
    """

    return [
        AssetTypeTable,
        AssetTable,
        IndexTypeTable,
        IndexTable,
        IndexDatasetAvailabilityTable,
        IndexFormulaDefinitionTable,
        IndexFormulaInputTable,
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
        PortfolioDatasetAvailabilityTable,
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
        *_markets_time_index_storage_models(),
    ]


def _markets_time_index_storage_models() -> list[type]:
    """Return ADR 0017 TimeIndexTableUpdater output storage MetaTables in FK order.

    Imported lazily so importing ``msm.models`` never eagerly pulls in the
    TimeIndexTableUpdater packages (avoids an import cycle: the storage modules import
    ``msm.models`` domain tables for their FK targets).
    """

    from msm.time_index.accounts.storage import AccountHoldingsStorage, TargetPositionsStorage
    from msm.time_index.accounts.virtual_funds.storage import VirtualFundHoldingsStorage
    from msm.time_index.assets.storage import AssetSnapshotsStorage
    from msm.time_index.execution.storage import (
        OrderEventsStorage,
        OrdersStorage,
        TradesStorage,
    )
    from msm.time_index.indices.storage import IndexValuesStorage

    return [
        AssetSnapshotsStorage,
        IndexValuesStorage,
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
    "IndexFormulaDefinitionTable",
    "IndexFormulaInputTable",
    "IssuerTable",
    "OpenFigiAssetDetailsTable",
    "OrderManagerTable",
    "PositionSetTable",
    "PortfolioDatasetAvailabilityTable",
    "PortfolioGroupMembershipTable",
    "PortfolioGroupTable",
    "PortfolioTable",
    "SignalMetadataTable",
    "VirtualFundHoldingsSetTable",
    "VirtualFundTable",
    "markets_sqlalchemy_models",
]
