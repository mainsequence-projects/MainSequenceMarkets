from __future__ import annotations

from importlib import import_module
from typing import Any

_EXPORTS = {
    "ACCOUNT_HISTORICAL_HOLDINGS_TABLE_CONTRACT": ".contracts",
    "ASSET_DATA_NODE_BOOTSTRAP_TIME_INDEX": ".assets",
    "ASSET_DATA_NODE_BOOTSTRAP_UNIQUE_IDENTIFIER": ".assets",
    "ASSET_DATA_NODE_INDEX_NAMES": ".assets",
    "ASSET_DATA_NODE_TIME_INDEX_NAME": ".assets",
    "ASSET_PRICING_DETAIL_COLUMN_DESCRIPTIONS": ".assets",
    "ASSET_PRICING_DETAIL_COLUMN_DTYPES_MAP": ".assets",
    "ASSET_PRICING_DETAIL_COLUMN_LABELS": ".assets",
    "ASSET_SNAPSHOT_COLUMN_DESCRIPTIONS": ".assets",
    "ASSET_SNAPSHOT_COLUMN_DTYPES_MAP": ".assets",
    "ASSET_SNAPSHOT_COLUMN_LABELS": ".assets",
    "AssetDataNodeConfiguration": ".assets",
    "AssetPricingDetail": ".assets",
    "AssetSnapshot": ".assets",
    "AssetTimestampedDataNode": ".assets",
    "AssetTimestampedFrameMixin": ".assets",
    "FUND_HISTORICAL_HOLDINGS_TABLE_CONTRACT": ".contracts",
    "MarketDataNodeTableContract": ".contracts",
    "POSITION_EXPOSURE_TABLE_CONTRACT": ".contracts",
    "source_table_initialization_kwargs": ".contracts",
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
