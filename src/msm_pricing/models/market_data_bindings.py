from __future__ import annotations

import uuid

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
            markets_index_name(
                __metatable_identifier__,
                "context_key",
                "concept_key",
                unique=True,
            ),
            "context_key",
            "concept_key",
            unique=True,
        ),
        Index(
            markets_index_name(__metatable_identifier__, "context_key"),
            "context_key",
        ),
        Index(
            markets_index_name(__metatable_identifier__, "concept_key"),
            "concept_key",
        ),
    )

    uid: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True),
        primary_key=True,
        default=new_markets_uid,
    )
    context_key: Mapped[str] = mapped_column(String(64), nullable=False)
    concept_key: Mapped[str] = mapped_column(String(128), nullable=False)
    data_node_identifier: Mapped[str] = mapped_column(String(255), nullable=False)
    source: Mapped[str | None] = mapped_column(String(255), nullable=True)
    metadata_json: Mapped[dict | None] = mapped_column("metadata", JSON, nullable=True)


__all__ = ["PricingMarketDataBindingTable"]
