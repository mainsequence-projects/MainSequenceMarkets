from __future__ import annotations

from importlib import import_module
from typing import Any

_EXPORTS = {
    "ACCOUNT_HISTORICAL_HOLDINGS_TABLE_CONTRACT": ".utils",
    "ASSET_DATA_NODE_BOOTSTRAP_TIME_INDEX": ".assets",
    "ASSET_DATA_NODE_BOOTSTRAP_UNIQUE_IDENTIFIER": ".assets",
    "ACCOUNT_HOLDINGS_INDEX_NAMES": ".accounts",
    "ACCOUNT_HOLDINGS_RECORDS": ".accounts",
    "ACCOUNT_HOLDINGS_TIME_INDEX_NAME": ".accounts",
    "AccountHoldings": ".accounts",
    "AssetDataNodeConfiguration": ".assets",
    "AssetIndexedDataNode": ".assets",
    "AssetIndexedDataNodeConfiguration": ".assets",
    "AssetSnapshot": ".assets",
    "AssetSnapshotConfiguration": ".assets",
    "AssetSnapshotInput": ".assets",
    "AssetTimestampedDataNode": ".assets",
    "AssetTimestampedFrameMixin": ".assets",
    "DataNodeTableContract": ".utils",
    "EXECUTION_ERRORS_COLUMN_DTYPES_MAP": ".execution",
    "EXECUTION_ERRORS_INDEX_NAMES": ".execution",
    "EXECUTION_ERRORS_TIME_INDEX_NAME": ".execution",
    "ExecutionDataNode": ".execution",
    "ExecutionDataNodeConfiguration": ".execution",
    "ExecutionErrors": ".execution",
    "FUND_HISTORICAL_HOLDINGS_TABLE_CONTRACT": ".utils",
    "HoldingsDataNode": ".accounts",
    "HoldingsDataNodeConfiguration": ".accounts",
    "INDEX_DATA_NODE_BOOTSTRAP_TIME_INDEX": ".indices",
    "INDEX_DATA_NODE_BOOTSTRAP_UNIQUE_IDENTIFIER": ".indices",
    "IndexDataNodeConfiguration": ".indices",
    "IndexTimestampedDataNode": ".indices",
    "IndexTimestampedFrameMixin": ".indices",
    "ORDER_EVENTS_COLUMN_DTYPES_MAP": ".execution",
    "ORDER_EVENTS_INDEX_NAMES": ".execution",
    "ORDER_EVENTS_TIME_INDEX_NAME": ".execution",
    "ORDERS_COLUMN_DTYPES_MAP": ".execution",
    "ORDERS_INDEX_NAMES": ".execution",
    "ORDERS_TIME_INDEX_NAME": ".execution",
    "OrderEvents": ".execution",
    "Orders": ".execution",
    "POSITION_EXPOSURE_TABLE_CONTRACT": ".utils",
    "StampedDataNode": ".utils",
    "StampedDataNodeConfiguration": ".utils",
    "StampedFrameMixin": ".utils",
    "TRADES_COLUMN_DTYPES_MAP": ".execution",
    "TRADES_INDEX_NAMES": ".execution",
    "TRADES_TIME_INDEX_NAME": ".execution",
    "Trades": ".execution",
    "VIRTUAL_FUND_HOLDINGS_INDEX_NAMES": ".accounts",
    "VIRTUAL_FUND_HOLDINGS_RECORDS": ".accounts",
    "VIRTUAL_FUND_HOLDINGS_TIME_INDEX_NAME": ".accounts",
    "VirtualFundHoldings": ".accounts",
    "asset_indexed_foreign_keys": ".assets",
    "asset_unique_identifier_foreign_key": ".assets",
    "index_indexed_foreign_keys": ".indices",
    "index_time_index_record": ".indices",
    "index_unique_identifier_foreign_key": ".indices",
    "index_unique_identifier_record": ".indices",
    "source_table_initialization_kwargs": ".utils",
}


def __getattr__(name: str) -> Any:
    if name not in _EXPORTS:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    module = import_module(_EXPORTS[name], __name__)
    value = getattr(module, name)
    globals()[name] = value
    return value


def __dir__() -> list[str]:
    return sorted(set(globals()) | set(__all__))


__all__ = sorted(_EXPORTS)
