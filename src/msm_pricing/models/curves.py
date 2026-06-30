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


class CurveTable(MarketsMetaTableMixin, MarketsBase):
    """Pricing-owned curve registry identity."""

    __metatable_identifier__ = "Curve"
    __metatable_description__ = (
        "Pricing curve registry keyed by unique_identifier. Stores curve identity "
        "and high-level classification. Curve construction details and "
        "market-data-set selection policy live in dedicated pricing tables."
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
            "curve_type",
        ),
        Index(
            None,
            "currency_code",
        ),
        Index(
            None,
            "quote_side",
        ),
        Index(
            None,
            "source",
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
    display_name: Mapped[str] = mapped_column(
        String(255),
        nullable=False,
        info={
            "label": "Display Name",
            "description": "Human-readable display name for UI, logs, and operator workflows.",
        },
    )
    curve_type: Mapped[str] = mapped_column(
        String(64),
        nullable=False,
        info={
            "label": "Curve Type",
            "description": "Pricing curve type, such as discount, zero, forward, projection, or basis.",
        },
    )
    currency_code: Mapped[str | None] = mapped_column(
        String(16),
        nullable=True,
        info={
            "label": "Currency Code",
            "description": "Optional ISO currency or pricing currency code for this curve identity.",
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
    interpolation_method: Mapped[str | None] = mapped_column(
        String(64),
        nullable=True,
        info={
            "label": "Interpolation Method",
            "description": "Interpolation method used when reconstructing the pricing curve.",
        },
    )
    compounding: Mapped[str | None] = mapped_column(
        String(64),
        nullable=True,
        info={
            "label": "Compounding",
            "description": "Compounding convention used by a pricing curve resolver.",
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
    status: Mapped[str] = mapped_column(
        String(32),
        nullable=False,
        default="ACTIVE",
        info={
            "label": "Status",
            "description": "Operational status for selecting this curve in pricing workflows.",
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


__all__ = ["CurveTable"]
