from __future__ import annotations

import datetime
import uuid

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, Index as SqlIndex
from sqlalchemy import Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.sql import text
from sqlalchemy.types import JSON, Uuid

from msm.base import MarketsBase, MarketsMetaTableMixin, markets_table_args, new_markets_uid
from msm.models.assets.core import AssetTable
from msm.models.indices import IndexTable


class IndexFormulaDefinitionTable(MarketsMetaTableMixin, MarketsBase):
    """Immutable formula version for one Index."""

    __metatable_identifier__ = "IndexFormulaDefinition"
    __metatable_description__ = (
        "Versioned point-in-time formulas keyed by Index identity. Each row owns the "
        "expression, alignment and missing-data policies, validity interval, and semantic hash."
    )
    __table_args__ = markets_table_args(
        __metatable_identifier__,
        CheckConstraint("version > 0", name="formula_version_positive"),
        CheckConstraint(
            "valid_to IS NULL OR valid_to > valid_from",
            name="formula_validity_interval_valid",
        ),
        CheckConstraint(
            "status IN ('draft', 'active', 'retired')",
            name="formula_status_valid",
        ),
        CheckConstraint(
            "alignment_policy IN ('exact', 'asof')",
            name="formula_alignment_policy_valid",
        ),
        CheckConstraint(
            "missing_data_policy IN ('drop', 'fail')",
            name="formula_missing_data_policy_valid",
        ),
        SqlIndex(None, "index_uid", "version", unique=True),
        SqlIndex(None, "index_uid", "definition_hash", unique=True),
        SqlIndex(None, "index_uid"),
        SqlIndex(None, "status"),
        SqlIndex(None, "valid_from"),
        SqlIndex(
            None,
            "index_uid",
            unique=True,
            postgresql_where=text("status = 'active'"),
        ),
    )

    uid: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True),
        primary_key=True,
        default=new_markets_uid,
        info={"label": "Formula UID", "description": "Stable UUID for this formula version."},
    )
    index_uid: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey(f"{IndexTable.__table__.fullname}.uid", ondelete="CASCADE"),
        nullable=False,
        info={"label": "Index UID", "description": "Formula Index that owns this version."},
    )
    version: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        info={
            "label": "Version",
            "description": "Positive monotonic version for this formula definition.",
        },
    )
    status: Mapped[str] = mapped_column(
        String(32),
        nullable=False,
        default="draft",
        info={"label": "Status", "description": "Draft, active, or retired lifecycle state."},
    )
    valid_from: Mapped[datetime.datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        info={
            "label": "Formula Starts At",
            "description": "Inclusive UTC timestamp calculated with this formula version.",
        },
    )
    valid_to: Mapped[datetime.datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
        info={
            "label": "Formula Ends At",
            "description": "Exclusive UTC timestamp at which this version stops applying.",
        },
    )
    formula: Mapped[str] = mapped_column(
        Text,
        nullable=False,
        info={
            "label": "Formula",
            "description": "Strict point-in-time arithmetic expression for this Index.",
        },
    )
    alignment_policy: Mapped[str] = mapped_column(
        String(16),
        nullable=False,
        default="exact",
        info={"label": "Alignment", "description": "Exact or bounded as-of alignment."},
    )
    alignment_parameters_json: Mapped[dict | None] = mapped_column(
        JSON,
        nullable=True,
        info={
            "label": "Alignment Parameters",
            "description": "Strict as-of parameters including maximum staleness.",
        },
    )
    missing_data_policy: Mapped[str] = mapped_column(
        String(16),
        nullable=False,
        default="drop",
        info={"label": "Missing Data", "description": "Drop or fail on missing inputs."},
    )
    definition_hash: Mapped[str] = mapped_column(
        String(64),
        nullable=False,
        info={
            "label": "Definition Hash",
            "description": "Canonical SHA-256 digest of formula semantics.",
        },
    )
    metadata_json: Mapped[dict | None] = mapped_column(
        JSON,
        nullable=True,
        info={
            "label": "Metadata JSON",
            "description": "Non-calculation descriptive metadata for this formula version.",
        },
    )


class IndexFormulaInputTable(MarketsMetaTableMixin, MarketsBase):
    """Exact Asset or Index observable referenced by a formula."""

    __metatable_identifier__ = "IndexFormulaInput"
    __metatable_description__ = (
        "Formula inputs keyed by formula version. Each row resolves one Asset or component "
        "Index through an exact source MetaTable UID and numeric observable column."
    )
    __table_args__ = markets_table_args(
        __metatable_identifier__,
        CheckConstraint(
            "(CASE WHEN asset_uid IS NOT NULL THEN 1 ELSE 0 END + "
            "CASE WHEN component_index_uid IS NOT NULL THEN 1 ELSE 0 END) = 1",
            name="formula_input_source_exclusive",
        ),
        SqlIndex(
            None,
            "definition_uid",
            "asset_uid",
            "observable",
            unique=True,
            postgresql_where=text("asset_uid IS NOT NULL"),
        ),
        SqlIndex(
            None,
            "definition_uid",
            "component_index_uid",
            "observable",
            unique=True,
            postgresql_where=text("component_index_uid IS NOT NULL"),
        ),
        SqlIndex(None, "definition_uid"),
        SqlIndex(None, "asset_uid"),
        SqlIndex(None, "component_index_uid"),
        SqlIndex(None, "meta_table_uid"),
    )

    uid: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True),
        primary_key=True,
        default=new_markets_uid,
        info={"label": "Input UID", "description": "Stable UUID for this formula input."},
    )
    definition_uid: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey(f"{IndexFormulaDefinitionTable.__table__.fullname}.uid", ondelete="CASCADE"),
        nullable=False,
        info={"label": "Formula UID", "description": "Formula version that owns this input."},
    )
    asset_uid: Mapped[uuid.UUID | None] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey(f"{AssetTable.__table__.fullname}.uid", ondelete="RESTRICT"),
        nullable=True,
        info={
            "label": "Asset UID",
            "description": "Referenced Asset identity for this formula input.",
        },
    )
    component_index_uid: Mapped[uuid.UUID | None] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey(f"{IndexTable.__table__.fullname}.uid", ondelete="RESTRICT"),
        nullable=True,
        info={
            "label": "Component Index UID",
            "description": "Referenced component Index identity for this formula input.",
        },
    )
    meta_table_uid: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True),
        nullable=False,
        info={
            "label": "MetaTable UID",
            "description": "Exact Main Sequence source MetaTable UID; not a relational database FK.",
        },
    )
    observable: Mapped[str] = mapped_column(
        String(255),
        nullable=False,
        info={
            "label": "Observable",
            "description": "Exact numeric source column used by the formula.",
        },
    )


__all__ = ["IndexFormulaDefinitionTable", "IndexFormulaInputTable"]
