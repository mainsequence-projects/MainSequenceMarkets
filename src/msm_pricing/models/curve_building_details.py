from __future__ import annotations

import uuid

from sqlalchemy import ForeignKey, Index, String
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.types import JSON, Uuid

from msm.base import (
    MarketsBase,
    MarketsMetaTableMixin,
    markets_table_args,
)

from .curves import CurveTable


class CurveBuildingDetailsTable(MarketsMetaTableMixin, MarketsBase):
    """Curve-owned build specification for pricing term structures."""

    __metatable_identifier__ = "CurveBuildingDetails"
    __metatable_description__ = (
        "Pricing curve building details keyed by CurveTable.uid. Stores the "
        "builder type, quote convention, calendars, day count, interpolation, "
        "compounding, extrapolation policy, source, and metadata used to rebuild "
        "pricing term structures from curve observations."
    )
    __table_args__ = markets_table_args(
        __metatable_identifier__,
        Index(
            None,
            "builder_type",
        ),
        Index(
            None,
            "quote_convention",
        ),
        Index(
            None,
            "source",
        ),
    )

    curve_uid: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey(
            f"{CurveTable.__table__.fullname}.uid",
            ondelete="CASCADE",
        ),
        primary_key=True,
        nullable=False,
        info={
            "label": "Curve UID",
            "description": "Foreign key to the CurveTable row this build specification owns.",
        },
    )
    builder_type: Mapped[str] = mapped_column(
        String(64),
        nullable=False,
        info={
            "label": "Builder Type",
            "description": "Curve builder type, such as zero_rate_curve or discount_factor_curve.",
        },
    )
    quote_convention: Mapped[str] = mapped_column(
        String(64),
        nullable=False,
        info={
            "label": "Quote Convention",
            "description": "Convention of stored observations, such as zero_rate or discount_factor.",
        },
    )
    rate_unit: Mapped[str] = mapped_column(
        String(32),
        nullable=False,
        info={
            "label": "Rate Unit",
            "description": "Unit used by rate-like observations, such as decimal or percent.",
        },
    )
    day_counter_code: Mapped[str] = mapped_column(
        String(64),
        nullable=False,
        info={
            "label": "Day Counter Code",
            "description": "Serialized day-count convention used by curve construction.",
        },
    )
    calendar_code: Mapped[str] = mapped_column(
        String(64),
        nullable=False,
        info={
            "label": "Calendar Code",
            "description": "Serialized calendar code used by curve construction.",
        },
    )
    interpolation_method: Mapped[str] = mapped_column(
        String(64),
        nullable=False,
        info={
            "label": "Interpolation Method",
            "description": "Interpolation method used by the curve builder.",
        },
    )
    compounding: Mapped[str] = mapped_column(
        String(64),
        nullable=False,
        info={
            "label": "Compounding",
            "description": "Compounding convention used when converting quoted rates.",
        },
    )
    compounding_frequency: Mapped[str | None] = mapped_column(
        String(64),
        nullable=True,
        info={
            "label": "Compounding Frequency",
            "description": "Optional compounding frequency for compounded quote conventions.",
        },
    )
    extrapolation_policy: Mapped[str] = mapped_column(
        String(64),
        nullable=False,
        info={
            "label": "Extrapolation Policy",
            "description": "Policy for using the curve outside observed node maturities.",
        },
    )
    bootstrap_method: Mapped[str | None] = mapped_column(
        String(64),
        nullable=True,
        info={
            "label": "Bootstrap Method",
            "description": "Optional bootstrap method for helper-based curve construction.",
        },
    )
    builder_payload: Mapped[dict | None] = mapped_column(
        JSON,
        nullable=True,
        info={
            "label": "Builder Payload",
            "description": "Optional builder-specific structured JSON payload.",
        },
    )
    source: Mapped[str | None] = mapped_column(
        String(255),
        nullable=True,
        info={
            "label": "Source",
            "description": "Source system, workflow, or provider that produced the row.",
        },
    )
    metadata_json: Mapped[dict | None] = mapped_column(
        "metadata",
        JSON,
        nullable=True,
        info={
            "label": "Metadata",
            "description": "Structured metadata JSON for provider, pricing, or workflow-specific attributes.",
        },
    )


__all__ = ["CurveBuildingDetailsTable"]
