from __future__ import annotations

from typing import ClassVar

import pandas as pd

from mainsequence.meta_tables import (
    DataNode,
    DataNodeConfiguration,
    PlatformTimeIndexMetaTable,
)
from msm.data_nodes.utils.namespaces import wrap_default_markets_hash_namespace
from msm.data_nodes.utils.storage_metadata import (
    storage_data_node_description,
    storage_data_node_identifier,
)
from msm.data_nodes.utils.time import normalize_datetime64_ns_utc

StorageTable = type[PlatformTimeIndexMetaTable]


class StampedDataNodeConfiguration(DataNodeConfiguration):
    """Configuration for timestamped reference-keyed markets DataNodes.

    Storage-first: the column schema, index names, and time index live on the
    ``storage_table`` (a ``PlatformTimeIndexMetaTable`` class), not on the
    configuration. This configuration only carries update-scoped build fields;
    the identifier and descriptive metadata live on the ``storage_table``.
    """

    reference_dimension: ClassVar[str] = "unique_identifier"
    frame_label: ClassVar[str] = "Stamped DataNode"


class StampedFrameMixin:
    """Shared frame/config behavior for timestamped markets DataNodes."""

    configuration_class: ClassVar[type[StampedDataNodeConfiguration]] = StampedDataNodeConfiguration
    frame_label: ClassVar[str] = "Stamped DataNode"

    def __init__(
        self,
        config: StampedDataNodeConfiguration | None = None,
        storage_table: StorageTable | None = None,
        *,
        hash_namespace: str | None = None,
    ):
        super().__init__(
            config=config or self.default_config(),
            storage_table=storage_table or self._required_storage_table(),
            hash_namespace=hash_namespace,
        )

    @classmethod
    def default_config(cls) -> StampedDataNodeConfiguration:
        return cls.configuration_class()

    @classmethod
    def _required_storage_table(cls) -> StorageTable:
        """Return the storage class that owns this node's schema contract."""

        raise NotImplementedError(f"{cls.__name__} must define _required_storage_table().")

    @classmethod
    def _default_identifier(cls) -> str:
        return storage_data_node_identifier(cls._required_storage_table())

    @classmethod
    def _default_description(cls) -> str:
        return storage_data_node_description(cls._required_storage_table())

    def set_frame(self, frame: pd.DataFrame):
        self._stamped_data_frame = frame
        return self

    def get_frame(self) -> pd.DataFrame:
        frame = getattr(self, "_stamped_data_frame", None)
        if frame is None:
            raise ValueError(
                f"{self.__class__.__name__} requires a real stamped frame. "
                "Call set_frame() before update()."
            )
        return frame

    def update(self) -> pd.DataFrame:
        return normalize_stamped_frame(
            self.get_frame(),
            storage_table=self.storage_table,
            frame_label=self.frame_label,
        )

    @classmethod
    def validate_frame(
        cls,
        frame: pd.DataFrame,
        *,
        storage_table: StorageTable | None = None,
    ) -> pd.DataFrame:
        storage_table = storage_table or cls._required_storage_table()
        return normalize_stamped_frame(
            frame,
            storage_table=storage_table,
            frame_label=cls.frame_label,
        )


class StampedDataNode(StampedFrameMixin, DataNode):
    """Base DataNode for timestamped facts keyed by a reference unique identifier."""

    def __init_subclass__(cls, **kwargs):
        super().__init_subclass__(**kwargs)
        cls.__init__ = wrap_default_markets_hash_namespace(cls, cls.__init__)

    def dependencies(self) -> dict:
        return {}


def normalize_stamped_frame(
    frame: pd.DataFrame,
    *,
    storage_table: StorageTable,
    frame_label: str | None = None,
) -> pd.DataFrame:
    """Normalize a frame to the storage_table contract (columns, index, dtypes).

    Schema is sourced from the ``storage_table`` class — its ``__table__``
    columns, ``__index_names__``, and ``__time_index_name__`` — rather than from
    a configuration ``records`` list. Returns a frame indexed by the storage
    index with the time index as ``datetime64[ns, UTC]`` and identity dimensions
    cast to ``string``.
    """

    index_names = list(storage_table.__index_names__)
    time_index_name = storage_table.__time_index_name__
    column_names = [column.name for column in storage_table.__table__.columns]
    label = frame_label or storage_table.__name__

    normalized = reset_frame_index(frame.copy(), index_names=index_names, frame_label=label)
    missing = sorted(set(column_names).difference(normalized.columns))
    if missing:
        raise ValueError(f"{label} frame is missing columns: {missing!r}.")

    normalized[time_index_name] = normalize_datetime64_ns_utc(normalized[time_index_name])
    for dimension in index_names[1:]:
        normalized[dimension] = normalized[dimension].astype("string")
    normalized = normalized[column_names]
    normalized = normalized.set_index(index_names)

    if normalized.index.has_duplicates:
        raise ValueError(f"{label} frame contains duplicate rows for {index_names!r}.")
    return normalized.sort_index()


def reset_frame_index(
    frame: pd.DataFrame,
    *,
    index_names: list[str],
    frame_label: str = "Stamped DataNode",
) -> pd.DataFrame:
    missing_index_names = [
        index_name
        for index_name in index_names
        if index_name not in frame.columns and index_name not in (frame.index.names or [])
    ]
    if missing_index_names:
        raise ValueError(f"{frame_label} frame is missing index columns: {missing_index_names!r}.")
    has_required_index = any(name in index_names for name in frame.index.names)
    return frame.reset_index() if has_required_index else frame


__all__ = [
    "StampedDataNode",
    "StampedDataNodeConfiguration",
    "StampedFrameMixin",
    "normalize_stamped_frame",
    "reset_frame_index",
]
