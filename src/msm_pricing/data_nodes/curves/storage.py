"""Pricing curve DataNode storage contracts."""

from __future__ import annotations

import datetime
from typing import ClassVar

from sqlalchemy import DateTime, ForeignKey, String
from sqlalchemy.orm import Mapped, mapped_column

from msm.base import MarketsBase, MarketsTimeIndexMetaTableMixin
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
    curve: Mapped[str | None] = mapped_column(
        String,
        nullable=True,
        info={
            "label": "Compressed Curve",
            "description": "Compressed discount-curve points payload for the curve observation.",
        },
    )


__all__ = ["CURVE_IDENTIFIER_DIMENSION", "DiscountCurvesStorage"]
