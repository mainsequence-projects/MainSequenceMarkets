from __future__ import annotations

from typing import ClassVar

from msm.data_nodes.utils.stamped import (
    STAMPED_DATA_NODE_BOOTSTRAP_TIME_INDEX,
    STAMPED_DATA_NODE_BOOTSTRAP_UNIQUE_IDENTIFIER,
    StampedDataNode,
    StampedDataNodeConfiguration,
    StampedFrameMixin,
)
from msm.settings import INDEX_UNIQUE_IDENTIFIER_DIMENSION

INDEX_DATA_NODE_BOOTSTRAP_UNIQUE_IDENTIFIER = STAMPED_DATA_NODE_BOOTSTRAP_UNIQUE_IDENTIFIER
INDEX_DATA_NODE_BOOTSTRAP_TIME_INDEX = STAMPED_DATA_NODE_BOOTSTRAP_TIME_INDEX


class IndexDataNodeConfiguration(StampedDataNodeConfiguration):
    """Configuration for timestamped index DataNodes.

    Storage-first: the column schema, index names, and the canonical
    ``Index.unique_identifier`` foreign key live on the ``storage_table``
    (an ``IndexFixingsStorage``-style ``PlatformTimeIndexMetaData`` class),
    not on this configuration.
    """

    reference_dimension: ClassVar[str] = INDEX_UNIQUE_IDENTIFIER_DIMENSION
    frame_label: ClassVar[str] = "Index DataNode"


class IndexTimestampedFrameMixin(StampedFrameMixin):
    """Shared frame/config behavior for timestamped index DataNodes."""

    configuration_class: ClassVar[type[IndexDataNodeConfiguration]] = IndexDataNodeConfiguration
    frame_label: ClassVar[str] = "Index DataNode"


class IndexTimestampedDataNode(IndexTimestampedFrameMixin, StampedDataNode):
    """Base index-indexed DataNode for timestamped facts keyed by unique_identifier."""


__all__ = [
    "INDEX_DATA_NODE_BOOTSTRAP_TIME_INDEX",
    "INDEX_DATA_NODE_BOOTSTRAP_UNIQUE_IDENTIFIER",
    "IndexDataNodeConfiguration",
    "IndexTimestampedDataNode",
    "IndexTimestampedFrameMixin",
]
