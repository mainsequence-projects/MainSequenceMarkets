from __future__ import annotations

from msm.time_index.assets import (
    AssetUpdaterConfiguration,
    AssetTimestampedUpdater,
)

from .storage import AssetPricingDetailsStorage


class AssetPricingDetailConfiguration(AssetUpdaterConfiguration):
    """Configuration for the canonical AssetPricingDetail TimeIndexTableUpdater."""


class AssetPricingDetail(AssetTimestampedUpdater):
    """Timestamped provider pricing metadata keyed by asset_identifier."""

    configuration_class = AssetPricingDetailConfiguration

    @classmethod
    def _required_output_table(cls) -> type[AssetPricingDetailsStorage]:
        return AssetPricingDetailsStorage


__all__ = [
    "AssetPricingDetail",
    "AssetPricingDetailConfiguration",
]
