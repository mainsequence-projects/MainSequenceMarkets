from __future__ import annotations

import datetime as dt
from collections.abc import Sequence
from typing import ClassVar, Protocol

import pandas as pd
from pydantic import Field, model_validator

from mainsequence.client.models_tdag import ColumnMetaData, TableMetaData
from mainsequence.client.utils import DataFrequency
from mainsequence.tdag import APIDataNode, DataNode
from mainsequence.tdag.data_nodes import (
    DataNodeMetaData,
    RecordDefinition,
    SourceTableForeignKey,
)
from msm.data_nodes.utils.stamped import (
    StampedDataNode,
    StampedDataNodeConfiguration,
)
from msm.settings import markets_data_node_identifier
from msm_pricing.models import CurveTable

from .curve_codec import compress_curve_to_string

CURVE_UNIQUE_IDENTIFIER_DIMENSION = "curve_unique_identifier"

DISCOUNT_CURVES_NODE_DESCRIPTION = (
    "Daily compressed discount curves used by msm_pricing valuation workflows. "
    "Each row represents one valuation timestamp and one curve_unique_identifier "
    "registered in the Curve MetaTable, with the curve column storing the compressed "
    "term-structure payload. The dataset is intended for reconstructing discount "
    "term structures by curve identity when pricing bonds and other fixed-income "
    "instruments. Curve identities resolve to pricing-owned Curve metadata, which "
    "links each curve to its index convention details, interpolation method, "
    "compounding convention, source, and other curve metadata."
)


class DiscountCurveBuilder(Protocol):
    """Runtime builder for one curve identity."""

    def __call__(
        self,
        *,
        update_statistics,
        curve_unique_identifier: str,
        base_node_curve_points: APIDataNode | None,
    ) -> pd.DataFrame: ...


def curve_time_index_record() -> RecordDefinition:
    return RecordDefinition(
        column_name="time_index",
        dtype="datetime64[ns, UTC]",
        label="Time Index",
        description="UTC timestamp for the curve observation row.",
    )


def curve_unique_identifier_record() -> RecordDefinition:
    return RecordDefinition(
        column_name=CURVE_UNIQUE_IDENTIFIER_DIMENSION,
        dtype="string",
        label="Curve Unique Identifier",
        description="Curve unique identifier from the Curve MetaTable.",
    )


def curve_unique_identifier_foreign_key(
    source_column: RecordDefinition | str = CURVE_UNIQUE_IDENTIFIER_DIMENSION,
) -> SourceTableForeignKey:
    """Return the canonical DataNode source-table FK to ``Curve.unique_identifier``."""

    return SourceTableForeignKey(
        target=CurveTable,
        source_columns=[source_column],
        target_columns=[CurveTable.unique_identifier],
        on_delete="restrict",
    )


def curve_indexed_foreign_keys(
    *,
    records: Sequence[RecordDefinition] | None,
    foreign_keys: Sequence[SourceTableForeignKey] | None = None,
    source_column: RecordDefinition | str = CURVE_UNIQUE_IDENTIFIER_DIMENSION,
) -> list[SourceTableForeignKey]:
    """Return explicit foreign keys plus the canonical Curve FK when missing."""

    source_column_name = (
        source_column.column_name if isinstance(source_column, RecordDefinition) else source_column
    )
    record_names = _record_column_names(records)
    if source_column_name not in record_names:
        raise ValueError(
            "Curve DataNodes require a records entry for "
            f"{source_column_name!r} before adding the canonical Curve foreign key."
        )

    resolved_foreign_keys = list(foreign_keys or [])
    if not any(
        _is_canonical_curve_foreign_key(foreign_key) for foreign_key in resolved_foreign_keys
    ):
        resolved_foreign_keys.insert(
            0,
            curve_unique_identifier_foreign_key(source_column=source_column),
        )
    return resolved_foreign_keys


def _record_column_names(records: Sequence[RecordDefinition] | None) -> list[str]:
    if not records:
        raise ValueError("Curve DataNode foreign keys require DataNodeConfiguration.records.")

    names = [record.column_name for record in records]
    duplicate_names = sorted({name for name in names if names.count(name) > 1})
    if duplicate_names:
        raise ValueError(f"Duplicate DataNode record column names: {duplicate_names!r}.")
    return names


def _is_canonical_curve_foreign_key(foreign_key: SourceTableForeignKey) -> bool:
    if foreign_key.source_column_names() != [CURVE_UNIQUE_IDENTIFIER_DIMENSION]:
        return False
    if foreign_key.target_column_names() != ["unique_identifier"]:
        return False
    if foreign_key.on_delete.lower() != "restrict":
        return False

    target = foreign_key.target
    target_table = getattr(getattr(target, "__table__", target), "name", None)
    return target is CurveTable or target_table == CurveTable.__table__.name


def discount_curve_records() -> list[RecordDefinition]:
    return [
        curve_time_index_record(),
        curve_unique_identifier_record(),
        RecordDefinition(
            column_name="curve",
            dtype="str",
            label="Compressed Curve",
            description="Compressed discount-curve points payload.",
        ),
    ]


class CurveDataNodeConfiguration(StampedDataNodeConfiguration):
    """Configuration for timestamped curve DataNodes."""

    reference_dimension: ClassVar[str] = CURVE_UNIQUE_IDENTIFIER_DIMENSION
    frame_label: ClassVar[str] = "Curve DataNode"

    index_names: list[str] = Field(
        default_factory=lambda: ["time_index", CURVE_UNIQUE_IDENTIFIER_DIMENSION],
        description="Canonical DataFrame index columns for the curve DataNode.",
    )

    @model_validator(mode="after")
    def _ensure_curve_foreign_key(self) -> CurveDataNodeConfiguration:
        self.foreign_keys = curve_indexed_foreign_keys(
            records=self.records,
            foreign_keys=self.foreign_keys,
        )
        return self


class CurveTimestampedDataNode(StampedDataNode):
    """Base curve DataNode for timestamped facts keyed by curve unique identifier."""

    configuration_class: ClassVar[type[CurveDataNodeConfiguration]] = (
        CurveDataNodeConfiguration
    )
    frame_label: ClassVar[str] = "Curve DataNode"


class CurveConfig(CurveDataNodeConfiguration):
    """Configuration for the canonical discount-curves DataNode."""

    node_metadata: DataNodeMetaData = Field(
        default_factory=lambda: DataNodeMetaData(
            identifier=markets_data_node_identifier("discount_curves"),
            description=DISCOUNT_CURVES_NODE_DESCRIPTION,
        ),
        description="Discovery metadata for the DiscountCurves DataNode.",
    )
    records: list[RecordDefinition] = Field(
        default_factory=discount_curve_records,
        description="Output schema for the DiscountCurves DataNode.",
    )
    curve_unique_identifier: str = Field(
        ...,
        description=(
            "Curve unique identifier from CurveTable. This is dataset identity, "
            "not a Main Sequence Constant name."
        ),
    )
    curve_points_dependency_node_uid: str | None = Field(
        None,
        title="Dependency curve points",
        description="Optional upstream curve-points DataNode identifier.",
        json_schema_extra={"update_only": True},
    )


class DiscountCurvesNode(CurveTimestampedDataNode):
    """Compressed discount curves keyed by curve unique identifier."""

    __data_node_identifier__ = "discount_curves"
    configuration_class = CurveConfig
    OFFSET_START = dt.datetime(1990, 1, 1, tzinfo=dt.UTC)

    def __init__(
        self,
        curve_config: CurveConfig,
        **kwargs,
    ):
        self.curve_config = curve_config
        self.curve_builder: DiscountCurveBuilder | None = None
        self.base_node_curve_points = None
        if curve_config.curve_points_dependency_node_uid:
            self.base_node_curve_points = APIDataNode.build_from_identifier(
                identifier=curve_config.curve_points_dependency_node_uid
            )
        super().__init__(config=curve_config, **kwargs)

    def dependencies(self) -> dict[str, DataNode | APIDataNode]:
        if self.base_node_curve_points is None:
            return {}
        return {self.curve_config.curve_points_dependency_node_uid: self.base_node_curve_points}

    def set_curve_builder(self, curve_builder: DiscountCurveBuilder) -> DiscountCurvesNode:
        self.curve_builder = curve_builder
        return self

    def update(self) -> pd.DataFrame:
        curve_unique_identifier = self.curve_config.curve_unique_identifier
        frame = self.build_curve_frame(
            update_statistics=self.update_statistics,
            curve_unique_identifier=curve_unique_identifier,
            base_node_curve_points=self.base_node_curve_points,
        )
        if frame.empty:
            return pd.DataFrame()

        normalized = self._normalize_builder_frame(
            frame,
            curve_unique_identifier=curve_unique_identifier,
        )
        normalized["curve"] = normalized["curve"].apply(compress_curve_to_string)
        normalized["time_index"] = pd.to_datetime(normalized["time_index"], utc=True)

        last = self.update_statistics.get_last_update_for_identity(curve_unique_identifier)
        if last is not None:
            normalized = normalized[normalized["time_index"] > pd.Timestamp(last)]
        if normalized.empty:
            return pd.DataFrame()

        return self.validate_frame(normalized, config=self.config)

    def build_curve_frame(
        self,
        *,
        update_statistics,
        curve_unique_identifier: str,
        base_node_curve_points: APIDataNode | None,
    ) -> pd.DataFrame:
        if self.curve_builder is None:
            raise NotImplementedError(
                "DiscountCurvesNode requires a curve_builder callable or a subclass "
                "that implements build_curve_frame(...)."
            )
        return self.curve_builder(
            update_statistics=update_statistics,
            curve_unique_identifier=curve_unique_identifier,
            base_node_curve_points=base_node_curve_points,
        )

    @staticmethod
    def _normalize_builder_frame(
        frame: pd.DataFrame,
        *,
        curve_unique_identifier: str,
    ) -> pd.DataFrame:
        normalized = frame.copy()
        if isinstance(normalized.index, pd.MultiIndex):
            index_names = [
                CURVE_UNIQUE_IDENTIFIER_DIMENSION if name == "unique_identifier" else name
                for name in normalized.index.names
            ]
            normalized.index = normalized.index.set_names(index_names)
        elif normalized.index.name == "unique_identifier":
            normalized.index.name = CURVE_UNIQUE_IDENTIFIER_DIMENSION

        normalized = normalized.reset_index()
        if (
            "unique_identifier" in normalized.columns
            and CURVE_UNIQUE_IDENTIFIER_DIMENSION not in normalized.columns
        ):
            normalized = normalized.rename(
                columns={"unique_identifier": CURVE_UNIQUE_IDENTIFIER_DIMENSION}
            )
        if CURVE_UNIQUE_IDENTIFIER_DIMENSION not in normalized.columns:
            normalized[CURVE_UNIQUE_IDENTIFIER_DIMENSION] = curve_unique_identifier
        return normalized

    def get_table_metadata(self) -> TableMetaData:
        return TableMetaData(
            identifier=self.config.node_metadata.identifier,
            data_frequency_id=DataFrequency.one_d,
            description=self.config.node_metadata.description,
        )

    def get_column_metadata(self) -> list[ColumnMetaData]:
        return [
            ColumnMetaData(
                column_name="curve",
                dtype="str",
                label="Compressed Curve",
                description="Compressed discount-curve points payload.",
            )
        ]


__all__ = [
    "CURVE_UNIQUE_IDENTIFIER_DIMENSION",
    "CurveConfig",
    "CurveDataNodeConfiguration",
    "CurveTimestampedDataNode",
    "DiscountCurvesNode",
    "DiscountCurveBuilder",
    "curve_indexed_foreign_keys",
    "curve_time_index_record",
    "curve_unique_identifier_foreign_key",
    "curve_unique_identifier_record",
    "discount_curve_records",
]
