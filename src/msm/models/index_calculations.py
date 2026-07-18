from __future__ import annotations

import datetime
import uuid

from sqlalchemy import CheckConstraint, DateTime, Float, ForeignKey, Index as SqlIndex
from sqlalchemy import Integer, String
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.types import JSON, Uuid

from msm.base import MarketsBase, MarketsMetaTableMixin, markets_table_args, new_markets_uid
from msm.models.assets.core import AssetTable
from msm.models.indices import IndexTable


class IndexCalculationDefinitionTable(MarketsMetaTableMixin, MarketsBase):
    """Immutable, effective-dated methodology version for one market index."""

    __metatable_identifier__ = "IndexCalculationDefinition"
    __metatable_description__ = (
        "Versioned derived-index methodology rows keyed by definition UID. Each row "
        "owns the operator, output unit, temporal alignment, missing-data behavior, "
        "composition policy, and effective interval used to interpret published index "
        "values without widening the canonical Index identity table."
    )
    __table_args__ = markets_table_args(
        __metatable_identifier__,
        CheckConstraint("definition_version > 0", name="definition_version_positive"),
        CheckConstraint(
            "effective_to IS NULL OR effective_to > effective_from",
            name="effective_interval_valid",
        ),
        CheckConstraint(
            "status IN ('draft', 'active', 'retired')",
            name="definition_status_valid",
        ),
        CheckConstraint(
            "composition_mode IN ('fixed', 'rule_selected', 'rebalanced')",
            name="composition_mode_valid",
        ),
        SqlIndex(None, "index_uid", "definition_version", unique=True),
        SqlIndex(None, "index_uid"),
        SqlIndex(None, "status"),
        SqlIndex(None, "effective_from"),
        SqlIndex(None, "calculation_family"),
        SqlIndex(None, "index_uid", "definition_hash", unique=True),
    )

    uid: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True),
        primary_key=True,
        default=new_markets_uid,
        info={
            "label": "Definition UID",
            "description": "Stable UUID for this exact immutable methodology version.",
        },
    )
    index_uid: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey(f"{IndexTable.__table__.fullname}.uid", ondelete="CASCADE"),
        nullable=False,
        info={
            "label": "Index UID",
            "description": "Canonical Index row whose calculated meaning this version defines.",
        },
    )
    definition_version: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        info={
            "label": "Definition Version",
            "description": "Monotonically increasing positive methodology version within the index.",
        },
    )
    status: Mapped[str] = mapped_column(
        String(32),
        nullable=False,
        default="draft",
        info={
            "label": "Status",
            "description": "Lifecycle state controlling whether the immutable version is executable.",
        },
    )
    effective_from: Mapped[datetime.datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        info={
            "label": "Effective From",
            "description": "Inclusive UTC timestamp from which this methodology applies.",
        },
    )
    effective_to: Mapped[datetime.datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
        info={
            "label": "Effective To",
            "description": "Exclusive UTC timestamp at which this methodology stops applying.",
        },
    )
    calculation_kind: Mapped[str] = mapped_column(
        String(64),
        nullable=False,
        info={
            "label": "Calculation Kind",
            "description": "Registered mathematical operator used to calculate this index version.",
        },
    )
    calculation_family: Mapped[str] = mapped_column(
        String(64),
        nullable=False,
        info={
            "label": "Calculation Family",
            "description": "Searchable business classification such as yield_spread or butterfly.",
        },
    )
    calculation_parameters_json: Mapped[dict | None] = mapped_column(
        JSON,
        nullable=True,
        info={
            "label": "Calculation Parameters",
            "description": "Strict operator-specific parameters such as base level or financing policy.",
        },
    )
    output_unit: Mapped[str] = mapped_column(
        String(64),
        nullable=False,
        info={
            "label": "Output Unit",
            "description": "Canonical unit code attached to every value published by this version.",
        },
    )
    alignment_policy: Mapped[str] = mapped_column(
        String(64),
        nullable=False,
        info={
            "label": "Alignment Policy",
            "description": "Registered rule for aligning leg observations to calculation timestamps.",
        },
    )
    alignment_parameters_json: Mapped[dict | None] = mapped_column(
        JSON,
        nullable=True,
        info={
            "label": "Alignment Parameters",
            "description": "Strict policy parameters such as maximum as-of staleness.",
        },
    )
    missing_data_policy: Mapped[str] = mapped_column(
        String(64),
        nullable=False,
        info={
            "label": "Missing Data Policy",
            "description": "Registered rule applied when required aligned observations are absent.",
        },
    )
    missing_data_parameters_json: Mapped[dict | None] = mapped_column(
        JSON,
        nullable=True,
        info={
            "label": "Missing Data Parameters",
            "description": "Strict policy parameters such as maximum forward-fill age.",
        },
    )
    composition_mode: Mapped[str] = mapped_column(
        String(32),
        nullable=False,
        info={
            "label": "Composition Mode",
            "description": "Whether legs are fixed, rule-selected, or explicitly rebalanced.",
        },
    )
    rebalance_policy: Mapped[str | None] = mapped_column(
        String(64),
        nullable=True,
        info={
            "label": "Rebalance Policy",
            "description": "Registered schedule or trigger used for non-fixed composition changes.",
        },
    )
    rebalance_parameters_json: Mapped[dict | None] = mapped_column(
        JSON,
        nullable=True,
        info={
            "label": "Rebalance Parameters",
            "description": "Strict policy-specific parameters for the registered rebalance rule.",
        },
    )
    definition_hash: Mapped[str] = mapped_column(
        String(64),
        nullable=False,
        info={
            "label": "Definition Hash",
            "description": "Deterministic SHA-256 digest of all output-affecting ordered semantics.",
        },
    )
    source: Mapped[str | None] = mapped_column(
        String(255),
        nullable=True,
        info={
            "label": "Source",
            "description": "Optional methodology owner, organization, or governed source namespace.",
        },
    )
    metadata_json: Mapped[dict | None] = mapped_column(
        JSON,
        nullable=True,
        info={
            "label": "Metadata JSON",
            "description": "Descriptive extension metadata that does not affect calculation output.",
        },
    )


class IndexCalculationLegTable(MarketsMetaTableMixin, MarketsBase):
    """Ordered, typed semantic input for one index calculation definition."""

    __metatable_identifier__ = "IndexCalculationLeg"
    __metatable_description__ = (
        "Ordered derived-index calculation legs keyed by definition and stable leg key. "
        "Each row identifies exactly one fixed asset, component index, or selector and "
        "records its observable, unit, transform, and algebraic coefficient policy."
    )
    __table_args__ = markets_table_args(
        __metatable_identifier__,
        CheckConstraint("leg_order >= 0", name="leg_order_nonnegative"),
        CheckConstraint(
            "(CASE WHEN asset_uid IS NOT NULL THEN 1 ELSE 0 END + "
            "CASE WHEN component_index_uid IS NOT NULL THEN 1 ELSE 0 END + "
            "CASE WHEN selector_code IS NOT NULL THEN 1 ELSE 0 END) = 1",
            name="component_source_exclusive",
        ),
        CheckConstraint(
            "(coefficient_method = 'fixed' AND coefficient IS NOT NULL) OR "
            "(coefficient_method <> 'fixed' AND coefficient IS NULL)",
            name="coefficient_contract_valid",
        ),
        SqlIndex(None, "definition_uid", "leg_key", unique=True),
        SqlIndex(None, "definition_uid", "leg_order", unique=True),
        SqlIndex(None, "asset_uid"),
        SqlIndex(None, "component_index_uid"),
        SqlIndex(None, "selector_code"),
    )

    uid: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True),
        primary_key=True,
        default=new_markets_uid,
        info={
            "label": "Leg UID",
            "description": "Stable UUID for this ordered calculation-leg row.",
        },
    )
    definition_uid: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey(
            f"{IndexCalculationDefinitionTable.__table__.fullname}.uid",
            ondelete="CASCADE",
        ),
        nullable=False,
        info={
            "label": "Definition UID",
            "description": "Immutable methodology version that owns this ordered input leg.",
        },
    )
    leg_key: Mapped[str] = mapped_column(
        String(64),
        nullable=False,
        info={
            "label": "Leg Key",
            "description": "Stable semantic key used to address this leg within its definition.",
        },
    )
    leg_order: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        info={
            "label": "Leg Order",
            "description": "Zero-based deterministic display and calculation order.",
        },
    )
    leg_role: Mapped[str | None] = mapped_column(
        String(64),
        nullable=True,
        info={
            "label": "Leg Role",
            "description": "Optional business role such as numerator, denominator, or hedge.",
        },
    )
    component_kind: Mapped[str] = mapped_column(
        String(32),
        nullable=False,
        info={
            "label": "Component Kind",
            "description": "Declared source kind: asset, index, or selector.",
        },
    )
    asset_uid: Mapped[uuid.UUID | None] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey(f"{AssetTable.__table__.fullname}.uid", ondelete="RESTRICT"),
        nullable=True,
        info={
            "label": "Asset UID",
            "description": "Fixed Asset row used by this leg when component_kind is asset.",
        },
    )
    component_index_uid: Mapped[uuid.UUID | None] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey(f"{IndexTable.__table__.fullname}.uid", ondelete="RESTRICT"),
        nullable=True,
        info={
            "label": "Component Index UID",
            "description": "Fixed component Index row used by an index-on-index leg.",
        },
    )
    selector_code: Mapped[str | None] = mapped_column(
        String(64),
        nullable=True,
        info={
            "label": "Selector Code",
            "description": "Registered deterministic selector used to resolve a component over time.",
        },
    )
    selector_parameters_json: Mapped[dict | None] = mapped_column(
        JSON,
        nullable=True,
        info={
            "label": "Selector Parameters",
            "description": "Strict selector-specific parameters such as target tenor or futures rank.",
        },
    )
    observable_code: Mapped[str] = mapped_column(
        String(64),
        nullable=False,
        info={
            "label": "Observable Code",
            "description": "Semantic source observation requested for the resolved component.",
        },
    )
    input_unit: Mapped[str] = mapped_column(
        String(64),
        nullable=False,
        info={
            "label": "Input Unit",
            "description": "Unit expected from the source observation before normalization.",
        },
    )
    transform_code: Mapped[str] = mapped_column(
        String(64),
        nullable=False,
        info={
            "label": "Transform Code",
            "description": "Registered transformation applied before coefficient multiplication.",
        },
    )
    transform_parameters_json: Mapped[dict | None] = mapped_column(
        JSON,
        nullable=True,
        info={
            "label": "Transform Parameters",
            "description": "Strict transform-specific parameters such as a rebase value.",
        },
    )
    coefficient_method: Mapped[str] = mapped_column(
        String(64),
        nullable=False,
        info={
            "label": "Coefficient Method",
            "description": "Registered fixed or dynamic method producing the algebraic multiplier.",
        },
    )
    coefficient: Mapped[float | None] = mapped_column(
        Float,
        nullable=True,
        info={
            "label": "Coefficient",
            "description": "Finite algebraic multiplier present only for fixed-coefficient legs.",
        },
    )
    coefficient_parameters_json: Mapped[dict | None] = mapped_column(
        JSON,
        nullable=True,
        info={
            "label": "Coefficient Parameters",
            "description": "Strict method-specific estimation window, lag, bounds, and fallback policy.",
        },
    )
    metadata_json: Mapped[dict | None] = mapped_column(
        JSON,
        nullable=True,
        info={
            "label": "Metadata JSON",
            "description": "Descriptive leg metadata excluded from calculation semantics.",
        },
    )


__all__ = [
    "IndexCalculationDefinitionTable",
    "IndexCalculationLegTable",
]
