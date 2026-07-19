from __future__ import annotations

from msm.data_nodes.indices.timestamped import (
    IndexDataNodeConfiguration,
    IndexTimestampedDataNode,
    IndexTimestampedFrameMixin,
)
from msm.data_nodes.indices.storage import (
    IndexResolvedLegsStorage,
    IndexValuesStorage,
    configured_index_values_storage,
    index_values_storage_identity_components,
    index_values_storage_table_name,
)
from msm.data_nodes.indices.values import IndexValuesDataNode, normalize_index_values_frame

__all__ = [
    "IndexDataNodeConfiguration",
    "IndexTimestampedDataNode",
    "IndexTimestampedFrameMixin",
    "IndexResolvedLegsStorage",
    "IndexValuesDataNode",
    "IndexValuesStorage",
    "configured_index_values_storage",
    "index_values_storage_identity_components",
    "index_values_storage_table_name",
    "normalize_index_values_frame",
    "DerivedIndexDataNode",
    "DerivedIndexDataNodeConfiguration",
    "DerivedIndexResolvedLegsDataNode",
]


def __getattr__(name: str):
    if name in {
        "DerivedIndexDataNode",
        "DerivedIndexDataNodeConfiguration",
        "DerivedIndexResolvedLegsDataNode",
    }:
        from msm.data_nodes.indices import derived

        return getattr(derived, name)
    raise AttributeError(name)
