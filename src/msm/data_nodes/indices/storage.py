"""Canonical storage contracts for calculated indexes and dynamic leg provenance."""

from __future__ import annotations

import datetime
import uuid
from typing import ClassVar

from sqlalchemy import CheckConstraint, DateTime, Float, ForeignKey, Index as SqlIndex, String
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.types import JSON, Uuid

from msm.base import MarketsBase, MarketsTimeIndexMetaTableMixin
from msm.models.index_calculations import IndexCalculationDefinitionTable
from msm.models.indices import IndexTable
from msm.settings import INDEX_IDENTIFIER_DIMENSION


class IndexValuesStorage(MarketsTimeIndexMetaTableMixin, MarketsBase):
    """Canonical calculated index observations keyed by index and UTC timestamp."""

    __metatable_identifier__ = "IndexValuesTS"
    __metatable_description__ = (
        "Canonical derived-index value history keyed by (time_index, index_identifier). "
        "Each row records the immutable definition version, unit, calculation status, "
        "and bounded provenance used by downstream DataNodes, APIs, and portfolios."
    )
    __time_index_name__: ClassVar[str] = "time_index"
    __index_names__: ClassVar[list[str]] = ["time_index", INDEX_IDENTIFIER_DIMENSION]
    __metatable_extra_hash_components__ = {"storage_name": "index_values"}
    __table_args__ = (
        SqlIndex(None, "definition_uid"),
        SqlIndex(None, "calculation_status"),
    )

    time_index: Mapped[datetime.datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        info={
            "label": "Time Index",
            "description": "UTC timestamp at which the calculated index observation applies.",
        },
    )
    index_identifier: Mapped[str] = mapped_column(
        String(255),
        ForeignKey(f"{IndexTable.__table__.fullname}.unique_identifier", ondelete="RESTRICT"),
        nullable=False,
        info={
            "label": "Index Identifier",
            "description": "Canonical Index.unique_identifier for the published derived series.",
        },
    )
    value: Mapped[float] = mapped_column(
        Float,
        nullable=False,
        info={
            "label": "Index Value",
            "description": "Calculated value normalized to the definition's declared output unit.",
        },
    )
    unit: Mapped[str] = mapped_column(
        String(64),
        nullable=False,
        info={
            "label": "Unit",
            "description": "Canonical unit code matching the effective definition output unit.",
        },
    )
    definition_uid: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey(
            f"{IndexCalculationDefinitionTable.__table__.fullname}.uid",
            ondelete="RESTRICT",
        ),
        nullable=False,
        info={
            "label": "Definition UID",
            "description": "Exact immutable methodology version used for this observation.",
        },
    )
    calculation_status: Mapped[str] = mapped_column(
        String(32),
        nullable=False,
        info={
            "label": "Calculation Status",
            "description": "Structured readiness state such as ready, stale, or partial.",
        },
    )
    source_as_of: Mapped[datetime.datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
        info={
            "label": "Source As Of",
            "description": "Latest source-observation timestamp contributing to the value.",
        },
    )
    metadata_json: Mapped[dict | None] = mapped_column(
        JSON,
        nullable=True,
        info={
            "label": "Metadata JSON",
            "description": "Bounded calculation diagnostics not represented by canonical columns.",
        },
    )


class IndexResolvedLegsStorage(MarketsTimeIndexMetaTableMixin, MarketsBase):
    """Effective dynamic component and coefficient history for derived indexes."""

    __metatable_identifier__ = "IndexResolvedLegsTS"
    __metatable_description__ = (
        "Dynamic derived-index methodology audit facts keyed by effective UTC time, index, "
        "leg key, and resolved component. Rows preserve selector-resolved membership and "
        "time-varying algebraic coefficients without representing holdings or positions."
    )
    __time_index_name__: ClassVar[str] = "time_index"
    __index_names__: ClassVar[list[str]] = [
        "time_index",
        INDEX_IDENTIFIER_DIMENSION,
        "leg_key",
        "resolved_component_key",
    ]
    __metatable_extra_hash_components__ = {"storage_name": "index_resolved_legs"}
    __table_args__ = (
        CheckConstraint(
            "component_kind IN ('asset', 'index')",
            name="resolved_component_kind_valid",
        ),
        SqlIndex(None, "definition_uid"),
        SqlIndex(None, "resolution_status"),
    )

    time_index: Mapped[datetime.datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        info={
            "label": "Effective Time",
            "description": "UTC timestamp from which this component and coefficient resolution applies.",
        },
    )
    index_identifier: Mapped[str] = mapped_column(
        String(255),
        ForeignKey(f"{IndexTable.__table__.fullname}.unique_identifier", ondelete="RESTRICT"),
        nullable=False,
        info={
            "label": "Index Identifier",
            "description": "Canonical derived-index identifier whose methodology was resolved.",
        },
    )
    definition_uid: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey(
            f"{IndexCalculationDefinitionTable.__table__.fullname}.uid",
            ondelete="RESTRICT",
        ),
        nullable=False,
        info={
            "label": "Definition UID",
            "description": "Immutable methodology version that produced this resolution.",
        },
    )
    leg_key: Mapped[str] = mapped_column(
        String(64),
        nullable=False,
        info={
            "label": "Leg Key",
            "description": "Stable semantic key of the resolved definition leg.",
        },
    )
    resolved_component_key: Mapped[str] = mapped_column(
        String(255),
        nullable=False,
        info={
            "label": "Resolved Component",
            "description": "Stable Asset or Index identifier selected for this effective time.",
        },
    )
    component_kind: Mapped[str] = mapped_column(
        String(32),
        nullable=False,
        info={
            "label": "Component Kind",
            "description": "Identity registry containing the resolved key: asset or index.",
        },
    )
    resolved_coefficient: Mapped[float] = mapped_column(
        Float,
        nullable=False,
        info={
            "label": "Resolved Coefficient",
            "description": "Effective algebraic multiplier produced by the configured method.",
        },
    )
    coefficient_method: Mapped[str] = mapped_column(
        String(64),
        nullable=False,
        info={
            "label": "Coefficient Method",
            "description": "Registered method that produced the effective coefficient.",
        },
    )
    observable_code: Mapped[str] = mapped_column(
        String(64),
        nullable=False,
        info={
            "label": "Observable Code",
            "description": "Semantic observation requested from the resolved component.",
        },
    )
    source_observation_time: Mapped[datetime.datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
        info={
            "label": "Source Observation Time",
            "description": "UTC timestamp of the fact used to select or estimate the resolution.",
        },
    )
    resolution_status: Mapped[str] = mapped_column(
        String(32),
        nullable=False,
        info={
            "label": "Resolution Status",
            "description": "Structured state describing whether component and coefficient resolution succeeded.",
        },
    )
    metadata_json: Mapped[dict | None] = mapped_column(
        JSON,
        nullable=True,
        info={
            "label": "Metadata JSON",
            "description": "Selector or estimator diagnostics used to audit this resolution.",
        },
    )


__all__ = ["IndexResolvedLegsStorage", "IndexValuesStorage"]
