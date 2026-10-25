from __future__ import annotations

from typing import ClassVar

from msm.time_index.utils.stamped import (
    StampedUpdater,
    StampedUpdaterConfiguration,
    StampedFrameMixin,
)
from msm.settings import INDEX_IDENTIFIER_DIMENSION


class IndexUpdaterConfiguration(StampedUpdaterConfiguration):
    """Configuration for timestamped index updaters.

    Storage-first: the column schema, index names, and the canonical
    ``Index.unique_identifier`` foreign key live on the ``output_table``
    (an ``IndexFixingsStorage``-style ``PlatformTimeIndexMetaTable`` class),
    not on this configuration.
    """

    reference_dimension: ClassVar[str] = INDEX_IDENTIFIER_DIMENSION
    frame_label: ClassVar[str] = "Index TimeIndexTableUpdater"


class IndexTimestampedFrameMixin(StampedFrameMixin):
    """Shared frame/config behavior for timestamped index updaters."""

    configuration_class: ClassVar[type[IndexUpdaterConfiguration]] = IndexUpdaterConfiguration
    frame_label: ClassVar[str] = "Index TimeIndexTableUpdater"


class IndexTimestampedUpdater(IndexTimestampedFrameMixin, StampedUpdater):
    """Base index-indexed TimeIndexTableUpdater for timestamped facts keyed by index_identifier."""


__all__ = [
    "IndexUpdaterConfiguration",
    "IndexTimestampedUpdater",
    "IndexTimestampedFrameMixin",
]
