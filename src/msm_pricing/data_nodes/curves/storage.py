"""Pricing curve DataNode storage contracts."""

from __future__ import annotations

import datetime
from typing import ClassVar

from sqlalchemy import DateTime, ForeignKey, String, Text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from msm.base import MarketsBase, MarketsTimeIndexMetaTableMixin
from msm_pricing.models.curves import CurveTable

CURVE_IDENTIFIER_DIMENSION = "curve_identifier"


class DiscountCurvesStorage(MarketsTimeIndexMetaTableMixin, MarketsBase):
    """Daily compressed discount curves used by msm_pricing valuation workflows.

    Each row represents one valuation timestamp and one curve_identifier
    registered in the Curve MetaTable, with the curve column storing the
    compressed term-structure payload and key_nodes recording the input quotes
    used to build that observation. The dataset reconstructs discount term
    structures by curve identity when pricing bonds and other fixed-income
    instruments, while preserving compressed row-level construction provenance
    for audit and diagnostics.
    """

    __metatable_identifier__ = "DiscountCurvesTS"
    __metatable_description__ = (
        "Timestamped discount-curve storage keyed by (time_index, "
        "curve_identifier). Stores compressed curve payloads that reconstruct "
        "discount term structures for pricing workflows, compressed key-node "
        "input quote provenance used to build each curve observation, and "
        "optional structured metadata. Each curve identity links back to the "
        "Curve MetaTable."
    )
    __time_index_name__: ClassVar[str] = "time_index"
    __cadence__: ClassVar[str] = "1d"
    __index_names__: ClassVar[list[str]] = ["time_index", CURVE_IDENTIFIER_DIMENSION]

    time_index: Mapped[datetime.datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        info={"label": "Time Index", "description": "UTC timestamp for the curve observation row."},
    )
    curve_identifier: Mapped[str] = mapped_column(
        String(255),
        ForeignKey(
            f"{CurveTable.__table__.fullname}.unique_identifier",
            ondelete="RESTRICT",
        ),
        nullable=False,
        info={
            "label": "Curve Identifier",
            "description": "Curve unique identifier from the Curve MetaTable.",
        },
    )
    curve: Mapped[str] = mapped_column(
        String,
        nullable=False,
        info={
            "label": "Compressed Curve",
            "description": (
                "Compressed pricing curve node payload consumed by runtime pricing. "
                "The node quote meaning is interpreted through CurveBuildingDetails."
            ),
        },
    )
    key_nodes: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
        info={
            "label": "Compressed Key Nodes",
            "description": (
                "Compressed source-owned JSON construction provenance for this "
                "curve observation. Producers pass JSON object/list values and may "
                "use the recommended CurveKeyNode shape, including a typed asset or "
                "index source_reference, quote_type, quote_unit, quote_side, and "
                "optional yield fields, plus source-specific extensions validated "
                "by the producer DataNode."
            ),
        },
    )
    metadata_json: Mapped[dict | None] = mapped_column(
        JSONB,
        nullable=True,
        info={
            "label": "Metadata JSON",
            "description": (
                "Optional structured row metadata for curve-source diagnostics, "
                "quality flags, provider snapshots, workflow details, or other "
                "non-pricing provenance."
            ),
        },
    )


__all__ = ["CURVE_IDENTIFIER_DIMENSION", "DiscountCurvesStorage"]
