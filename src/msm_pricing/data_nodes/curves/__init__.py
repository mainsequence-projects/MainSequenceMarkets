from __future__ import annotations

import datetime as dt
from collections.abc import Mapping
from typing import Any, ClassVar, Protocol

import pandas as pd
from pydantic import Field

from mainsequence.meta_tables import APIDataNode, DataNode
from msm.data_nodes.utils.stamped import (
    StampedDataNode,
    StampedDataNodeConfiguration,
)

from ..curve_codec import compress_curve_to_string
from .key_nodes import CurveKeyNode, normalize_curve_key_nodes, normalize_curve_metadata
from .storage import CURVE_IDENTIFIER_DIMENSION, DiscountCurvesStorage

CURVE_IDENTIFIER = CURVE_IDENTIFIER_DIMENSION


class DiscountCurveBuilder(Protocol):
    """Runtime builder for one curve identity."""

    def __call__(
        self,
        *,
        update_statistics,
        curve_identifier: str,
        base_node_curve_points: APIDataNode | None,
    ) -> pd.DataFrame: ...


class CurveKeyNodesValidator(Protocol):
    """Runtime semantic validator for source-owned curve key-node provenance."""

    def __call__(
        self,
        value: Any,
        *,
        row: Mapping[str, Any],
        curve_identifier: str,
    ) -> Any: ...


class CurveDataNodeConfiguration(StampedDataNodeConfiguration):
    """Configuration for timestamped curve DataNodes.

    Storage-first: the column schema, index names, and the canonical
    ``Curve.unique_identifier`` foreign key live on the ``storage_table``
    (a ``DiscountCurvesStorage``-style ``PlatformTimeIndexMetaTable`` class),
    not on this configuration.
    """

    reference_dimension: ClassVar[str] = CURVE_IDENTIFIER
    frame_label: ClassVar[str] = "Curve DataNode"


class CurveTimestampedDataNode(StampedDataNode):
    """Base curve DataNode for timestamped facts keyed by curve_identifier."""

    configuration_class: ClassVar[type[CurveDataNodeConfiguration]] = CurveDataNodeConfiguration
    frame_label: ClassVar[str] = "Curve DataNode"


class CurveConfig(CurveDataNodeConfiguration):
    """Configuration for the canonical discount-curves DataNode."""

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
    )


class DiscountCurvesNode(CurveTimestampedDataNode):
    """Compressed discount curves keyed by curve unique identifier."""

    configuration_class = CurveConfig
    OFFSET_START = dt.datetime(1990, 1, 1, tzinfo=dt.UTC)

    def __init__(
        self,
        curve_config: CurveConfig,
        **kwargs,
    ):
        self.curve_config = curve_config
        self.curve_builder: DiscountCurveBuilder | None = None
        self.key_nodes_validator: CurveKeyNodesValidator | None = None
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

    @classmethod
    def _required_storage_table(cls) -> type[DiscountCurvesStorage]:
        return DiscountCurvesStorage

    def set_curve_builder(self, curve_builder: DiscountCurveBuilder) -> DiscountCurvesNode:
        self.curve_builder = curve_builder
        return self

    def set_key_nodes_validator(
        self,
        key_nodes_validator: CurveKeyNodesValidator | None,
    ) -> DiscountCurvesNode:
        """Attach optional producer-owned semantic validation for key_nodes.

        The base DataNode always applies storage-level JSON normalization. This
        hook lets a producer enforce source-specific requirements without making
        those requirements part of the shared storage contract or hashed config.
        """

        self.key_nodes_validator = key_nodes_validator
        return self

    def normalize_key_nodes(
        self,
        value: Any,
        *,
        row: Mapping[str, Any],
        curve_identifier: str,
    ) -> Any:
        """Normalize and optionally validate source-owned key-node provenance."""

        normalized = normalize_curve_key_nodes(value)
        if self.key_nodes_validator is None:
            return normalized
        validated = self.key_nodes_validator(
            normalized,
            row=row,
            curve_identifier=curve_identifier,
        )
        return normalize_curve_key_nodes(validated)

    def update(self) -> pd.DataFrame:
        curve_identifier = self.curve_config.curve_unique_identifier
        frame = self.build_curve_frame(
            update_statistics=self.update_statistics,
            curve_identifier=curve_identifier,
            base_node_curve_points=self.base_node_curve_points,
        )
        if frame.empty:
            return pd.DataFrame()

        normalized = self._normalize_builder_frame(
            frame,
            curve_identifier=curve_identifier,
        )
        normalized["curve"] = normalized["curve"].apply(compress_curve_to_string)
        normalized["time_index"] = pd.to_datetime(normalized["time_index"], utc=True)

        last = self.update_statistics.get_last_update_for_identity(curve_identifier)
        if last is not None:
            normalized = normalized[normalized["time_index"] > pd.Timestamp(last)]
        if normalized.empty:
            return pd.DataFrame()

        return self.validate_frame(normalized, storage_table=self.storage_table)

    def build_curve_frame(
        self,
        *,
        update_statistics,
        curve_identifier: str,
        base_node_curve_points: APIDataNode | None,
    ) -> pd.DataFrame:
        if self.curve_builder is None:
            raise NotImplementedError(
                "DiscountCurvesNode requires a curve_builder callable or a subclass "
                "that implements build_curve_frame(...)."
            )
        return self.curve_builder(
            update_statistics=update_statistics,
            curve_identifier=curve_identifier,
            base_node_curve_points=base_node_curve_points,
        )

    def _normalize_builder_frame(
        self_or_frame,
        frame: pd.DataFrame | None = None,
        *,
        curve_identifier: str,
        key_nodes_normalizer: CurveKeyNodesValidator | None = None,
    ) -> pd.DataFrame:
        instance = None if frame is None else self_or_frame
        source_frame = self_or_frame if frame is None else frame
        if key_nodes_normalizer is None and isinstance(instance, DiscountCurvesNode):
            key_nodes_normalizer = instance.normalize_key_nodes
        if key_nodes_normalizer is None:
            key_nodes_normalizer = _normalize_key_nodes_without_semantic_validator

        normalized = source_frame.copy()
        normalized = normalized.reset_index()
        stale_columns = {"unique_identifier", "curve_unique_identifier"}.intersection(
            normalized.columns
        )
        if stale_columns:
            raise ValueError(
                "Discount curve builder frames must use curve_identifier, not "
                f"{sorted(stale_columns)!r}."
            )
        if CURVE_IDENTIFIER not in normalized.columns:
            normalized[CURVE_IDENTIFIER] = curve_identifier
        if "curve" not in normalized.columns:
            raise ValueError(
                "Discount curve builder frames must include a non-empty curve "
                "mapping for each curve observation."
            )
        normalized["curve"] = normalized["curve"].apply(_normalize_curve_payload)
        if "metadata_json" not in normalized.columns:
            normalized["metadata_json"] = None
        else:
            normalized["metadata_json"] = normalized["metadata_json"].apply(normalize_curve_metadata)
        if "key_nodes" not in normalized.columns:
            raise ValueError(
                "Discount curve builder frames must include key_nodes construction "
                "provenance for each curve observation."
            )
        normalized["key_nodes"] = [
            key_nodes_normalizer(
                row["key_nodes"],
                row=row,
                curve_identifier=str(row.get(CURVE_IDENTIFIER) or curve_identifier),
            )
            for row in normalized.to_dict(orient="records")
        ]
        return normalized


def _normalize_curve_payload(value):
    if not isinstance(value, Mapping) or not value:
        raise ValueError(
            "Discount curve builder frames must include a non-empty curve "
            "mapping for each curve observation."
        )
    return dict(value)


def _normalize_key_nodes_without_semantic_validator(
    value: Any,
    *,
    row: Mapping[str, Any],
    curve_identifier: str,
) -> Any:
    return normalize_curve_key_nodes(value)


__all__ = [
    "CURVE_IDENTIFIER",
    "CurveConfig",
    "CurveDataNodeConfiguration",
    "CurveKeyNode",
    "CurveKeyNodesValidator",
    "CurveTimestampedDataNode",
    "DiscountCurvesNode",
    "DiscountCurveBuilder",
]
