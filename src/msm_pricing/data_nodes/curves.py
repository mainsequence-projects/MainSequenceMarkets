from __future__ import annotations

import datetime as dt
from typing import ClassVar, Protocol

import pandas as pd
from pydantic import Field

from mainsequence.meta_tables import APIDataNode, DataNode
from msm.data_nodes.utils.stamped import (
    StampedDataNode,
    StampedDataNodeConfiguration,
)

from .curve_codec import compress_curve_to_string
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

    @staticmethod
    def _normalize_builder_frame(
        frame: pd.DataFrame,
        *,
        curve_identifier: str,
    ) -> pd.DataFrame:
        normalized = frame.copy()
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
        return normalized


__all__ = [
    "CURVE_IDENTIFIER",
    "CurveConfig",
    "CurveDataNodeConfiguration",
    "CurveTimestampedDataNode",
    "DiscountCurvesNode",
    "DiscountCurveBuilder",
]
