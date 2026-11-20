"""An asset's pricing detail resolves through its storage first (``msm_pricing``).

Split from ``tests/msm/assets/test_asset_snapshots.py``.
"""

from __future__ import annotations

from msm_pricing.time_index import AssetPricingDetail, AssetPricingDetailConfiguration
from msm_pricing.time_index.pricing_details.storage import AssetPricingDetailsStorage


def test_asset_pricing_detail_resolves_storage_first_surface() -> None:
    assert AssetPricingDetail._required_output_table() is AssetPricingDetailsStorage
    assert issubclass(
        AssetPricingDetail.configuration_class,
        AssetPricingDetailConfiguration,
    )
    assert [column.name for column in AssetPricingDetailsStorage.__table__.columns] == [
        "time_index",
        "asset_identifier",
        "instrument_dump",
        "instrument_type",
        "serialization_format",
        "pricing_package_version",
        "source",
        "metadata",
    ]
