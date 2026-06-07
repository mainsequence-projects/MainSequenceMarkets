"""Signal DataNode storage contracts."""

from __future__ import annotations

import datetime
from typing import ClassVar

from sqlalchemy import DateTime, Float, String
from sqlalchemy.orm import Mapped, mapped_column

from msm.base import MarketsBase, MarketsTimeIndexMetaTableMixin
from msm.settings import ASSET_IDENTIFIER_DIMENSION


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
        String,
        nullable=False,
        info={
            "label": "Signal UID",
            "description": (
                "Deterministic hash of the canonical signal configuration that produced "
                "this signal weight row."
            ),
        },
    )
    asset_identifier: Mapped[str] = mapped_column(
        String,
        nullable=False,
        info={
            "label": "Asset Identifier",
            "description": "Asset unique identifier for the signaled instrument.",
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
