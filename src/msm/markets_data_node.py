from __future__ import annotations

from msm.asset_indexed_data_node import (
    ASSET_UNIQUE_IDENTIFIER_DIMENSION,
    AssetIndexedDataNode,
    AssetIndexedDataNodeConfiguration,
    MarketAssetScopeItem,
    asset_indexed_foreign_keys,
    asset_unique_identifier_foreign_key,
)

MarketDataNodeConfiguration = AssetIndexedDataNodeConfiguration
MarketDataNode = AssetIndexedDataNode

__all__ = [
    "ASSET_UNIQUE_IDENTIFIER_DIMENSION",
    "MarketAssetScopeItem",
    "MarketDataNode",
    "MarketDataNodeConfiguration",
    "asset_indexed_foreign_keys",
    "asset_unique_identifier_foreign_key",
]
