from __future__ import annotations

import uuid

from sqlalchemy import ForeignKey, Index, String
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.types import Uuid

from msm.base import (
    MarketsBase,
    MarketsMetaTableMixin,
    markets_table_args,
    new_markets_uid,
)

from msm.models.indices import IndexTable
from msm.models.calendars import CalendarTable
from msm.models.portfolios.signals import SignalMetadataTable


class PortfolioTable(MarketsMetaTableMixin, MarketsBase):
    """Portfolio identity and relational configuration metadata."""

    __metatable_identifier__ = "Portfolio"
    __metatable_description__ = (
        "Portfolio identity and configuration table keyed by unique_identifier. "
        "Stores required calendar linkage, optional published index linkage, and DataNode "
        "pointers used to publish portfolio weights, signals, and values."
    )
    __table_args__ = markets_table_args(
        __metatable_identifier__,
        Index(
            None,
            "unique_identifier",
            unique=True,
        ),
        Index(
            None,
            "calendar_uid",
        ),
        Index(
            None,
            "published_index_uid",
        ),
        Index(
            None,
            "signal_uid",
        ),
    )

    uid: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True),
        primary_key=True,
        default=new_markets_uid,
        info={
            "label": "UID",
            "description": "Canonical UUID primary key for this MetaTable row.",
        },
    )
    unique_identifier: Mapped[str] = mapped_column(
        String(255),
        nullable=False,
        info={
            "label": "Unique Identifier",
            "description": "Stable business identifier used for idempotent upserts, lookup, and joins.",
        },
    )
    calendar_uid: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey(
            f"{CalendarTable.__table__.fullname}.uid",
            ondelete="RESTRICT",
        ),
        nullable=False,
        info={
            "label": "Calendar UID",
            "description": "CalendarTable.uid for the persisted calendar used to schedule this portfolio.",
        },
    )
    published_index_uid: Mapped[uuid.UUID | None] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey(
            f"{IndexTable.__table__.fullname}.uid",
            ondelete="SET NULL",
        ),
        nullable=True,
        info={
            "label": "Published Index UID",
            "description": (
                "Optional IndexTable.uid used when this portfolio is published as "
                "an index-like observable. Core portfolio weights and values use "
                "PortfolioTable identity instead."
            ),
        },
    )
    portfolio_weights_data_node_uid: Mapped[uuid.UUID | None] = mapped_column(
        Uuid(as_uuid=True),
        nullable=True,
        info={
            "label": "Portfolio Weights Data Node UID",
            "description": "Platform DataNodeUpdate.uid for the portfolio weights producer.",
        },
    )
    signal_weights_data_node_uid: Mapped[uuid.UUID | None] = mapped_column(
        Uuid(as_uuid=True),
        nullable=True,
        info={
            "label": "Signal Weights Data Node UID",
            "description": "Platform DataNodeUpdate.uid for the signal weights producer.",
        },
    )
    signal_uid: Mapped[str | None] = mapped_column(
        String(255),
        ForeignKey(
            f"{SignalMetadataTable.__table__.fullname}.signal_uid",
            ondelete="RESTRICT",
        ),
        nullable=True,
        info={
            "label": "Signal UID",
            "description": (
                "Optional SignalMetadataTable.signal_uid for the signal currently "
                "used by this portfolio. Populated by portfolio workflow pointer "
                "updates after signal metadata has been persisted."
            ),
        },
    )
    portfolio_data_node_uid: Mapped[uuid.UUID | None] = mapped_column(
        Uuid(as_uuid=True),
        nullable=True,
        info={
            "label": "Portfolio Data Node UID",
            "description": "Platform DataNodeUpdate.uid for the portfolio-level data producer.",
        },
    )
    backtest_table_price_column_name: Mapped[str] = mapped_column(
        String(20),
        default="close",
        nullable=False,
        info={
            "label": "Backtest Table Price Column Name",
            "description": "Column name used as the portfolio backtest price field when reading price tables.",
        },
    )


__all__ = ["PortfolioTable"]
