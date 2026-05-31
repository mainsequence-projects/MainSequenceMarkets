"""Storage-first ``PlatformTimeIndexMetaData`` declarations for msm portfolios.

ADR 0017. Each class is the single source of truth for the column schema,
dtypes, descriptions, and index names of one canonical portfolio table or
interpolated/external price node output. The DataNode validators derive their
column dtype maps from these declarations; catalog registration follows in
Stage 5.

Portfolio outputs carry no identity foreign keys (only
AssetSnapshot/curve/index/fixings nodes declare canonical FKs), so these
storage classes declare none.
"""

from __future__ import annotations

import datetime
from typing import Any, ClassVar

from sqlalchemy import Boolean, DateTime, Float, String
from sqlalchemy.orm import Mapped, mapped_column

from msm.base import MarketsBase, MarketsTimeIndexMetaTableMixin


class PortfolioWeightsStorage(MarketsTimeIndexMetaTableMixin, MarketsBase):
    """Executed portfolio weights keyed by portfolio index asset and held asset."""

    __markets_base_identifier__: ClassVar[str] = "portfolio_weights"
    __metatable_extra_hash_components__: ClassVar[dict[str, Any]] = {
        "storage_name": "portfolio_weights",
    }
    __time_index_name__: ClassVar[str] = "time_index"
    __index_names__: ClassVar[list[str]] = [
        "time_index",
        "portfolio_index_asset_unique_identifier",
        "unique_identifier",
    ]

    time_index: Mapped[datetime.datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        info={"label": "Time Index", "description": "UTC timestamp for the executed portfolio weight row."},
    )
    portfolio_index_asset_unique_identifier: Mapped[str] = mapped_column(
        String,
        nullable=False,
        info={
            "label": "Portfolio Index Asset Unique Identifier",
            "description": (
                "Stable PortfolioIndexAsset unique identifier for the portfolio that "
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
        info={"label": "Weight", "description": "Executed/current allocation weight for this asset."},
    )
    weight_before: Mapped[float | None] = mapped_column(
        Float,
        nullable=True,
        info={"label": "Weight Before", "description": "Allocation weight before the rebalance execution."},
    )
    price_current: Mapped[float | None] = mapped_column(
        Float,
        nullable=True,
        info={"label": "Price Current", "description": "Asset price used for the current rebalance calculation."},
    )
    price_before: Mapped[float | None] = mapped_column(
        Float,
        nullable=True,
        info={"label": "Price Before", "description": "Asset price from the previous rebalance reference."},
    )
    volume_current: Mapped[float | None] = mapped_column(
        Float,
        nullable=True,
        info={"label": "Volume Current", "description": "Asset volume used for the current rebalance calculation."},
    )
    volume_before: Mapped[float | None] = mapped_column(
        Float,
        nullable=True,
        info={"label": "Volume Before", "description": "Asset volume from the previous rebalance reference."},
    )


class SignalWeightsStorage(MarketsTimeIndexMetaTableMixin, MarketsBase):
    """Raw signal weights keyed by signal UID and signaled asset."""

    __markets_base_identifier__: ClassVar[str] = "signal_weights"
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
    """Canonical portfolio value series keyed by portfolio asset unique identifier."""

    __markets_base_identifier__: ClassVar[str] = "portfolios"
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
            "description": "Stable asset unique identifier for the portfolio value series.",
        },
    )
    close: Mapped[float | None] = mapped_column(
        Float,
        nullable=True,
        info={"label": "Close", "description": "Published portfolio close value."},
    )
    return_: Mapped[float | None] = mapped_column(
        "return",
        Float,
        nullable=True,
        info={"label": "Return", "description": "Portfolio period return."},
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
    __metatable_extra_hash_components__: ClassVar[dict[str, Any]] = {
        "storage_name": "interpolated_prices",
    }
    __time_index_name__: ClassVar[str] = "time_index"
    __index_names__: ClassVar[list[str]] = ["time_index", "unique_identifier"]

    time_index: Mapped[datetime.datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        info={"label": "Time Index", "description": "UTC timestamp for the interpolated price bar."},
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
        info={"label": "Open Time", "description": "UTC timestamp marking the start of the price bar."},
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
        info={"label": "Interpolated", "description": "Whether the bar was synthetically interpolated."},
    )


class ExternalPricesStorage(MarketsTimeIndexMetaTableMixin, MarketsBase):
    """External provider price observations keyed by asset unique identifier."""

    __markets_base_identifier__: ClassVar[str] = "external_prices"
    __metatable_extra_hash_components__: ClassVar[dict[str, Any]] = {
        "storage_name": "external_prices",
    }
    __time_index_name__: ClassVar[str] = "time_index"
    __index_names__: ClassVar[list[str]] = ["time_index", "unique_identifier"]

    time_index: Mapped[datetime.datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        info={"label": "Time Index", "description": "UTC timestamp for the external price observation."},
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
        info={"label": "Open", "description": "External price observation mapped to the open field."},
    )


__all__ = [
    "ExternalPricesStorage",
    "InterpolatedPricesStorage",
    "PortfolioWeightsStorage",
    "PortfoliosStorage",
    "SignalWeightsStorage",
]
