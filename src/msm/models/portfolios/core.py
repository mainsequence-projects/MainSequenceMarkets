from __future__ import annotations

import uuid

from mainsequence.meta_tables import MetaTableForeignKey
from sqlalchemy import Index, String
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.types import JSON, Uuid

from msm.base import (
    MarketsBase,
    MarketsMetaTableMixin,
    markets_index_name,
    markets_table_args,
    new_markets_uid,
)

from ..assets import AssetTable


class PortfolioTable(MarketsMetaTableMixin, MarketsBase):
    """Portfolio identity and relational configuration metadata."""

    __metatable_identifier__ = "Portfolio"
    __metatable_description__ = (
        "Portfolio identity and configuration table keyed by unique_identifier. "
        "Stores portfolio index asset linkage, DataNode pointers, construction "
        "flags, stats, and metadata."
    )
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
    calendar_name: Mapped[str | None] = mapped_column(
        String(255),
        nullable=True,
        info={
            "label": "Calendar Name",
            "description": "Calendar name used to resolve market sessions for this row.",
        },
    )
    portfolio_index_asset_uid: Mapped[uuid.UUID | None] = mapped_column(
        Uuid(as_uuid=True),
        MetaTableForeignKey(
            AssetTable,
            column="uid",
            ondelete="SET NULL",
        ),
        nullable=True,
        info={
            "label": "Portfolio Index Asset UID",
            "description": "AssetTable.uid for the synthetic asset representing the portfolio index.",
        },
    )
    portfolio_index_asset_unique_identifier: Mapped[str | None] = mapped_column(
        String(255),
        nullable=True,
        info={
            "label": "Portfolio Index Asset Unique Identifier",
            "description": "Asset unique identifier for the synthetic asset representing the portfolio index.",
        },
    )
    portfolio_weights_data_node_uid: Mapped[uuid.UUID | None] = mapped_column(
        Uuid(as_uuid=True),
        nullable=True,
        info={
            "label": "Portfolio Weights Data Node UID",
            "description": "Platform DataNode storage UID for portfolio weights history.",
        },
    )
    signal_weights_data_node_uid: Mapped[uuid.UUID | None] = mapped_column(
        Uuid(as_uuid=True),
        nullable=True,
        info={
            "label": "Signal Weights Data Node UID",
            "description": "Platform DataNode storage UID for signal weights history.",
        },
    )
    portfolio_data_node_uid: Mapped[uuid.UUID | None] = mapped_column(
        Uuid(as_uuid=True),
        nullable=True,
        info={
            "label": "Portfolio Data Node UID",
            "description": "Platform DataNode storage UID for portfolio-level historical data.",
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
    builds_from_target_weights: Mapped[bool] = mapped_column(
        default=True,
        nullable=False,
        info={
            "label": "Builds From Target Weights",
            "description": "Whether the portfolio construction workflow builds this portfolio from target weights.",
        },
    )
    builds_from_predictions: Mapped[bool] = mapped_column(
        default=False,
        nullable=False,
        info={
            "label": "Builds From Predictions",
            "description": "Whether the portfolio construction workflow builds this portfolio from prediction rows.",
        },
    )
    builds_from_target_positions: Mapped[bool] = mapped_column(
        default=False,
        nullable=False,
        info={
            "label": "Builds From Target Positions",
            "description": "Whether the portfolio construction workflow builds this portfolio from target positions.",
        },
    )
    tracking_funds_expected_exposure_from_latest_holdings: Mapped[bool] = mapped_column(
        default=False,
        nullable=False,
        info={
            "label": "Tracking Funds Expected Exposure From Latest Holdings",
            "description": "Whether tracking funds infer expected exposure from latest holdings.",
        },
    )
    stats_json: Mapped[dict | None] = mapped_column(
        JSON,
        nullable=True,
        info={
            "label": "Stats JSON",
            "description": "Structured portfolio statistics payload for analytics consumers.",
        },
    )
    metadata_json: Mapped[dict | None] = mapped_column(
        JSON,
        nullable=True,
        info={
            "label": "Metadata JSON",
            "description": "Structured metadata JSON for provider, application, or workflow-specific attributes.",
        },
    )


class PortfolioAssetDetailTable(MarketsMetaTableMixin, MarketsBase):
    """Explicit portfolio-to-asset relation for portfolio index asset details."""

    __metatable_identifier__ = "PortfolioAssetDetail"
    __metatable_description__ = (
        "Portfolio asset-detail relation keyed by portfolio_uid. Links a portfolio "
        "to its optional canonical asset row and asset unique_identifier metadata."
    )
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
        info={
            "label": "UID",
            "description": "Canonical UUID primary key for this MetaTable row.",
        },
    )
    portfolio_uid: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True),
        MetaTableForeignKey(
            PortfolioTable,
            column="uid",
            ondelete="CASCADE",
        ),
        nullable=False,
        info={
            "label": "Portfolio UID",
            "description": "Foreign key to PortfolioTable.uid for the referenced portfolio.",
        },
    )
    asset_uid: Mapped[uuid.UUID | None] = mapped_column(
        Uuid(as_uuid=True),
        MetaTableForeignKey(
            AssetTable,
            column="uid",
            ondelete="SET NULL",
        ),
        nullable=True,
        info={
            "label": "Asset UID",
            "description": "Foreign key to the canonical AssetTable.uid for the referenced asset.",
        },
    )
    asset_unique_identifier: Mapped[str | None] = mapped_column(
        String(255),
        nullable=True,
        info={
            "label": "Asset Unique Identifier",
            "description": "Stable AssetTable.unique_identifier value captured for provider payloads, joins, or denormalized display.",
        },
    )
    metadata_json: Mapped[dict | None] = mapped_column(
        JSON,
        nullable=True,
        info={
            "label": "Metadata JSON",
            "description": "Structured metadata JSON for provider, application, or workflow-specific attributes.",
        },
    )


__all__ = [
    "PortfolioAssetDetailTable",
    "PortfolioTable",
]
