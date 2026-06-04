from __future__ import annotations

import datetime as dt
import uuid
from decimal import Decimal

from sqlalchemy import DateTime, ForeignKey, Index, Numeric, String
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.types import JSON, Uuid

from msm.base import (
    MarketsBase,
    MarketsMetaTableMixin,
    markets_table_args,
)

from .assets import AssetTable
from .indices import IndexTable


class FutureAssetDetailsTable(MarketsMetaTableMixin, MarketsBase):
    """Future contract detail row linked to a canonical markets asset."""

    __metatable_identifier__ = "FutureAssetDetails"
    __metatable_description__ = (
        "One-to-one future contract detail table keyed by AssetTable.uid. Links a "
        "future asset to its underlying Index, settlement and margin assets, "
        "contract terms, expiry, and metadata."
    )
    __table_args__ = markets_table_args(
        __metatable_identifier__,
        Index(
            None,
            "underlying_index_uid",
        ),
        Index(
            None,
            "settlement_asset",
        ),
        Index(
            None,
            "margin_asset",
        ),
        Index(
            None,
            "expires_at",
        ),
    )

    asset_uid: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey(
            f"{AssetTable.__table__.fullname}.uid",
            ondelete="CASCADE",
        ),
        primary_key=True,
        nullable=False,
        info={
            "label": "Asset UID",
            "description": "Foreign key to the canonical AssetTable.uid for the referenced asset.",
        },
    )
    kind: Mapped[str] = mapped_column(
        String(32),
        nullable=False,
        info={
            "label": "Kind",
            "description": "Derivative kind or product family for the future contract.",
        },
    )
    underlying_index_uid: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey(
            f"{IndexTable.__table__.fullname}.uid",
            ondelete="RESTRICT",
        ),
        nullable=False,
        info={
            "label": "Underlying Index UID",
            "description": "Foreign key to IndexTable.uid for the derivative underlying index.",
        },
    )
    quote_unit: Mapped[str] = mapped_column(
        String(64),
        nullable=False,
        info={
            "label": "Quote Unit",
            "description": "Unit in which derivative prices are quoted.",
        },
    )
    settlement_asset: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey(
            f"{AssetTable.__table__.fullname}.uid",
            ondelete="RESTRICT",
        ),
        nullable=False,
        info={
            "label": "Settlement Asset",
            "description": "Asset or currency delivered or paid at derivative settlement.",
        },
    )
    margin_asset: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey(
            f"{AssetTable.__table__.fullname}.uid",
            ondelete="RESTRICT",
        ),
        nullable=False,
        info={
            "label": "Margin Asset",
            "description": "Asset or currency used as margin for the derivative contract.",
        },
    )
    settlement_model: Mapped[str] = mapped_column(
        String(32),
        nullable=False,
        info={
            "label": "Settlement Model",
            "description": "Derivative settlement model used by the contract.",
        },
    )
    settlement_method: Mapped[str] = mapped_column(
        String(32),
        nullable=False,
        info={
            "label": "Settlement Method",
            "description": "Derivative settlement method, such as cash or physical settlement.",
        },
    )
    contract_size: Mapped[Decimal] = mapped_column(
        Numeric(38, 18),
        nullable=False,
        info={
            "label": "Contract Size",
            "description": "Contract size multiplier for one derivative contract.",
        },
    )
    contract_unit: Mapped[str] = mapped_column(
        String(64),
        nullable=False,
        info={
            "label": "Contract Unit",
            "description": "Unit in which the derivative contract size is expressed.",
        },
    )
    expires_at: Mapped[dt.datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
        info={
            "label": "Expires At",
            "description": "UTC timestamp when the derivative contract expires.",
        },
    )
    settles_at: Mapped[dt.datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
        info={
            "label": "Settles At",
            "description": "UTC timestamp when the derivative contract settles.",
        },
    )
    metadata_payload: Mapped[dict | None] = mapped_column(
        "metadata",
        JSON,
        nullable=True,
        info={
            "label": "Metadata",
            "description": "Structured metadata JSON for provider, pricing, or workflow-specific attributes.",
        },
    )


__all__ = ["FutureAssetDetailsTable"]
