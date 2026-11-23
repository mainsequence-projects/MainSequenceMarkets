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
    AssetCalendarTable,
    AssetCategoryMembershipTable,
    AssetCategoryTable,
    AssetTable,
    AssetTypeTable,
    BondAssetDetailsTable,
    CurrencySpotAssetDetailsTable,
    OpenFigiAssetDetailsTable,
)
from .calendars import (
    CalendarExceptionTable,
    CalendarSessionRuleTable,
    CalendarTable,
)
from .derivatives import FutureAssetDetailsTable
from .execution import OrderManagerTable, OrderTable
from .issuers import IssuerTable
from .indices import IndexTable, IndexTypeTable
from .index_dataset_availability import IndexDatasetAvailabilityTable
from .index_formulas import (
    IndexFormulaDefinitionTable,
    IndexFormulaInputTable,
)
from .portfolios import PortfolioGroupMembershipTable, PortfolioGroupTable, PortfolioTable
from .portfolios import SignalMetadataTable


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
        CalendarSessionRuleTable,
        CalendarExceptionTable,
        AssetCalendarTable,
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
        OrderTable,
        *_markets_time_index_storage_models(),
    ]


def _markets_time_index_storage_models() -> list[type]:
    """Return ADR 0017 TimeIndexTableUpdater output storage MetaTables in FK order.

    Imported lazily so importing ``msm.models`` never eagerly pulls in the
    TimeIndexTableUpdater packages (avoids an import cycle: the storage modules import
    ``msm.models`` domain tables for their FK targets).
    """

    from msm.time_index.accounts.storage import AccountHoldingsStorage, TargetPositionsStorage
    from msm.time_index.accounts.virtual_funds.storage import (
        AccountAllocationLinesStorage,
        VirtualFundHoldingsStorage,
    )
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
        AccountAllocationLinesStorage,
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
    "AssetCalendarTable",
    "AssetCategoryMembershipTable",
    "AssetCategoryTable",
    "AssetTable",
    "AssetTypeTable",
    "BondAssetDetailsTable",
    "CalendarExceptionTable",
    "CalendarSessionRuleTable",
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
    "OrderTable",
    "PositionSetTable",
    "PortfolioGroupMembershipTable",
    "PortfolioGroupTable",
    "PortfolioTable",
    "SignalMetadataTable",
    "VirtualFundHoldingsSetTable",
    "VirtualFundTable",
    "markets_sqlalchemy_models",
]
