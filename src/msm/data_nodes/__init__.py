from __future__ import annotations

from importlib import import_module
from typing import Any

_EXPORTS = {
    "ASSET_DATA_NODE_BOOTSTRAP_TIME_INDEX": ".assets",
    "ASSET_DATA_NODE_BOOTSTRAP_UNIQUE_IDENTIFIER": ".assets",
    "ACCOUNT_HOLDINGS_INDEX_NAMES": ".accounts",
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
    "EXECUTION_ERRORS_INDEX_NAMES": ".execution",
    "EXECUTION_ERRORS_TIME_INDEX_NAME": ".execution",
    "ExecutionDataNode": ".execution",
    "ExecutionDataNodeConfiguration": ".execution",
    "ExecutionErrors": ".execution",
    "HoldingsDataNode": ".accounts",
    "HoldingsDataNodeConfiguration": ".accounts",
    "INDEX_DATA_NODE_BOOTSTRAP_TIME_INDEX": ".indices",
    "INDEX_DATA_NODE_BOOTSTRAP_UNIQUE_IDENTIFIER": ".indices",
    "IndexDataNodeConfiguration": ".indices",
    "IndexTimestampedDataNode": ".indices",
    "IndexTimestampedFrameMixin": ".indices",
    "ORDER_EVENTS_INDEX_NAMES": ".execution",
    "ORDER_EVENTS_TIME_INDEX_NAME": ".execution",
    "ORDERS_INDEX_NAMES": ".execution",
    "ORDERS_TIME_INDEX_NAME": ".execution",
    "OrderEvents": ".execution",
    "Orders": ".execution",
    "StampedDataNode": ".utils",
    "StampedDataNodeConfiguration": ".utils",
    "StampedFrameMixin": ".utils",
    "TRADES_INDEX_NAMES": ".execution",
    "TRADES_TIME_INDEX_NAME": ".execution",
    "Trades": ".execution",
    "VIRTUAL_FUND_HOLDINGS_INDEX_NAMES": ".accounts",
    "VIRTUAL_FUND_HOLDINGS_TIME_INDEX_NAME": ".accounts",
    "VirtualFundHoldings": ".accounts",
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
