from __future__ import annotations

from importlib import import_module
from typing import Any

_EXPORTS = {
    "AccountHoldings": ".accounts",
    "AssetUpdaterConfiguration": ".assets",
    "AssetIndexedUpdater": ".assets",
    "AssetIndexedUpdaterConfiguration": ".assets",
    "AssetSnapshot": ".assets",
    "AssetSnapshotConfiguration": ".assets",
    "AssetSnapshotInput": ".assets",
    "AssetTimestampedUpdater": ".assets",
    "AssetTimestampedFrameMixin": ".assets",
    "ExecutionUpdater": ".execution",
    "ExecutionUpdaterConfiguration": ".execution",
    "HoldingsUpdater": ".accounts",
    "HoldingsUpdaterConfiguration": ".accounts",
    "IndexUpdaterConfiguration": ".indices",
    "FormulaIndexUpdater": ".indices",
    "FormulaIndexUpdaterConfiguration": ".indices",
    "IndexTimestampedUpdater": ".indices",
    "IndexTimestampedFrameMixin": ".indices",
    "IndexValuesUpdater": ".indices",
    "IndexValuesStorage": ".indices",
    "configured_index_values_storage": ".indices",
    "index_values_storage_identity_components": ".indices",
    "index_values_output_table_name": ".indices",
    "normalize_index_values_frame": ".indices",
    "OrderEvents": ".execution",
    "Orders": ".execution",
    "StampedUpdater": ".utils",
    "StampedUpdaterConfiguration": ".utils",
    "StampedFrameMixin": ".utils",
    "TargetPositions": ".accounts",
    "TargetPositionsConfiguration": ".accounts",
    "Trades": ".execution",
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
