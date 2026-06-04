"""Storage-first ``PlatformTimeIndexMetaData`` declarations for msm_pricing.

ADR 0017. Each class is the single source of truth for the column schema,
dtypes, descriptions, and identity foreign keys of one pricing table. The
DataNode validators derive their column dtype maps from these declarations;
catalog registration follows in Stage 5.
"""

from __future__ import annotations

import datetime
from typing import ClassVar

from sqlalchemy import DateTime, Float, ForeignKey, String
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from msm.base import MarketsBase, MarketsTimeIndexMetaTableMixin
from msm.models.assets.core import AssetTable
from msm.models.indices import IndexTable
from msm.settings import ASSET_IDENTIFIER_DIMENSION, INDEX_IDENTIFIER_DIMENSION
from msm_pricing.models.curves import CurveTable

CURVE_IDENTIFIER_DIMENSION = "curve_identifier"


class DiscountCurvesStorage(MarketsTimeIndexMetaTableMixin, MarketsBase):
    """Daily compressed discount curves used by msm_pricing valuation workflows.

    Each row represents one valuation timestamp and one curve_identifier
    registered in the Curve MetaTable, with the curve column storing the
    compressed term-structure payload. The dataset reconstructs discount term
    structures by curve identity when pricing bonds and other fixed-income
    instruments.
    """

    __metatable_identifier__ = "DiscountCurvesTS"
    __metatable_description__ = (
        "Timestamped discount-curve storage keyed by (time_index, "
        "curve_identifier). Stores compressed curve payloads that reconstruct "
        "discount term structures for pricing workflows and link each curve identity "
        "back to the Curve MetaTable."
    )
    __time_index_name__: ClassVar[str] = "time_index"
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
    curve: Mapped[str | None] = mapped_column(
        String,
        nullable=True,
        info={
            "label": "Compressed Curve",
            "description": "Compressed discount-curve points payload for the curve observation.",
        },
    )


class IndexFixingsStorage(MarketsTimeIndexMetaTableMixin, MarketsBase):
    """Timestamped interest-rate index fixings used by msm_pricing.

    Each row represents one observation timestamp and one Index identifier,
    with the rate column storing the observed fixing as a decimal value. Pricing
    uses this data to load historical SOFR, TIIE, IBOR, overnight, and other
    reference-rate fixings for floating-rate bonds and swaps.
    """

    __metatable_identifier__ = "IndexFixingsTS"
    __metatable_description__ = (
        "Timestamped interest-rate index fixing storage keyed by (time_index, "
        "index_identifier). Stores observed index fixing rates used by pricing "
        "workflows for floating-rate bonds, swaps, and curve-linked analytics."
    )
    __time_index_name__: ClassVar[str] = "time_index"
    __index_names__: ClassVar[list[str]] = ["time_index", INDEX_IDENTIFIER_DIMENSION]

    time_index: Mapped[datetime.datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        info={"label": "Time Index", "description": "UTC timestamp for the index fact row."},
    )
    index_identifier: Mapped[str] = mapped_column(
        String(255),
        ForeignKey(
            f"{IndexTable.__table__.fullname}.unique_identifier",
            ondelete="RESTRICT",
        ),
        nullable=False,
        info={
            "label": "Index Identifier",
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

    __metatable_identifier__ = "AssetPricingDetailsTS"
    __metatable_description__ = (
        "Timestamped asset pricing-detail storage keyed by (time_index, "
        "asset_identifier). Stores serialized pricing instrument payloads for "
        "canonical assets before current-pricing rows are promoted."
    )
    __time_index_name__: ClassVar[str] = "time_index"
    __index_names__: ClassVar[list[str]] = ["time_index", ASSET_IDENTIFIER_DIMENSION]

    time_index: Mapped[datetime.datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        info={"label": "Time Index", "description": "UTC timestamp for the asset fact row."},
    )
    asset_identifier: Mapped[str] = mapped_column(
        String(255),
        ForeignKey(
            f"{AssetTable.__table__.fullname}.unique_identifier",
            ondelete="RESTRICT",
        ),
        nullable=False,
        info={
            "label": "Asset Identifier",
            "description": "Asset unique identifier from the Asset MetaTable.",
        },
    )
    instrument_dump: Mapped[dict | None] = mapped_column(
        JSONB,
        nullable=True,
        info={
            "label": "Instrument Dump",
            "description": "Provider-specific pricing instrument payload for the asset observation.",
        },
    )


__all__ = [
    "AssetPricingDetailsStorage",
    "CURVE_IDENTIFIER_DIMENSION",
    "DiscountCurvesStorage",
    "IndexFixingsStorage",
]
