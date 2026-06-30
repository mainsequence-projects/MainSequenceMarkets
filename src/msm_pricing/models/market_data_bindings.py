from __future__ import annotations

import uuid

from sqlalchemy import ForeignKey, Index, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.types import JSON, Uuid

from msm.base import (
    MarketsBase,
    MarketsMetaTableMixin,
    markets_table_args,
    new_markets_uid,
)

from .curves import CurveTable


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


class PricingMarketDataSetCurveBindingTable(MarketsMetaTableMixin, MarketsBase):
    """Binding from a market-data set valuation role to a curve identity."""

    __metatable_identifier__ = "PricingMarketDataSetCurveBinding"
    __metatable_description__ = (
        "Pricing market-data set curve binding keyed by market_data_set_uid and "
        "binding_key. Each row selects one CurveTable identity for a valuation "
        "role, selector type, selector key, and optional quote side within a "
        "pricing market-data set."
    )
    __table_args__ = markets_table_args(
        __metatable_identifier__,
        Index(
            None,
            "market_data_set_uid",
            "binding_key",
            unique=True,
        ),
        Index(
            None,
            "role_key",
        ),
        Index(
            None,
            "selector_type",
            "selector_key",
        ),
        Index(
            None,
            "quote_side",
        ),
        Index(
            None,
            "curve_uid",
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
            "description": "Canonical UUID primary key for this curve binding.",
        },
    )
    market_data_set_uid: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey(f"{PricingMarketDataSetTable.__table__.fullname}.uid", ondelete="CASCADE"),
        nullable=False,
        info={
            "label": "Market Data Set UID",
            "description": "PricingMarketDataSet UID that owns this curve binding.",
        },
    )
    binding_key: Mapped[str] = mapped_column(
        String(255),
        nullable=False,
        info={
            "label": "Binding Key",
            "description": (
                "Deterministic normalized key derived from role, selector, and quote side."
            ),
        },
    )
    role_key: Mapped[str] = mapped_column(
        String(64),
        nullable=False,
        info={
            "label": "Role Key",
            "description": "Valuation role, such as discount, projection, or z_spread_base.",
        },
    )
    selector_type: Mapped[str] = mapped_column(
        String(64),
        nullable=False,
        info={
            "label": "Selector Type",
            "description": "Selector domain, such as currency, index, global, asset, or issuer.",
        },
    )
    selector_key: Mapped[str] = mapped_column(
        String(255),
        nullable=False,
        info={
            "label": "Selector Key",
            "description": "Selector value within selector_type, such as USD or an IndexTable.uid.",
        },
    )
    quote_side: Mapped[str | None] = mapped_column(
        String(32),
        nullable=True,
        info={
            "label": "Quote Side",
            "description": "Optional quote side such as bid, mid, offer, official, or model.",
        },
    )
    curve_uid: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey(f"{CurveTable.__table__.fullname}.uid", ondelete="RESTRICT"),
        nullable=False,
        info={
            "label": "Curve UID",
            "description": "CurveTable UID selected by this market-data-set binding.",
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
    priority: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=0,
        info={
            "label": "Priority",
            "description": "Reserved integer priority for future explicit selection policies.",
        },
    )
    status: Mapped[str] = mapped_column(
        String(32),
        nullable=False,
        default="ACTIVE",
        info={
            "label": "Status",
            "description": "Operational status for selecting this curve binding.",
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
    "PricingMarketDataSetCurveBindingTable",
    "PricingMarketDataSetTable",
]
