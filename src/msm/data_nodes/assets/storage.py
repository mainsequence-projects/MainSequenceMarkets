"""Asset DataNode storage contracts."""

from __future__ import annotations

import datetime
from typing import ClassVar

from sqlalchemy import DateTime, ForeignKey, String
from sqlalchemy.orm import Mapped, mapped_column

from msm.base import MarketsBase, MarketsTimeIndexMetaTableMixin
from msm.models.assets.core import AssetTable
from msm.settings import ASSET_IDENTIFIER_DIMENSION


class AssetSnapshotsStorage(MarketsTimeIndexMetaTableMixin, MarketsBase):
    """Timestamped asset display snapshots keyed by asset unique identifier."""

    __metatable_identifier__ = "AssetSnapshotsTS"
    __metatable_description__ = (
        "Timestamped asset display-fact storage keyed by (time_index, "
        "asset_identifier). Used by the AssetSnapshot DataNode to publish "
        "historical asset names, tickers, exchange codes, and share-class grouping "
        "without widening AssetTable."
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
    name: Mapped[str | None] = mapped_column(
        String,
        nullable=True,
        info={
            "label": "Name",
            "description": "Security name as recorded by the asset data provider.",
        },
    )
    ticker: Mapped[str | None] = mapped_column(
        String,
        nullable=True,
        info={"label": "Ticker", "description": "Ticker or display symbol for the asset row."},
    )
    exchange_code: Mapped[str | None] = mapped_column(
        String,
        nullable=True,
        info={
            "label": "Exchange Code",
            "description": "Exchange or market code for the asset row.",
        },
    )
    asset_ticker_group_id: Mapped[str | None] = mapped_column(
        String,
        nullable=True,
        info={
            "label": "Asset Ticker Group ID",
            "description": "Highest aggregation level for share-class grouping.",
        },
    )


__all__ = ["AssetSnapshotsStorage"]
