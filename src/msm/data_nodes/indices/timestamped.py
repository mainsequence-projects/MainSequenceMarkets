from __future__ import annotations

from typing import ClassVar

from msm.data_nodes.utils.stamped import (
    StampedDataNode,
    StampedDataNodeConfiguration,
    StampedFrameMixin,
)
from msm.settings import INDEX_IDENTIFIER_DIMENSION


class IndexDataNodeConfiguration(StampedDataNodeConfiguration):
    """Configuration for timestamped index DataNodes.

    Storage-first: the column schema, index names, and the canonical
    ``Index.unique_identifier`` foreign key live on the ``storage_table``
    (an ``IndexFixingsStorage``-style ``PlatformTimeIndexMetaTable`` class),
    not on this configuration.
    """

    reference_dimension: ClassVar[str] = INDEX_IDENTIFIER_DIMENSION
    frame_label: ClassVar[str] = "Index DataNode"


class IndexTimestampedFrameMixin(StampedFrameMixin):
    """Shared frame/config behavior for timestamped index DataNodes."""

    configuration_class: ClassVar[type[IndexDataNodeConfiguration]] = IndexDataNodeConfiguration
    frame_label: ClassVar[str] = "Index DataNode"


class IndexTimestampedDataNode(IndexTimestampedFrameMixin, StampedDataNode):
    """Base index-indexed DataNode for timestamped facts keyed by index_identifier."""


__all__ = [
    "IndexDataNodeConfiguration",
    "IndexTimestampedDataNode",
    "IndexTimestampedFrameMixin",
]
