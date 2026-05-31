"""Storage-first ``PlatformTimeIndexMetaData`` declarations for msm_pricing.

ADR 0017. Each class is the single source of truth for the column schema,
dtypes, descriptions, and identity foreign keys of one pricing table. The
DataNode validators derive their column dtype maps from these declarations;
catalog registration follows in Stage 5.
"""

from __future__ import annotations

import datetime
from typing import Any, ClassVar

from mainsequence.meta_tables import MetaTableForeignKey
from sqlalchemy import DateTime, Float, String
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from msm.base import MarketsBase, MarketsTimeIndexMetaTableMixin
from msm.models.assets.core import AssetTable
from msm.models.indices import IndexTable
from msm_pricing.models.curves import CurveTable
from msm_pricing.settings import PRICING_CONCEPT_INTEREST_RATE_INDEX_FIXINGS


class DiscountCurvesStorage(MarketsTimeIndexMetaTableMixin, MarketsBase):
    """Daily compressed discount curves used by msm_pricing valuation workflows.

    Each row represents one valuation timestamp and one curve_unique_identifier
    registered in the Curve MetaTable, with the curve column storing the
    compressed term-structure payload. The dataset reconstructs discount term
    structures by curve identity when pricing bonds and other fixed-income
    instruments.
    """

    __markets_base_identifier__: ClassVar[str] = "discount_curves"
    __metatable_description__ = (
        "Timestamped discount-curve storage keyed by (time_index, "
        "curve_unique_identifier). Stores compressed curve payloads that reconstruct "
        "discount term structures for pricing workflows and link each curve identity "
        "back to the Curve MetaTable."
    )
    __metatable_extra_hash_components__: ClassVar[dict[str, Any]] = {
        "storage_name": "discount_curves",
    }
    __time_index_name__: ClassVar[str] = "time_index"
    __index_names__: ClassVar[list[str]] = ["time_index", "curve_unique_identifier"]

    time_index: Mapped[datetime.datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        info={"label": "Time Index", "description": "UTC timestamp for the curve observation row."},
    )
    curve_unique_identifier: Mapped[str] = mapped_column(
        String(255),
        MetaTableForeignKey(
            CurveTable,
            column="unique_identifier",
            ondelete="RESTRICT",
        ),
        nullable=False,
        info={
            "label": "Curve Unique Identifier",
            "description": "Curve unique identifier from the Curve MetaTable.",
        },
    )
    curve: Mapped[str | None] = mapped_column(
        String,
        nullable=True,
        info={
            "label": "Compressed Curve",
            "description": "Compressed discount-curve points payload.",
        },
    )


class IndexFixingsStorage(MarketsTimeIndexMetaTableMixin, MarketsBase):
    """Timestamped interest-rate index fixings used by msm_pricing.

    Each row represents one observation timestamp and one Index unique_identifier,
    with the rate column storing the observed fixing as a decimal value. Pricing
    uses this data to load historical SOFR, TIIE, IBOR, overnight, and other
    reference-rate fixings for floating-rate bonds and swaps.
    """

    __markets_base_identifier__: ClassVar[str] = PRICING_CONCEPT_INTEREST_RATE_INDEX_FIXINGS
    __metatable_description__ = (
        "Timestamped interest-rate index fixing storage keyed by (time_index, "
        "unique_identifier). Stores observed index fixing rates used by pricing "
        "workflows for floating-rate bonds, swaps, and curve-linked analytics."
    )
    __metatable_extra_hash_components__: ClassVar[dict[str, Any]] = {
        "storage_name": PRICING_CONCEPT_INTEREST_RATE_INDEX_FIXINGS,
    }
    __time_index_name__: ClassVar[str] = "time_index"
    __index_names__: ClassVar[list[str]] = ["time_index", "unique_identifier"]

    time_index: Mapped[datetime.datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        info={"label": "Time Index", "description": "UTC timestamp for the index fact row."},
    )
    unique_identifier: Mapped[str] = mapped_column(
        String(255),
        MetaTableForeignKey(
            IndexTable,
            column="unique_identifier",
            ondelete="RESTRICT",
        ),
        nullable=False,
        info={
            "label": "Unique Identifier",
            "description": "Index unique identifier from the Index MetaTable.",
        },
    )
    rate: Mapped[float | None] = mapped_column(
        Float,
        nullable=True,
        info={
            "label": "Fixing Rate",
            "description": "Observed index fixing rate normalized to decimal form.",
        },
    )


class AssetPricingDetailsStorage(MarketsTimeIndexMetaTableMixin, MarketsBase):
    """Timestamped provider pricing metadata keyed by asset unique identifier."""

    __markets_base_identifier__: ClassVar[str] = "asset_pricing_details"
    __metatable_description__ = (
        "Timestamped asset pricing-detail storage keyed by (time_index, "
        "unique_identifier). Stores serialized pricing instrument payloads for "
        "canonical assets before current-pricing rows are promoted."
    )
    __metatable_extra_hash_components__: ClassVar[dict[str, Any]] = {
        "storage_name": "asset_pricing_details",
    }
    __time_index_name__: ClassVar[str] = "time_index"
    __index_names__: ClassVar[list[str]] = ["time_index", "unique_identifier"]

    time_index: Mapped[datetime.datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        info={"label": "Time Index", "description": "UTC timestamp for the asset fact row."},
    )
    unique_identifier: Mapped[str] = mapped_column(
        String(255),
        MetaTableForeignKey(
            AssetTable,
            column="unique_identifier",
            ondelete="RESTRICT",
        ),
        nullable=False,
        info={
            "label": "Unique Identifier",
            "description": "Asset unique identifier from the Asset MetaTable.",
        },
    )
    instrument_dump: Mapped[dict | None] = mapped_column(
        JSONB,
        nullable=True,
        info={
            "label": "Instrument Dump",
            "description": "Provider-specific pricing instrument payload.",
        },
    )


__all__ = [
    "AssetPricingDetailsStorage",
    "DiscountCurvesStorage",
    "IndexFixingsStorage",
]
