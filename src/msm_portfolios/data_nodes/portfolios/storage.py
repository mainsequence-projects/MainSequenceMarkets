"""Portfolio DataNode storage contracts."""

from __future__ import annotations

import datetime
from typing import ClassVar

from sqlalchemy import DateTime, Float, ForeignKey, String
from sqlalchemy.orm import Mapped, mapped_column

from msm.base import MarketsBase, MarketsTimeIndexMetaTableMixin
from msm.models.portfolios import PortfolioTable
from msm.settings import ASSET_IDENTIFIER_DIMENSION
from msm_portfolios.data_nodes.constants import (
    PORTFOLIO_IDENTIFIER_DIMENSION,
)


class PortfolioWeightsStorage(MarketsTimeIndexMetaTableMixin, MarketsBase):
    """Executed portfolio weights keyed by portfolio identity and held asset."""

    __metatable_identifier__ = "PortfolioWeightsTS"
    __metatable_description__ = (
        "Timestamped portfolio weight storage keyed by time_index, "
        "portfolio_identifier, and asset_identifier. Stores "
        "executed asset allocation weights and supporting price/volume facts."
    )
    __time_index_name__: ClassVar[str] = "time_index"
    __index_names__: ClassVar[list[str]] = [
        "time_index",
        PORTFOLIO_IDENTIFIER_DIMENSION,
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
    portfolio_identifier: Mapped[str] = mapped_column(
        String,
        nullable=False,
        info={
            "label": "Portfolio Identifier",
            "description": (
                "Stable PortfolioTable unique_identifier for the portfolio that "
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
        String(255),
        ForeignKey(
            f"{PortfolioTable.__table__.fullname}.unique_identifier",
            ondelete="RESTRICT",
        ),
        nullable=False,
        info={
            "label": "Portfolio Identifier",
            "description": "Stable PortfolioTable unique_identifier for the value series.",
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


__all__ = [
    "PORTFOLIO_IDENTIFIER_DIMENSION",
    "PortfolioWeightsStorage",
    "PortfoliosStorage",
]
