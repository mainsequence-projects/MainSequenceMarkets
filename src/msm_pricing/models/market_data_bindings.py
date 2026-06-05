from __future__ import annotations

import uuid

from sqlalchemy import ForeignKey, Index, String, Text
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.types import JSON, Uuid

from msm.base import (
    MarketsBase,
    MarketsMetaTableMixin,
    markets_table_args,
    new_markets_uid,
)


class PricingMarketDataSetTable(MarketsMetaTableMixin, MarketsBase):
    """Named set of market-data sources used together by pricing workflows."""

    __metatable_identifier__ = "PricingMarketDataSet"
    __metatable_description__ = (
        "Pricing market-data set table keyed by set_key. Each row represents a "
        "named collection of market-data DataNode storage bindings, such as "
        "default, eod, live, or a stress scenario, used by pricing engines."
    )
    __table_args__ = markets_table_args(
        __metatable_identifier__,
        Index(
            None,
            "set_key",
            unique=True,
        ),
        Index(
            None,
            "status",
        ),
    )

    uid: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True),
        primary_key=True,
        default=new_markets_uid,
        info={
            "label": "UID",
            "description": "Canonical UUID primary key for this pricing market-data set.",
        },
    )
    set_key: Mapped[str] = mapped_column(
        String(64),
        nullable=False,
        info={
            "label": "Set Key",
            "description": (
                "User-facing key for this market-data set, such as default, eod, live, "
                "or a named stress scenario."
            ),
        },
    )
    display_name: Mapped[str] = mapped_column(
        String(255),
        nullable=False,
        info={
            "label": "Display Name",
            "description": "Human-readable name for this pricing market-data set.",
        },
    )
    description: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
        info={
            "label": "Description",
            "description": "Optional explanation of what source set or workflow this row represents.",
        },
    )
    status: Mapped[str] = mapped_column(
        String(32),
        nullable=False,
        default="ACTIVE",
        info={
            "label": "Status",
            "description": "Operational status for selecting this market-data set in pricing.",
        },
    )
    metadata_json: Mapped[dict | None] = mapped_column(
        "metadata",
        JSON,
        nullable=True,
        info={
            "label": "Metadata",
            "description": "Structured metadata JSON for provider, workflow, or scenario attributes.",
        },
    )


class PricingMarketDataSetBindingTable(MarketsMetaTableMixin, MarketsBase):
    """Binding from a market-data set and pricing concept to a DataNode storage UID."""

    __metatable_identifier__ = "PricingMarketDataSetBinding"
    __metatable_description__ = (
        "Pricing market-data set binding table keyed by market_data_set_uid and "
        "concept_key. Each row points one pricing concept, such as discount curves "
        "or interest-rate index fixings, to the backend storage table UID consumed "
        "by the pricing engine."
    )
    __table_args__ = markets_table_args(
        __metatable_identifier__,
        Index(
            None,
            "market_data_set_uid",
            "concept_key",
            unique=True,
        ),
        Index(
            None,
            "concept_key",
        ),
        Index(
            None,
            "data_node_uid",
        ),
    )

    uid: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True),
        primary_key=True,
        default=new_markets_uid,
        info={
            "label": "UID",
            "description": "Canonical UUID primary key for this market-data set binding.",
        },
    )
    market_data_set_uid: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey(f"{PricingMarketDataSetTable.__table__.fullname}.uid", ondelete="CASCADE"),
        nullable=False,
        info={
            "label": "Market Data Set UID",
            "description": "PricingMarketDataSet UID that owns this concept binding.",
        },
    )
    concept_key: Mapped[str] = mapped_column(
        String(128),
        nullable=False,
        info={
            "label": "Concept Key",
            "description": "Pricing market-data concept key, such as discount_curves.",
        },
    )
    data_node_uid: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True),
        nullable=False,
        info={
            "label": "DataNode Storage UID",
            "description": (
                "Backend MetaTable/TimeIndexMetaTable UID of the DataNode storage table "
                "used to resolve this pricing concept."
            ),
        },
    )
    storage_table_identifier: Mapped[str | None] = mapped_column(
        String(255),
        nullable=True,
        info={
            "label": "Storage Table Identifier",
            "description": (
                "Optional diagnostic copy of the storage table identifier. Pricing resolution "
                "uses data_node_uid, not this string."
            ),
        },
    )
    source: Mapped[str | None] = mapped_column(
        String(255),
        nullable=True,
        info={
            "label": "Source",
            "description": "Source system, workflow, or provider that produced the binding row.",
        },
    )
    metadata_json: Mapped[dict | None] = mapped_column(
        "metadata",
        JSON,
        nullable=True,
        info={
            "label": "Metadata",
            "description": "Structured metadata JSON for provider, pricing, or workflow attributes.",
        },
    )


__all__ = [
    "PricingMarketDataSetBindingTable",
    "PricingMarketDataSetTable",
]
