from __future__ import annotations

from collections.abc import Sequence
from typing import ClassVar

from pydantic import Field, model_validator

from mainsequence.tdag.data_nodes import RecordDefinition, SourceTableForeignKey
from msm.data_nodes.utils.stamped import (
    STAMPED_DATA_NODE_BOOTSTRAP_TIME_INDEX,
    STAMPED_DATA_NODE_BOOTSTRAP_UNIQUE_IDENTIFIER,
    StampedDataNode,
    StampedDataNodeConfiguration,
    StampedFrameMixin,
)
from msm.models import IndexTable
from msm.settings import INDEX_UNIQUE_IDENTIFIER_DIMENSION

INDEX_DATA_NODE_BOOTSTRAP_UNIQUE_IDENTIFIER = STAMPED_DATA_NODE_BOOTSTRAP_UNIQUE_IDENTIFIER
INDEX_DATA_NODE_BOOTSTRAP_TIME_INDEX = STAMPED_DATA_NODE_BOOTSTRAP_TIME_INDEX


def index_time_index_record() -> RecordDefinition:
    return RecordDefinition(
        column_name="time_index",
        dtype="datetime64[ns, UTC]",
        label="Time Index",
        description="UTC timestamp for the index fact row.",
    )


def index_unique_identifier_record() -> RecordDefinition:
    return RecordDefinition(
        column_name=INDEX_UNIQUE_IDENTIFIER_DIMENSION,
        dtype="string",
        label="Unique Identifier",
        description="Index unique identifier from the Index MetaTable.",
    )


def index_unique_identifier_foreign_key(
    source_column: RecordDefinition | str = INDEX_UNIQUE_IDENTIFIER_DIMENSION,
) -> SourceTableForeignKey:
    """Return the canonical DataNode source-table FK to ``Index.unique_identifier``."""

    return SourceTableForeignKey(
        target=IndexTable,
        source_columns=[source_column],
        target_columns=[IndexTable.unique_identifier],
        on_delete="restrict",
    )


def index_indexed_foreign_keys(
    *,
    records: Sequence[RecordDefinition] | None,
    foreign_keys: Sequence[SourceTableForeignKey] | None = None,
    source_column: RecordDefinition | str = INDEX_UNIQUE_IDENTIFIER_DIMENSION,
) -> list[SourceTableForeignKey]:
    """Return explicit foreign keys plus the canonical Index FK when missing."""

    source_column_name = (
        source_column.column_name if isinstance(source_column, RecordDefinition) else source_column
    )
    record_names = _record_column_names(records)
    if source_column_name not in record_names:
        raise ValueError(
            "Index-indexed DataNodes require a records entry for "
            f"{source_column_name!r} before adding the canonical Index foreign key."
        )

    resolved_foreign_keys = list(foreign_keys or [])
    if not any(
        _is_canonical_index_foreign_key(foreign_key) for foreign_key in resolved_foreign_keys
    ):
        resolved_foreign_keys.insert(
            0,
            index_unique_identifier_foreign_key(source_column=source_column),
        )
    return resolved_foreign_keys


def _record_column_names(records: Sequence[RecordDefinition] | None) -> list[str]:
    if not records:
        raise ValueError(
            "Index-indexed DataNode foreign keys require DataNodeConfiguration.records."
        )

    names = [record.column_name for record in records]
    duplicate_names = sorted({name for name in names if names.count(name) > 1})
    if duplicate_names:
        raise ValueError(f"Duplicate DataNode record column names: {duplicate_names!r}.")
    return names


def _is_canonical_index_foreign_key(foreign_key: SourceTableForeignKey) -> bool:
    if foreign_key.source_column_names() != [INDEX_UNIQUE_IDENTIFIER_DIMENSION]:
        return False
    if foreign_key.target_column_names() != [INDEX_UNIQUE_IDENTIFIER_DIMENSION]:
        return False
    if foreign_key.on_delete.lower() != "restrict":
        return False

    target = foreign_key.target
    target_table = getattr(getattr(target, "__table__", target), "name", None)
    return target is IndexTable or target_table == IndexTable.__table__.name


class IndexDataNodeConfiguration(StampedDataNodeConfiguration):
    """Configuration for timestamped index DataNodes."""

    reference_dimension: ClassVar[str] = INDEX_UNIQUE_IDENTIFIER_DIMENSION
    frame_label: ClassVar[str] = "Index DataNode"

    index_names: list[str] = Field(
        default_factory=lambda: ["time_index", INDEX_UNIQUE_IDENTIFIER_DIMENSION],
        description="Canonical DataFrame index columns for the index DataNode.",
    )

    @model_validator(mode="after")
    def _ensure_index_foreign_key(self) -> IndexDataNodeConfiguration:
        self.foreign_keys = index_indexed_foreign_keys(
            records=self.records,
            foreign_keys=self.foreign_keys,
        )
        return self


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
    "index_indexed_foreign_keys",
    "index_time_index_record",
    "index_unique_identifier_foreign_key",
    "index_unique_identifier_record",
]
