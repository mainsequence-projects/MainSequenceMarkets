from __future__ import annotations

import datetime as dt
from collections.abc import Mapping
from typing import ClassVar, Protocol

import pandas as pd
from pydantic import Field, field_validator

from msm.data_nodes.indices import (
    IndexDataNodeConfiguration,
    IndexTimestampedDataNode,
)

from .storage import IndexFixingsStorage


class IndexFixingBuilder(Protocol):
    """Runtime builder for one index fixing identity."""

    def __call__(
        self,
        *,
        update_statistics,
        index_identifier: str,
    ) -> pd.DataFrame: ...


class IndexFixingConfiguration(IndexDataNodeConfiguration):
    """Configuration for index fixing observations consumed by pricing."""

    index_unique_identifiers: list[str] | None = Field(
        default=None,
        description=(
            "Optional updater scope of Index unique identifiers. When omitted, "
            "the node publishes every supplied fixing builder."
        ),
    )

    @field_validator("index_unique_identifiers")
    @classmethod
    def _validate_index_unique_identifiers(
        cls,
        value: list[str] | None,
    ) -> list[str] | None:
        if value is None:
            return None

        normalized = [item.strip() for item in value]
        if any(not item for item in normalized):
            raise ValueError("index_unique_identifiers cannot contain empty values.")
        if len(normalized) != len(set(normalized)):
            raise ValueError("index_unique_identifiers cannot contain duplicates.")
        return normalized


class FixingRatesNode(IndexTimestampedDataNode):
    """Pricing helper that publishes index fixings from registered builders."""

    configuration_class: ClassVar[type[IndexFixingConfiguration]] = IndexFixingConfiguration
    OFFSET_START = dt.datetime(1990, 1, 1, tzinfo=dt.UTC)

    def __init__(
        self,
        fixing_config: IndexFixingConfiguration | None = None,
        **kwargs,
    ):
        self.fixing_config = fixing_config or self.default_config()
        self.fixing_builders: dict[str, IndexFixingBuilder] = {}
        super().__init__(config=self.fixing_config, **kwargs)

    @classmethod
    def _required_storage_table(cls) -> type[IndexFixingsStorage]:
        return IndexFixingsStorage

    def set_fixing_builders(
        self,
        fixing_builders: Mapping[str, IndexFixingBuilder],
    ) -> FixingRatesNode:
        self.fixing_builders = dict(fixing_builders)
        return self

    def index_unique_identifiers(self) -> list[str]:
        configured = self.fixing_config.index_unique_identifiers
        if configured is not None:
            return list(configured)
        return sorted(self.fixing_builders)

    def update(self) -> pd.DataFrame:
        frames = []
        for index_identifier in self.index_unique_identifiers():
            frame = self.build_fixing_frame(
                update_statistics=self.update_statistics,
                index_identifier=index_identifier,
            )
            if not frame.empty:
                frames.append(frame)

        if not frames:
            return pd.DataFrame()

        frame = pd.concat(frames, axis=0)
        normalized = self._normalize_builder_frame(frame)
        normalized = normalized.dropna(subset=["rate"])
        if normalized.empty:
            return pd.DataFrame()
        return self.validate_frame(normalized, storage_table=self.storage_table)

    def build_fixing_frame(
        self,
        *,
        update_statistics,
        index_identifier: str,
    ) -> pd.DataFrame:
        try:
            builder = self.fixing_builders[index_identifier]
        except KeyError as exc:
            raise NotImplementedError(
                "FixingRatesNode requires fixing_builders keyed by IndexTable "
                "unique_identifier or a subclass that implements build_fixing_frame(...)."
            ) from exc
        return builder(
            update_statistics=update_statistics,
            index_identifier=index_identifier,
        )

    @staticmethod
    def _normalize_builder_frame(frame: pd.DataFrame) -> pd.DataFrame:
        normalized = frame.copy()
        normalized = normalized.reset_index()
        stale_columns = {"index_uid", "unique_identifier"}.intersection(normalized.columns)
        if stale_columns:
            raise ValueError(
                "Index fixing builder frames must use index_identifier, not "
                f"{sorted(stale_columns)!r}."
            )
        return normalized


__all__ = [
    "FixingRatesNode",
    "IndexFixingConfiguration",
    "IndexFixingBuilder",
]
