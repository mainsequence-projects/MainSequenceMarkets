"""Signal DataNode storage contracts."""

from __future__ import annotations

import datetime
from typing import ClassVar

from sqlalchemy import DateTime, Float, ForeignKey, String
from sqlalchemy.orm import Mapped, mapped_column

from msm.base import MarketsBase, MarketsTimeIndexMetaTableMixin
from msm.models.assets import AssetTable
from msm.settings import ASSET_IDENTIFIER_DIMENSION
from msm_portfolios.models.signals import SignalMetadataTable


class SignalWeightsStorage(MarketsTimeIndexMetaTableMixin, MarketsBase):
    """Raw signal weights keyed by signal UID and signaled asset."""

    __metatable_identifier__ = "SignalWeightsTS"
    __metatable_description__ = (
        "Timestamped signal weight storage keyed by (time_index, signal_uid, "
        "asset_identifier). Stores raw signal allocation weights for signaled "
        "assets before portfolio execution."
    )
    __time_index_name__: ClassVar[str] = "time_index"
    __index_names__: ClassVar[list[str]] = ["time_index", "signal_uid", ASSET_IDENTIFIER_DIMENSION]

    time_index: Mapped[datetime.datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        info={"label": "Time Index", "description": "UTC timestamp for the signal weight row."},
    )
    signal_uid: Mapped[str] = mapped_column(
        String(255),
        ForeignKey(
            f"{SignalMetadataTable.__table__.fullname}.signal_uid",
            ondelete="RESTRICT",
        ),
        nullable=False,
        info={
            "label": "Signal UID",
            "description": (
                "Deterministic hash of the canonical signal configuration that produced "
                "this signal weight row. References SignalMetadataTable.signal_uid."
            ),
        },
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
            "description": "AssetTable unique_identifier for the signaled instrument.",
        },
    )
    signal_weight: Mapped[float | None] = mapped_column(
        Float,
        nullable=True,
        info={
            "label": "Signal Weight",
            "description": "Raw signal allocation weight before portfolio execution.",
        },
    )


__all__ = ["SignalWeightsStorage"]
