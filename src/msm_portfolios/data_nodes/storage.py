"""Storage-first ``PlatformTimeIndexMetaTable`` declarations for msm portfolios.

ADR 0017. Each class is the single source of truth for the column schema,
dtypes, descriptions, and index names of one canonical portfolio table or
interpolated/external price node output. The DataNode validators derive their
column dtype maps from these declarations; catalog registration follows in
Stage 5.

Portfolio output tables use explicit storage identifier dimensions. Virtual-fund
allocation holdings declare canonical foreign keys to their owning
`VirtualFundTable` row, source account holdings set, and held
`AssetTable.unique_identifier`.
"""

from __future__ import annotations

import datetime
import uuid
from typing import ClassVar

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    Float,
    ForeignKey,
    SmallInteger,
    String,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.types import Uuid

from msm.base import MarketsBase, MarketsTimeIndexMetaTableMixin
from msm.models.accounts import AccountHoldingsSetTable
from msm.models.assets.core import AssetTable
from msm.settings import ASSET_IDENTIFIER_DIMENSION

from msm_portfolios.models.virtual_funds import VirtualFundHoldingsSetTable, VirtualFundTable

PORTFOLIO_IDENTIFIER_DIMENSION = "portfolio_identifier"
PORTFOLIO_INDEX_IDENTIFIER_DIMENSION = "portfolio_index_identifier"


class PortfolioWeightsStorage(MarketsTimeIndexMetaTableMixin, MarketsBase):
    """Executed portfolio weights keyed by portfolio index and held asset."""

    __metatable_identifier__ = "PortfolioWeightsTS"
    __metatable_description__ = (
        "Timestamped portfolio weight storage keyed by time_index, "
        "portfolio_index_identifier, and asset_identifier. Stores "
        "executed asset allocation weights and supporting price/volume facts."
    )
    __time_index_name__: ClassVar[str] = "time_index"
    __index_names__: ClassVar[list[str]] = [
        "time_index",
        PORTFOLIO_INDEX_IDENTIFIER_DIMENSION,
        ASSET_IDENTIFIER_DIMENSION,
    ]

    time_index: Mapped[datetime.datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        info={
            "label": "Time Index",
            "description": "UTC timestamp for the executed portfolio weight row.",
        },
    )
    portfolio_index_identifier: Mapped[str] = mapped_column(
        String,
        nullable=False,
        info={
            "label": "Portfolio Index Identifier",
            "description": (
                "Stable PortfolioIndex unique identifier for the portfolio that "
                "owns this executed weight row."
            ),
        },
    )
    asset_identifier: Mapped[str] = mapped_column(
        String,
        nullable=False,
        info={
            "label": "Asset Identifier",
            "description": "Asset unique identifier for the weighted instrument.",
        },
    )
    weight: Mapped[float | None] = mapped_column(
        Float,
        nullable=True,
        info={
            "label": "Weight",
            "description": "Executed/current allocation weight for this asset.",
        },
    )
    weight_before: Mapped[float | None] = mapped_column(
        Float,
        nullable=True,
        info={
            "label": "Weight Before",
            "description": "Allocation weight before the rebalance execution.",
        },
    )
    price_current: Mapped[float | None] = mapped_column(
        Float,
        nullable=True,
        info={
            "label": "Price Current",
            "description": "Asset price used for the current rebalance calculation.",
        },
    )
    price_before: Mapped[float | None] = mapped_column(
        Float,
        nullable=True,
        info={
            "label": "Price Before",
            "description": "Asset price from the previous rebalance reference.",
        },
    )
    volume_current: Mapped[float | None] = mapped_column(
        Float,
        nullable=True,
        info={
            "label": "Volume Current",
            "description": "Asset volume used for the current rebalance calculation.",
        },
    )
    volume_before: Mapped[float | None] = mapped_column(
        Float,
        nullable=True,
        info={
            "label": "Volume Before",
            "description": "Asset volume from the previous rebalance reference.",
        },
    )


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


class PortfoliosStorage(MarketsTimeIndexMetaTableMixin, MarketsBase):
    """Canonical portfolio value series keyed by portfolio unique identifier."""

    __metatable_identifier__ = "PortfoliosTS"
    __metatable_description__ = (
        "Timestamped portfolio value storage keyed by (time_index, "
        "portfolio_identifier). Stores close, return, calculated close, and close "
        "timestamp for canonical portfolio value series."
    )
    __time_index_name__: ClassVar[str] = "time_index"
    __index_names__: ClassVar[list[str]] = ["time_index", PORTFOLIO_IDENTIFIER_DIMENSION]

    time_index: Mapped[datetime.datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        info={"label": "Time Index", "description": "UTC timestamp for the portfolio value row."},
    )
    portfolio_identifier: Mapped[str] = mapped_column(
        String,
        nullable=False,
        info={
            "label": "Portfolio Identifier",
            "description": "Stable portfolio or portfolio-index unique identifier for the value series.",
        },
    )
    close: Mapped[float | None] = mapped_column(
        Float,
        nullable=True,
        info={
            "label": "Close",
            "description": "Published portfolio close value for the timestamp.",
        },
    )
    return_: Mapped[float | None] = mapped_column(
        "return",
        Float,
        nullable=True,
        info={"label": "Return", "description": "Portfolio period return for the timestamp."},
    )
    calculated_close: Mapped[float | None] = mapped_column(
        Float,
        nullable=True,
        info={
            "label": "Calculated Close",
            "description": "Internally calculated close before any price override.",
        },
    )
    close_time: Mapped[datetime.datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
        info={
            "label": "Close Time",
            "description": "UTC close timestamp represented by this portfolio value row.",
        },
    )


class InterpolatedPricesStorage(MarketsTimeIndexMetaTableMixin, MarketsBase):
    """Interpolated/upsampled OHLCV price bars keyed by asset unique identifier."""

    __metatable_identifier__ = "InterpolatedPricesTS"
    __metatable_description__ = (
        "Timestamped interpolated-price storage keyed by (time_index, "
        "asset_identifier). Stores OHLCV bars, VWAP, trade count, and interpolation "
        "flags for asset price feeds used by portfolio workflows."
    )
    __time_index_name__: ClassVar[str] = "time_index"
    __index_names__: ClassVar[list[str]] = ["time_index", ASSET_IDENTIFIER_DIMENSION]

    time_index: Mapped[datetime.datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        info={
            "label": "Time Index",
            "description": "UTC timestamp for the interpolated price bar.",
        },
    )
    asset_identifier: Mapped[str] = mapped_column(
        String,
        nullable=False,
        info={
            "label": "Asset Identifier",
            "description": "Asset unique identifier for the priced instrument.",
        },
    )
    open_time: Mapped[datetime.datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
        info={
            "label": "Open Time",
            "description": "UTC timestamp marking the start of the price bar.",
        },
    )
    open: Mapped[float | None] = mapped_column(
        Float,
        nullable=True,
        info={"label": "Open", "description": "Opening price for the bar."},
    )
    high: Mapped[float | None] = mapped_column(
        Float,
        nullable=True,
        info={"label": "High", "description": "Highest price during the bar."},
    )
    low: Mapped[float | None] = mapped_column(
        Float,
        nullable=True,
        info={"label": "Low", "description": "Lowest price during the bar."},
    )
    close: Mapped[float | None] = mapped_column(
        Float,
        nullable=True,
        info={"label": "Close", "description": "Closing price for the bar."},
    )
    volume: Mapped[float | None] = mapped_column(
        Float,
        nullable=True,
        info={"label": "Volume", "description": "Traded volume during the bar."},
    )
    trade_count: Mapped[float | None] = mapped_column(
        Float,
        nullable=True,
        info={"label": "Trade Count", "description": "Number of trades observed during the bar."},
    )
    vwap: Mapped[float | None] = mapped_column(
        Float,
        nullable=True,
        info={"label": "VWAP", "description": "Volume-weighted average price for the bar."},
    )
    interpolated: Mapped[bool | None] = mapped_column(
        Boolean,
        nullable=True,
        info={
            "label": "Interpolated",
            "description": "Whether the bar was synthetically interpolated.",
        },
    )


class VirtualFundHoldingsStorage(MarketsTimeIndexMetaTableMixin, MarketsBase):
    """Virtual-fund allocations keyed by virtual fund UID and held asset."""

    __metatable_identifier__ = "VirtualFundHoldingsTS"
    __metatable_description__ = (
        "Timestamped virtual-fund allocation storage keyed by (time_index, "
        "virtual_fund_uid, asset_identifier). Each row is a positive allocated "
        "quantity from a source account holdings set, with direction storing the "
        "long/short side."
    )
    __table_args__ = (
        CheckConstraint("direction IN (1, -1)", name="ck_virtual_fund_holdings_direction"),
    )
    __time_index_name__: ClassVar[str] = "time_index"
    __index_names__: ClassVar[list[str]] = [
        "time_index",
        "virtual_fund_uid",
        ASSET_IDENTIFIER_DIMENSION,
    ]

    time_index: Mapped[datetime.datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        info={
            "label": "Time Index",
            "description": (
                "UTC timestamp for the virtual-fund allocation snapshot. Rows with "
                "the same virtual_fund_uid and time_index belong to one allocation view."
            ),
        },
    )
    virtual_fund_uid: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey(
            f"{VirtualFundTable.__table__.fullname}.uid",
            ondelete="CASCADE",
        ),
        nullable=False,
        info={
            "label": "Virtual Fund UID",
            "description": (
                "Stable VirtualFundTable.uid that owns the allocation row. This "
                "dimension scopes allocation history to one virtual fund."
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
            "description": "Asset unique identifier for the allocated instrument.",
        },
    )
    virtual_fund_holdings_set_uid: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey(
            f"{VirtualFundHoldingsSetTable.__table__.fullname}.uid",
            ondelete="CASCADE",
        ),
        nullable=False,
        info={
            "label": "Virtual Fund Holdings Set UID",
            "description": "VirtualFundHoldingsSetTable.uid shared by rows in one allocation set.",
        },
    )
    source_account_holdings_set_uid: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey(
            f"{AccountHoldingsSetTable.__table__.fullname}.uid",
            ondelete="RESTRICT",
        ),
        nullable=False,
        info={
            "label": "Source Account Holdings Set UID",
            "description": "AccountHoldingsSetTable.uid that bounds this allocation row.",
        },
    )
    allocated_quantity: Mapped[float] = mapped_column(
        Float,
        nullable=False,
        info={
            "label": "Allocated Quantity",
            "description": "Positive source-account holdings magnitude allocated to this virtual fund.",
        },
    )
    direction: Mapped[int] = mapped_column(
        SmallInteger,
        default=1,
        nullable=False,
        info={
            "label": "Direction",
            "description": "Allocation side: 1 for long, -1 for short.",
        },
    )
    target_trade_time: Mapped[datetime.datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
        info={
            "label": "Target Trade Time",
            "description": (
                "Requested or expected execution time as a timezone-aware UTC datetime when provided."
            ),
        },
    )
    extra_details: Mapped[dict | None] = mapped_column(
        JSONB,
        nullable=True,
        info={
            "label": "Extra Details",
            "description": "JSONB payload for provider-specific holdings attributes.",
        },
    )


__all__ = [
    "InterpolatedPricesStorage",
    "PORTFOLIO_IDENTIFIER_DIMENSION",
    "PORTFOLIO_INDEX_IDENTIFIER_DIMENSION",
    "PortfolioWeightsStorage",
    "PortfoliosStorage",
    "SignalWeightsStorage",
    "VirtualFundHoldingsStorage",
]
