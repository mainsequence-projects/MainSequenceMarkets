"""Convenience DataNode for publishing canonical plain or calculated Index values."""

from __future__ import annotations

from typing import ClassVar

import pandas as pd

from mainsequence.meta_tables import PlatformTimeIndexMetaTable

from msm.data_nodes.indices.storage import (
    require_cadenced_index_values_storage,
)
from msm.data_nodes.indices.timestamped import IndexTimestampedDataNode
from msm.data_nodes.utils.stamped import normalize_stamped_frame, reset_frame_index

_OPTIONAL_VALUE_COLUMNS: tuple[str, ...] = (
    "definition_uid",
    "observation_status",
    "source_as_of",
    "metadata_json",
)


def normalize_index_values_frame(
    frame: pd.DataFrame,
    *,
    storage_table: type[PlatformTimeIndexMetaTable],
    frame_label: str = "Index Values",
) -> pd.DataFrame:
    """Normalize canonical Index values and supply omitted nullable provenance columns."""

    require_cadenced_index_values_storage(storage_table)
    index_names = list(storage_table.__index_names__)
    normalized = reset_frame_index(
        frame.copy(),
        index_names=index_names,
        frame_label=frame_label,
    )
    storage_columns = set(storage_table.__table__.columns.keys())
    for column_name in _OPTIONAL_VALUE_COLUMNS:
        if column_name in storage_columns and column_name not in normalized:
            normalized[column_name] = None
    return normalize_stamped_frame(
        normalized,
        storage_table=storage_table,
        frame_label=frame_label,
    )


class IndexValuesDataNode(IndexTimestampedDataNode):
    """Publish canonical Index values without requiring a calculation definition."""

    frame_label: ClassVar[str] = "Index Values"

    @classmethod
    def _required_storage_table(cls) -> type[PlatformTimeIndexMetaTable]:
        raise NotImplementedError(
            "IndexValuesDataNode requires a cadence-specific storage table; "
            "pass storage_table=configured_index_values_storage(cadence=...) "
            "or override _required_storage_table() in a cadence-specific producer"
        )

    def update(self) -> pd.DataFrame:
        frame = normalize_index_values_frame(
            self.get_frame(),
            storage_table=self.storage_table,
            frame_label=self.frame_label,
        )
        self._published_index_identifiers = index_identifiers_in_frame(frame)
        return frame

    def run_post_update_routines(self, error_on_last_update: bool) -> None:
        if error_on_last_update:
            return
        identifiers = getattr(self, "_published_index_identifiers", ())
        if identifiers:
            from msm.api.indices import Index

            Index.reconcile_dataset_availability(index_identifiers=identifiers)

    @classmethod
    def validate_frame(
        cls,
        frame: pd.DataFrame,
        *,
        storage_table: type[PlatformTimeIndexMetaTable] | None = None,
    ) -> pd.DataFrame:
        return normalize_index_values_frame(
            frame,
            storage_table=storage_table or cls._required_storage_table(),
            frame_label=cls.frame_label,
        )


def index_identifiers_in_frame(frame: pd.DataFrame) -> tuple[str, ...]:
    if frame.empty:
        return ()
    values = (
        frame.index.get_level_values("index_identifier")
        if "index_identifier" in frame.index.names
        else frame["index_identifier"]
    )
    return tuple(sorted({str(item) for item in values}))


__all__ = [
    "IndexValuesDataNode",
    "index_identifiers_in_frame",
    "normalize_index_values_frame",
]
