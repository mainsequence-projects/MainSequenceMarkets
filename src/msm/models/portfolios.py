from __future__ import annotations

import uuid

from sqlalchemy import ForeignKey, Index, String, Text
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.types import JSON, Uuid

from msm.base import (
    MarketsBase,
    MarketsMetaTableMixin,
    markets_fk_name,
    markets_index_name,
    markets_table_args,
    new_markets_uid,
)

from .assets import Asset


class Portfolio(MarketsMetaTableMixin, MarketsBase):
    """Portfolio identity and relational configuration metadata."""

    __metatable_identifier__ = "Portfolio"
    __table_args__ = markets_table_args(
        __metatable_identifier__,
        Index(
            markets_index_name(__metatable_identifier__, "unique_identifier", unique=True),
            "unique_identifier",
            unique=True,
        ),
        Index(
            markets_index_name(__metatable_identifier__, "calendar_name"),
            "calendar_name",
        ),
        Index(
            markets_index_name(__metatable_identifier__, "portfolio_index_asset_uid"),
            "portfolio_index_asset_uid",
        ),
    )

    uid: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True),
        primary_key=True,
        default=new_markets_uid,
    )
    unique_identifier: Mapped[str] = mapped_column(String(255), nullable=False)
    calendar_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    portfolio_index_asset_uid: Mapped[uuid.UUID | None] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey(
            f"{Asset.__table__.fullname}.uid",
            name=markets_fk_name(__metatable_identifier__, "Asset", "portfolio_index_asset_uid"),
            ondelete="SET NULL",
        ),
        nullable=True,
    )
    portfolio_index_asset_unique_identifier: Mapped[str | None] = mapped_column(
        String(255),
        nullable=True,
    )
    portfolio_weights_data_node_uid: Mapped[uuid.UUID | None] = mapped_column(
        Uuid(as_uuid=True),
        nullable=True,
    )
    signal_weights_data_node_uid: Mapped[uuid.UUID | None] = mapped_column(
        Uuid(as_uuid=True),
        nullable=True,
    )
    portfolio_data_node_uid: Mapped[uuid.UUID | None] = mapped_column(
        Uuid(as_uuid=True),
        nullable=True,
    )
    backtest_table_price_column_name: Mapped[str] = mapped_column(
        String(20),
        default="close",
        nullable=False,
    )
    builds_from_target_weights: Mapped[bool] = mapped_column(default=True, nullable=False)
    builds_from_predictions: Mapped[bool] = mapped_column(default=False, nullable=False)
    builds_from_target_positions: Mapped[bool] = mapped_column(default=False, nullable=False)
    tracking_funds_expected_exposure_from_latest_holdings: Mapped[bool] = mapped_column(
        default=False,
        nullable=False,
    )
    stats_json: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    metadata_json: Mapped[dict | None] = mapped_column(JSON, nullable=True)


class PortfolioAssetDetail(MarketsMetaTableMixin, MarketsBase):
    """Explicit portfolio-to-asset relation for portfolio index asset details."""

    __metatable_identifier__ = "PortfolioAssetDetail"
    __table_args__ = markets_table_args(
        __metatable_identifier__,
        Index(
            markets_index_name(__metatable_identifier__, "portfolio_uid", unique=True),
            "portfolio_uid",
            unique=True,
        ),
        Index(
            markets_index_name(__metatable_identifier__, "asset_uid"),
            "asset_uid",
        ),
    )

    uid: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True),
        primary_key=True,
        default=new_markets_uid,
    )
    portfolio_uid: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey(
            f"{Portfolio.__table__.fullname}.uid",
            name=markets_fk_name(__metatable_identifier__, "Portfolio", "portfolio_uid"),
            ondelete="CASCADE",
        ),
        nullable=False,
    )
    asset_uid: Mapped[uuid.UUID | None] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey(
            f"{Asset.__table__.fullname}.uid",
            name=markets_fk_name(__metatable_identifier__, "Asset", "asset_uid"),
            ondelete="SET NULL",
        ),
        nullable=True,
    )
    asset_unique_identifier: Mapped[str | None] = mapped_column(String(255), nullable=True)
    metadata_json: Mapped[dict | None] = mapped_column(JSON, nullable=True)


class PortfolioMetadata(MarketsMetaTableMixin, MarketsBase):
    """Human-facing portfolio metadata keyed by stable portfolio identifier."""

    __metatable_identifier__ = "PortfolioMetadata"
    __table_args__ = markets_table_args(
        __metatable_identifier__,
        Index(
            markets_index_name(__metatable_identifier__, "unique_identifier", unique=True),
            "unique_identifier",
            unique=True,
        ),
    )

    uid: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True),
        primary_key=True,
        default=new_markets_uid,
    )
    unique_identifier: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)


__all__ = ["Portfolio", "PortfolioAssetDetail", "PortfolioMetadata"]
