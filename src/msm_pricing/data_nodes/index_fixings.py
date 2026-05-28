from __future__ import annotations

import datetime as dt
from collections.abc import Mapping
from typing import ClassVar, Protocol

import pandas as pd
from pydantic import Field, field_validator

from mainsequence.client.models_tdag import ColumnMetaData, TableMetaData
from mainsequence.client.utils import DataFrequency
from mainsequence.tdag.data_nodes import DataNodeMetaData, RecordDefinition
from msm.data_nodes.indices import (
    IndexDataNodeConfiguration,
    IndexTimestampedDataNode,
    index_time_index_record,
    index_unique_identifier_record,
)
from msm.settings import (
    INDEX_UNIQUE_IDENTIFIER_DIMENSION,
    markets_data_node_identifier,
)
from msm_pricing.settings import PRICING_CONCEPT_INTEREST_RATE_INDEX_FIXINGS

INDEX_FIXINGS_NODE_DESCRIPTION = (
    "Timestamped index fixings used by msm_pricing to hydrate QuantLib indexes. "
    "Each row represents one observation timestamp and one Index unique_identifier, "
    "with the rate column storing the observed fixing as a decimal value. The "
    "dataset is an index-stamped fact table, not an asset-indexed table, and each "
    "identity links to the canonical Index MetaTable. Pricing uses this data to "
    "load historical SOFR, TIIE, IBOR, overnight, and other reference-rate fixings "
    "when valuing floating-rate bonds, swaps, and related instruments."
)


class IndexFixingBuilder(Protocol):
    """Runtime builder for one index fixing identity."""

    def __call__(
        self,
        *,
        update_statistics,
        unique_identifier: str,
    ) -> pd.DataFrame: ...


def index_fixing_rate_record() -> RecordDefinition:
    return RecordDefinition(
        column_name="rate",
        dtype="float64",
        label="Fixing Rate",
        description="Observed index fixing rate normalized to decimal form.",
    )


def index_fixing_records() -> list[RecordDefinition]:
    return [
        index_time_index_record(),
        index_unique_identifier_record(),
        index_fixing_rate_record(),
    ]


def _supported_frequency_ids() -> set[str]:
    return {frequency.value for frequency in DataFrequency}


class IndexFixingConfiguration(IndexDataNodeConfiguration):
    """Configuration for index fixing observations consumed by pricing."""

    node_metadata: DataNodeMetaData = Field(
        default_factory=lambda: DataNodeMetaData(
            identifier=markets_data_node_identifier(PRICING_CONCEPT_INTEREST_RATE_INDEX_FIXINGS),
            description=INDEX_FIXINGS_NODE_DESCRIPTION,
        ),
        description="Discovery metadata for the IndexFixings DataNode.",
    )
    records: list[RecordDefinition] = Field(
        default_factory=index_fixing_records,
        description="Output schema for index fixing observations.",
    )
    frequency: str = Field(
        default=DataFrequency.one_d.value,
        description=(
            "Hashable observation frequency for the fixing dataset. Different "
            "frequencies represent different DataNode identities."
        ),
    )
    index_unique_identifiers: list[str] | None = Field(
        default=None,
        description=(
            "Optional updater scope of Index unique identifiers. When omitted, "
            "the node publishes every supplied fixing builder."
        ),
        json_schema_extra={"update_only": True},
    )

    @field_validator("frequency")
    @classmethod
    def _validate_frequency(cls, value: str) -> str:
        if value not in _supported_frequency_ids():
            supported = ", ".join(sorted(_supported_frequency_ids()))
            raise ValueError(
                f"Unsupported index fixing frequency {value!r}. Use one of: {supported}."
            )
        return value

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

    __data_node_identifier__ = PRICING_CONCEPT_INTEREST_RATE_INDEX_FIXINGS
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
    def _default_description(cls) -> str:
        return INDEX_FIXINGS_NODE_DESCRIPTION

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
        for unique_identifier in self.index_unique_identifiers():
            frame = self.build_fixing_frame(
                update_statistics=self.update_statistics,
                unique_identifier=unique_identifier,
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
        return self.validate_frame(normalized, config=self.config)

    def build_fixing_frame(
        self,
        *,
        update_statistics,
        unique_identifier: str,
    ) -> pd.DataFrame:
        try:
            builder = self.fixing_builders[unique_identifier]
        except KeyError as exc:
            raise NotImplementedError(
                "FixingRatesNode requires fixing_builders keyed by IndexTable "
                "unique_identifier or a subclass that implements build_fixing_frame(...)."
            ) from exc
        return builder(
            update_statistics=update_statistics,
            unique_identifier=unique_identifier,
        )

    @staticmethod
    def _normalize_builder_frame(frame: pd.DataFrame) -> pd.DataFrame:
        normalized = frame.copy()
        if normalized.index.name == "index_uid":
            normalized.index.name = INDEX_UNIQUE_IDENTIFIER_DIMENSION
        if isinstance(normalized.index, pd.MultiIndex):
            normalized.index = normalized.index.set_names(
                [
                    INDEX_UNIQUE_IDENTIFIER_DIMENSION if name == "index_uid" else name
                    for name in normalized.index.names
                ]
            )

        normalized = normalized.reset_index()
        if (
            "index_uid" in normalized.columns
            and INDEX_UNIQUE_IDENTIFIER_DIMENSION not in normalized.columns
        ):
            normalized = normalized.rename(columns={"index_uid": INDEX_UNIQUE_IDENTIFIER_DIMENSION})
        return normalized

    def get_table_metadata(self) -> TableMetaData:
        return TableMetaData(
            identifier=self.config.node_metadata.identifier,
            data_frequency_id=DataFrequency(self.config.frequency),
            description=self.config.node_metadata.description,
        )

    def get_column_metadata(self) -> list[ColumnMetaData]:
        return [
            ColumnMetaData(
                column_name="rate",
                dtype="float64",
                label="Fixing Rate",
                description="Observed index fixing rate normalized to decimal form.",
            )
        ]


__all__ = [
    "FixingRatesNode",
    "INDEX_FIXINGS_NODE_DESCRIPTION",
    "IndexFixingConfiguration",
    "IndexFixingBuilder",
    "index_fixing_rate_record",
    "index_fixing_records",
]
