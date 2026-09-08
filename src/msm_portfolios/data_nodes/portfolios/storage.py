"""Portfolio time-index-table output contracts."""

from __future__ import annotations

import datetime
from typing import ClassVar

from sqlalchemy import DateTime, Float, ForeignKey, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from msm.base import MarketsBase, MarketsTimeIndexMetaTableMixin
from msm.models.assets import AssetTable
from msm.models.calendars import CalendarTable
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
        String(255),
        ForeignKey(
            f"{PortfolioTable.__table__.fullname}.unique_identifier",
            ondelete="RESTRICT",
        ),
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
        String(255),
        ForeignKey(
            f"{AssetTable.__table__.fullname}.unique_identifier",
            ondelete="RESTRICT",
        ),
        nullable=False,
        info={
            "label": "Asset Identifier",
            "description": "AssetTable unique_identifier for the weighted instrument.",
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


class PortfolioCalendarEventsStorage(MarketsTimeIndexMetaTableMixin, MarketsBase):
    """Published calendar events that strategies may declare as observed inputs."""

    __metatable_identifier__ = "PortfolioCalendarEventsTS"
    __metatable_description__ = (
        "Persisted calendar session events projected onto their actual UTC open or "
        "close timestamps. Rows are keyed by time, calendar, session label, and event "
        "type for explicit use as a rebalance-strategy dependency."
    )
    __time_index_name__: ClassVar[str] = "time_index"
    __index_names__: ClassVar[list[str]] = [
        "time_index",
        "calendar_identifier",
        "session_label",
        "event_type",
    ]

    time_index: Mapped[datetime.datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        info={
            "label": "Calendar Event Time",
            "description": "Actual UTC timestamp of the persisted session open or close.",
        },
    )
    calendar_identifier: Mapped[str] = mapped_column(
        String(255),
        ForeignKey(
            f"{CalendarTable.__table__.fullname}.unique_identifier",
            ondelete="RESTRICT",
        ),
        nullable=False,
        info={
            "label": "Calendar Identifier",
            "description": "CalendarTable unique_identifier that owns this session event.",
        },
    )
    session_label: Mapped[str] = mapped_column(
        String(64),
        nullable=False,
        info={
            "label": "Session Label",
            "description": "Persisted session category from which this event was projected.",
        },
    )
    event_type: Mapped[str] = mapped_column(
        String(32),
        nullable=False,
        info={
            "label": "Event Type",
            "description": "Session boundary represented by the row: market_open or market_close.",
        },
    )
    local_date: Mapped[str] = mapped_column(
        String(10),
        nullable=False,
        info={
            "label": "Local Session Date",
            "description": "Calendar-local ISO date used for weekly event selection.",
        },
    )


class PortfolioRebalanceStateStorage(MarketsTimeIndexMetaTableMixin, MarketsBase):
    """Auditable rebalance intent and execution progress by portfolio asset."""

    __metatable_identifier__ = "PortfolioRebalanceStateTS"
    __metatable_description__ = (
        "Event-driven portfolio rebalance state keyed by event timestamp, portfolio, "
        "target intent, and asset. Rows record target activation, partial execution, "
        "remaining weight, observed execution capacity, and strategy-owned restart state."
    )
    __time_index_name__: ClassVar[str] = "time_index"
    __index_names__: ClassVar[list[str]] = [
        "time_index",
        PORTFOLIO_IDENTIFIER_DIMENSION,
        "rebalance_intent_id",
        ASSET_IDENTIFIER_DIMENSION,
    ]

    time_index: Mapped[datetime.datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        info={
            "label": "Execution Event Time",
            "description": (
                "UTC timestamp of the observed event that caused this state transition."
            ),
        },
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
            "description": (
                "Stable PortfolioTable unique_identifier for the rebalance state machine."
            ),
        },
    )
    rebalance_intent_id: Mapped[str] = mapped_column(
        String(64),
        nullable=False,
        info={
            "label": "Rebalance Intent ID",
            "description": (
                "Deterministic hash of the selected signal timestamp and target weights."
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
            "description": "AssetTable unique_identifier whose target progress is recorded.",
        },
    )
    target_signal_time_index: Mapped[datetime.datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        info={
            "label": "Target Signal Time",
            "description": (
                "UTC observation timestamp of the signal target active for this transition."
            ),
        },
    )
    event_source: Mapped[str] = mapped_column(
        String(255),
        nullable=False,
        info={
            "label": "Event Source",
            "description": (
                "Declared strategy input whose observed timestamp triggered the transition."
            ),
        },
    )
    execution_status: Mapped[str] = mapped_column(
        String(32),
        nullable=False,
        info={
            "label": "Execution Status",
            "description": (
                "Lifecycle state: pending, partial, complete, superseded, cancelled, or rejected."
            ),
        },
    )
    target_weight: Mapped[float] = mapped_column(
        Float,
        nullable=False,
        info={
            "label": "Target Weight",
            "description": "Signal target weight selected for this asset and intent.",
        },
    )
    weight_before: Mapped[float] = mapped_column(
        Float,
        nullable=False,
        info={
            "label": "Weight Before",
            "description": "Executed portfolio weight immediately before this transition.",
        },
    )
    weight_after: Mapped[float] = mapped_column(
        Float,
        nullable=False,
        info={
            "label": "Weight After",
            "description": "Executed portfolio weight immediately after this transition.",
        },
    )
    executed_weight_delta: Mapped[float] = mapped_column(
        Float,
        nullable=False,
        info={
            "label": "Executed Weight Delta",
            "description": "Signed weight change executed at this observed event.",
        },
    )
    remaining_weight_delta: Mapped[float] = mapped_column(
        Float,
        nullable=False,
        info={
            "label": "Remaining Weight Delta",
            "description": "Signed target weight still unexecuted after this transition.",
        },
    )
    execution_price: Mapped[float | None] = mapped_column(
        Float,
        nullable=True,
        info={
            "label": "Execution Price",
            "description": "Observed price used by the strategy for this asset transition.",
        },
    )
    executed_quantity: Mapped[float | None] = mapped_column(
        Float,
        nullable=True,
        info={
            "label": "Executed Quantity",
            "description": "Signed asset quantity implied or reported for this transition.",
        },
    )
    executed_notional: Mapped[float | None] = mapped_column(
        Float,
        nullable=True,
        info={
            "label": "Executed Notional",
            "description": "Absolute notional capacity consumed by this asset transition.",
        },
    )
    observed_volume: Mapped[float | None] = mapped_column(
        Float,
        nullable=True,
        info={
            "label": "Observed Volume",
            "description": "Source bar volume observed by a volume-aware strategy.",
        },
    )
    observed_available_liquidity: Mapped[float | None] = mapped_column(
        Float,
        nullable=True,
        info={
            "label": "Observed Available Liquidity",
            "description": "Source liquidity capacity observed by a liquidity-aware strategy.",
        },
    )
    strategy_state: Mapped[str] = mapped_column(
        Text,
        nullable=False,
        info={
            "label": "Strategy State",
            "description": (
                "Versioned JSON state owned by the strategy and used for deterministic restart."
            ),
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


class PortfolioAnalyticsStorage(MarketsTimeIndexMetaTableMixin, MarketsBase):
    """Derived portfolio observations with explicit period and source lineage."""

    __metatable_identifier__ = "PortfolioAnalyticsTS"
    __metatable_description__ = (
        "Derived portfolio analytics keyed by time_index, portfolio_identifier, "
        "and analysis_identifier. Each time_index is the actual final canonical "
        "portfolio observation selected for the analytical period."
    )
    __time_index_name__: ClassVar[str] = "time_index"
    __index_names__: ClassVar[list[str]] = [
        "time_index",
        PORTFOLIO_IDENTIFIER_DIMENSION,
        "analysis_identifier",
    ]

    time_index: Mapped[datetime.datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        info={
            "label": "Time Index",
            "description": "Actual canonical portfolio observation selected for this period.",
        },
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
            "description": "Stable PortfolioTable identifier for the analyzed value series.",
        },
    )
    analysis_identifier: Mapped[str] = mapped_column(
        String(255),
        nullable=False,
        info={
            "label": "Analysis Identifier",
            "description": "Hash identity of the frequency, timezone, and aggregation contract.",
        },
    )
    close: Mapped[float | None] = mapped_column(
        Float,
        nullable=True,
        info={
            "label": "Close",
            "description": "Last canonical portfolio close selected in the analytical period.",
        },
    )
    return_: Mapped[float | None] = mapped_column(
        "return",
        Float,
        nullable=True,
        info={
            "label": "Return",
            "description": "Return between consecutive derived analytical observations.",
        },
    )
    source_time_index: Mapped[datetime.datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        info={
            "label": "Source Time Index",
            "description": "Canonical portfolio observation timestamp selected for this row.",
        },
    )
    period_start: Mapped[datetime.datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        info={
            "label": "Period Start",
            "description": "Configured analytical bucket start, distinct from time_index.",
        },
    )
    period_end: Mapped[datetime.datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        info={
            "label": "Period End",
            "description": "Configured analytical bucket end, distinct from time_index.",
        },
    )


__all__ = [
    "PORTFOLIO_IDENTIFIER_DIMENSION",
    "PortfolioAnalyticsStorage",
    "PortfolioCalendarEventsStorage",
    "PortfolioRebalanceStateStorage",
    "PortfolioWeightsStorage",
    "PortfoliosStorage",
]
