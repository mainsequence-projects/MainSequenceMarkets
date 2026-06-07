from __future__ import annotations

from msm.data_nodes.assets import (
    AssetDataNodeConfiguration,
    AssetTimestampedDataNode,
)

from .storage import AssetPricingDetailsStorage


class AssetPricingDetailConfiguration(AssetDataNodeConfiguration):
    """Configuration for the canonical AssetPricingDetail DataNode."""


class AssetPricingDetail(AssetTimestampedDataNode):
    """Timestamped provider pricing metadata keyed by asset_identifier."""

    configuration_class = AssetPricingDetailConfiguration

    @classmethod
    def _required_storage_table(cls) -> type[AssetPricingDetailsStorage]:
        return AssetPricingDetailsStorage


__all__ = [
    "AssetPricingDetail",
    "AssetPricingDetailConfiguration",
]
