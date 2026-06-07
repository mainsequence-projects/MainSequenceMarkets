"""Pricing index-fixing DataNode storage contracts."""

from __future__ import annotations

import datetime
from typing import ClassVar

from sqlalchemy import DateTime, Float, ForeignKey, String
from sqlalchemy.orm import Mapped, mapped_column

from msm.base import MarketsBase, MarketsTimeIndexMetaTableMixin
from msm.models.indices import IndexTable
from msm.settings import INDEX_IDENTIFIER_DIMENSION


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
    __cadence__: ClassVar[str] = "1d"
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


__all__ = ["IndexFixingsStorage"]
