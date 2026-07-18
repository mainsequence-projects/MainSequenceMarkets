from __future__ import annotations

from msm.data_nodes.indices.timestamped import (
    IndexDataNodeConfiguration,
    IndexTimestampedDataNode,
    IndexTimestampedFrameMixin,
)
from msm.data_nodes.indices.storage import IndexResolvedLegsStorage, IndexValuesStorage

__all__ = [
    "IndexDataNodeConfiguration",
    "IndexTimestampedDataNode",
    "IndexTimestampedFrameMixin",
    "IndexResolvedLegsStorage",
    "IndexValuesStorage",
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
