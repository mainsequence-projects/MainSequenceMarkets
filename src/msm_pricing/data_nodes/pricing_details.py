from __future__ import annotations

from pydantic import Field

from mainsequence.tdag.data_nodes import RecordDefinition
from msm.data_nodes.assets import (
    AssetDataNodeConfiguration,
    AssetTimestampedDataNode,
    asset_time_index_record,
    asset_unique_identifier_record,
)
from msm.settings import markets_data_node_identifier


def asset_pricing_detail_records() -> list[RecordDefinition]:
    return [
        asset_time_index_record(),
        asset_unique_identifier_record(),
        RecordDefinition(
            column_name="instrument_dump",
            dtype="jsonb",
            label="Instrument Dump",
            description="Provider-specific pricing instrument payload.",
        ),
    ]


class AssetPricingDetailConfiguration(AssetDataNodeConfiguration):
    """Configuration for the canonical AssetPricingDetail DataNode."""

    records: list[RecordDefinition] = Field(
        default_factory=asset_pricing_detail_records,
        description="Output schema for the AssetPricingDetail DataNode.",
    )


class AssetPricingDetail(AssetTimestampedDataNode):
    """Timestamped provider pricing metadata keyed by asset unique_identifier."""

    __data_node_identifier__ = "asset_pricing_details"
    configuration_class = AssetPricingDetailConfiguration

    @classmethod
    def _default_identifier(cls) -> str:
        return markets_data_node_identifier(cls.__data_node_identifier__)

    @classmethod
    def _default_description(cls) -> str:
        return "Timestamped asset pricing metadata keyed by time_index and unique_identifier."


__all__ = [
    "AssetPricingDetail",
    "AssetPricingDetailConfiguration",
    "asset_pricing_detail_records",
]
