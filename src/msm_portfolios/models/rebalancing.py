from __future__ import annotations

import uuid

from sqlalchemy import Index, String, Text
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.types import JSON, Uuid

from msm.base import (
    MarketsBase,
    MarketsMetaTableMixin,
    markets_index_name,
    markets_table_args,
    new_markets_uid,
)


class RebalanceStrategyMetadataTable(MarketsMetaTableMixin, MarketsBase):
    """Metadata row for a canonical portfolios rebalance strategy."""

    __metatable_identifier__ = "RebalanceStrategyMetadata"
    __metatable_description__ = (
        "Rebalance strategy metadata table keyed by rebalance_strategy_uid. Stores "
        "descriptions and configuration payloads for canonical portfolio rebalance "
        "strategies."
    )
    __table_args__ = markets_table_args(
        __metatable_identifier__,
        Index(
            markets_index_name(
                __metatable_identifier__,
                "rebalance_strategy_uid",
                unique=True,
            ),
            "rebalance_strategy_uid",
            unique=True,
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
    rebalance_strategy_uid: Mapped[str] = mapped_column(
        String(255),
        nullable=False,
        info={
            "label": "Rebalance Strategy UID",
            "description": "Stable unique identifier for the rebalance strategy definition.",
        },
    )
    rebalance_strategy_description: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
        info={
            "label": "Rebalance Strategy Description",
            "description": "Human-readable description of the rebalance strategy.",
        },
    )
    configuration_json: Mapped[dict | None] = mapped_column(
        JSON,
        nullable=True,
        info={
            "label": "Configuration JSON",
            "description": "Structured rebalance strategy configuration payload.",
        },
    )


__all__ = ["RebalanceStrategyMetadataTable"]
