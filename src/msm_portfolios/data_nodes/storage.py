"""Storage-first ``PlatformTimeIndexMetaData`` declarations for msm portfolios.

ADR 0017. Each class is the single source of truth for the column schema,
dtypes, descriptions, and index names of one canonical portfolio table or
interpolated/external price node output. The DataNode validators derive their
column dtype maps from these declarations; catalog registration follows in
Stage 5.

Portfolio output tables use logical asset identifiers. Virtual-fund holdings
also declare canonical foreign keys to their owning `FundTable` row and held
`AssetTable.unique_identifier`.
"""

from __future__ import annotations

import datetime
import uuid
from typing import Any, ClassVar

from mainsequence.meta_tables import MetaTableForeignKey
from sqlalchemy import Boolean, DateTime, Float, String
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.types import Uuid

from msm.base import MarketsBase, MarketsTimeIndexMetaTableMixin
from msm.models.assets.core import AssetTable

from msm_portfolios.models.virtual_funds import FundTable


class PortfolioWeightsStorage(MarketsTimeIndexMetaTableMixin, MarketsBase):
    """Executed portfolio weights keyed by portfolio index and held asset."""

    __markets_base_identifier__: ClassVar[str] = "portfolio_weights"
    __metatable_description__ = (
        "Timestamped portfolio weight storage keyed by time_index, "
        "portfolio_index_unique_identifier, and unique_identifier. Stores "
        "executed asset allocation weights and supporting price/volume facts."
    )
    __metatable_extra_hash_components__: ClassVar[dict[str, Any]] = {
        "storage_name": "portfolio_weights",
    }
    __time_index_name__: ClassVar[str] = "time_index"
    __index_names__: ClassVar[list[str]] = [
        "time_index",
        "portfolio_index_unique_identifier",
        "unique_identifier",
    ]

    time_index: Mapped[datetime.datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        info={
            "label": "Time Index",
            "description": "UTC timestamp for the executed portfolio weight row.",
        },
    )
    portfolio_index_unique_identifier: Mapped[str] = mapped_column(
        String,
        nullable=False,
        info={
            "label": "Portfolio Index Unique Identifier",
            "description": (
                "Stable PortfolioIndex unique identifier for the portfolio that "
                "owns this executed weight row."
            ),
        },
    )
    unique_identifier: Mapped[str] = mapped_column(
        String,
        nullable=False,
        info={
            "label": "Unique Identifier",
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

    __markets_base_identifier__: ClassVar[str] = "signal_weights"
    __metatable_description__ = (
        "Timestamped signal weight storage keyed by (time_index, signal_uid, "
        "unique_identifier). Stores raw signal allocation weights for signaled "
        "assets before portfolio execution."
    )
    __metatable_extra_hash_components__: ClassVar[dict[str, Any]] = {
        "storage_name": "signal_weights",
    }
    __time_index_name__: ClassVar[str] = "time_index"
    __index_names__: ClassVar[list[str]] = ["time_index", "signal_uid", "unique_identifier"]

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
    unique_identifier: Mapped[str] = mapped_column(
        String,
        nullable=False,
        info={
            "label": "Unique Identifier",
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

    __markets_base_identifier__: ClassVar[str] = "portfolios"
    __metatable_description__ = (
        "Timestamped portfolio value storage keyed by (time_index, "
        "unique_identifier). Stores close, return, calculated close, and close "
        "timestamp for canonical portfolio value series."
    )
    __metatable_extra_hash_components__: ClassVar[dict[str, Any]] = {
        "storage_name": "portfolios",
    }
    __time_index_name__: ClassVar[str] = "time_index"
    __index_names__: ClassVar[list[str]] = ["time_index", "unique_identifier"]

    time_index: Mapped[datetime.datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        info={"label": "Time Index", "description": "UTC timestamp for the portfolio value row."},
    )
    unique_identifier: Mapped[str] = mapped_column(
        String,
        nullable=False,
        info={
            "label": "Unique Identifier",
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

    __markets_base_identifier__: ClassVar[str] = "interpolated_prices"
    __metatable_description__ = (
        "Timestamped interpolated-price storage keyed by (time_index, "
        "unique_identifier). Stores OHLCV bars, VWAP, trade count, and interpolation "
        "flags for asset price feeds used by portfolio workflows."
    )
    __metatable_extra_hash_components__: ClassVar[dict[str, Any]] = {
        "storage_name": "interpolated_prices",
    }
    __time_index_name__: ClassVar[str] = "time_index"
    __index_names__: ClassVar[list[str]] = ["time_index", "unique_identifier"]

    time_index: Mapped[datetime.datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        info={
            "label": "Time Index",
            "description": "UTC timestamp for the interpolated price bar.",
        },
    )
    unique_identifier: Mapped[str] = mapped_column(
        String,
        nullable=False,
        info={
            "label": "Unique Identifier",
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


class ExternalPricesStorage(MarketsTimeIndexMetaTableMixin, MarketsBase):
    """External provider price observations keyed by asset unique identifier."""

    __markets_base_identifier__: ClassVar[str] = "external_prices"
    __metatable_description__ = (
        "Timestamped external-price storage keyed by (time_index, "
        "unique_identifier). Stores provider-supplied price observations for assets "
        "when external pricing data is injected into portfolio workflows."
    )
    __metatable_extra_hash_components__: ClassVar[dict[str, Any]] = {
        "storage_name": "external_prices",
    }
    __time_index_name__: ClassVar[str] = "time_index"
    __index_names__: ClassVar[list[str]] = ["time_index", "unique_identifier"]

    time_index: Mapped[datetime.datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        info={
            "label": "Time Index",
            "description": "UTC timestamp for the external price observation.",
        },
    )
    unique_identifier: Mapped[str] = mapped_column(
        String,
        nullable=False,
        info={
            "label": "Unique Identifier",
            "description": "Asset unique identifier for the priced instrument.",
        },
    )
    open: Mapped[float | None] = mapped_column(
        Float,
        nullable=True,
        info={
            "label": "Open",
            "description": "External price observation mapped to the open field.",
        },
    )


class FundHoldingsStorage(MarketsTimeIndexMetaTableMixin, MarketsBase):
    """Fund historical holdings keyed by fund UID and held asset."""

    __markets_base_identifier__: ClassVar[str] = "virtual_fund_historical_holdings"
    __metatable_description__ = (
        "Timestamped virtual-fund holdings storage keyed by (time_index, fund_uid, "
        "unique_identifier). Each row is one asset position in a fund holdings "
        "observation, including target weights, trade timing, and provider metadata "
        "when available."
    )
    __metatable_extra_hash_components__: ClassVar[dict[str, Any]] = {
        "storage_name": "virtual_fund_historical_holdings",
    }
    __time_index_name__: ClassVar[str] = "time_index"
    __index_names__: ClassVar[list[str]] = ["time_index", "fund_uid", "unique_identifier"]

    time_index: Mapped[datetime.datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        info={
            "label": "Time Index",
            "description": (
                "UTC timestamp for the fund holdings snapshot. Rows with the same "
                "fund_uid and time_index belong to the same fund observation."
            ),
        },
    )
    fund_uid: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True),
        MetaTableForeignKey(
            FundTable,
            column="uid",
            ondelete="RESTRICT",
        ),
        nullable=False,
        info={
            "label": "Fund UID",
            "description": (
                "Stable Fund UID that owns the holdings row. This dimension scopes "
                "holdings history to one fund."
            ),
        },
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
            "description": "Asset unique identifier for the held instrument at this fund timestamp.",
        },
    )
    holdings_set_uid: Mapped[uuid.UUID | None] = mapped_column(
        Uuid(as_uuid=True),
        nullable=True,
        info={
            "label": "Holdings Set UID",
            "description": "Stable UUID shared by rows written together as one fund holdings set.",
        },
    )
    is_trade_snapshot: Mapped[bool | None] = mapped_column(
        Boolean,
        nullable=True,
        info={
            "label": "Is Trade Snapshot",
            "description": "Whether the holdings row belongs to an execution or trade snapshot.",
        },
    )
    quantity: Mapped[float | None] = mapped_column(
        Float,
        nullable=True,
        info={
            "label": "Quantity",
            "description": "Position quantity held for this asset in the fund snapshot.",
        },
    )
    target_weight: Mapped[float | None] = mapped_column(
        Float,
        nullable=True,
        info={
            "label": "Target Weight",
            "description": "Target portfolio weight for this asset when available.",
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
    "ExternalPricesStorage",
    "FundHoldingsStorage",
    "InterpolatedPricesStorage",
    "PortfolioWeightsStorage",
    "PortfoliosStorage",
    "SignalWeightsStorage",
]
