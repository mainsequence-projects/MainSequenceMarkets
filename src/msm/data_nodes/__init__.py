from __future__ import annotations

from importlib import import_module
from typing import Any

_EXPORTS = {
    "AccountHoldings": ".accounts",
    "AssetDataNodeConfiguration": ".assets",
    "AssetIndexedDataNode": ".assets",
    "AssetIndexedDataNodeConfiguration": ".assets",
    "AssetSnapshot": ".assets",
    "AssetSnapshotConfiguration": ".assets",
    "AssetSnapshotInput": ".assets",
    "AssetTimestampedDataNode": ".assets",
    "AssetTimestampedFrameMixin": ".assets",
    "ExecutionDataNode": ".execution",
    "ExecutionDataNodeConfiguration": ".execution",
    "HoldingsDataNode": ".accounts",
    "HoldingsDataNodeConfiguration": ".accounts",
    "IndexDataNodeConfiguration": ".indices",
    "DerivedIndexDataNode": ".indices",
    "DerivedIndexDataNodeConfiguration": ".indices",
    "DerivedIndexResolvedLegsDataNode": ".indices",
    "DerivedIndexSourceBinding": ".indices",
    "IndexResolvedLegsStorage": ".indices",
    "IndexTimestampedDataNode": ".indices",
    "IndexTimestampedFrameMixin": ".indices",
    "IndexValuesDataNode": ".indices",
    "IndexValuesStorage": ".indices",
    "configured_index_values_storage": ".indices",
    "index_values_storage_identity_components": ".indices",
    "index_values_storage_table_name": ".indices",
    "normalize_index_values_frame": ".indices",
    "OrderEvents": ".execution",
    "Orders": ".execution",
    "StampedDataNode": ".utils",
    "StampedDataNodeConfiguration": ".utils",
    "StampedFrameMixin": ".utils",
    "TargetPositions": ".accounts",
    "TargetPositionsDataNodeConfiguration": ".accounts",
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
