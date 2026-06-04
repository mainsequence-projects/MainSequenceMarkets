from __future__ import annotations

import uuid

from sqlalchemy import Index, String
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.types import JSON, Uuid

from msm.base import (
    MarketsBase,
    MarketsMetaTableMixin,
    markets_table_args,
    new_markets_uid,
)


class PricingMarketDataBindingTable(MarketsMetaTableMixin, MarketsBase):
    """Pricing-owned binding from a context/concept pair to a DataNode identifier."""

    __metatable_identifier__ = "PricingMarketDataBinding"
    __metatable_description__ = (
        "Pricing market-data binding table keyed by context_key and concept_key. "
        "Resolves pricing concepts such as discount curves or interest-rate index "
        "fixings to DataNode identifiers for a named pricing context."
    )
    __table_args__ = markets_table_args(
        __metatable_identifier__,
        Index(
            None,
            "context_key",
            "concept_key",
            unique=True,
        ),
        Index(
            None,
            "context_key",
        ),
        Index(
            None,
            "concept_key",
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
    context_key: Mapped[str] = mapped_column(
        String(64),
        nullable=False,
        info={
            "label": "Context Key",
            "description": "Named pricing context key, such as default, eod, live, or risk_manager.",
        },
    )
    concept_key: Mapped[str] = mapped_column(
        String(128),
        nullable=False,
        info={
            "label": "Concept Key",
            "description": "Pricing market-data concept key, such as discount curves or index fixings.",
        },
    )
    data_node_identifier: Mapped[str] = mapped_column(
        String(255),
        nullable=False,
        info={
            "label": "Data Node Identifier",
            "description": "Stable DataNode identifier used to resolve a configured market-data source.",
        },
    )
    source: Mapped[str | None] = mapped_column(
        String(255),
        nullable=True,
        info={
            "label": "Source",
            "description": "Source system, workflow, or provider that produced the row.",
        },
    )
    metadata_json: Mapped[dict | None] = mapped_column(
        "metadata",
        JSON,
        nullable=True,
        info={
            "label": "Metadata",
            "description": "Structured metadata JSON for provider, pricing, or workflow-specific attributes.",
        },
    )


__all__ = ["PricingMarketDataBindingTable"]
