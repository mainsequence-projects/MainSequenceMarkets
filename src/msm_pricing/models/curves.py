from __future__ import annotations

import uuid

from sqlalchemy import ForeignKey, Index, String
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.types import JSON, Uuid

from msm.base import (
    MarketsBase,
    MarketsMetaTableMixin,
    markets_table_args,
    new_markets_uid,
)

from .index_convention_details import IndexConventionDetailsTable


class CurveTable(MarketsMetaTableMixin, MarketsBase):
    """Pricing-owned curve identity linked to index convention details."""

    __metatable_identifier__ = "Curve"
    __metatable_description__ = (
        "Pricing curve registry keyed by unique_identifier. Links each curve to "
        "index convention details and stores curve type, interpolation, compounding, "
        "source, and metadata used by pricing resolvers."
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
            "index_uid",
        ),
        Index(
            None,
            "curve_type",
        ),
        Index(
            None,
            "source",
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
    index_uid: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey(
            f"{IndexConventionDetailsTable.__table__.fullname}.index_uid",
            ondelete="RESTRICT",
        ),
        nullable=False,
        info={
            "label": "Index UID",
            "description": "Foreign key to the canonical index or index convention row used by pricing.",
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
