from __future__ import annotations

import uuid

from sqlalchemy import ForeignKey, Index, String
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
            markets_index_name(__metatable_identifier__, "unique_identifier", unique=True),
            "unique_identifier",
            unique=True,
        ),
        Index(
            markets_index_name(__metatable_identifier__, "index_uid"),
            "index_uid",
        ),
        Index(
            markets_index_name(__metatable_identifier__, "curve_type"),
            "curve_type",
        ),
        Index(
            markets_index_name(__metatable_identifier__, "source"),
            "source",
        ),
    )

    uid: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True),
        primary_key=True,
        default=new_markets_uid,
    )
    unique_identifier: Mapped[str] = mapped_column(String(255), nullable=False)
    display_name: Mapped[str] = mapped_column(String(255), nullable=False)
    curve_type: Mapped[str] = mapped_column(String(64), nullable=False)
    index_uid: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey(
            f"{IndexConventionDetailsTable.__table__.fullname}.index_uid",
            name=markets_fk_name(
                __metatable_identifier__,
                "IndexConventionDetails",
                "index_uid",
            ),
            ondelete="RESTRICT",
        ),
        nullable=False,
    )
    interpolation_method: Mapped[str | None] = mapped_column(String(64), nullable=True)
    compounding: Mapped[str | None] = mapped_column(String(64), nullable=True)
    source: Mapped[str | None] = mapped_column(String(255), nullable=True)
    metadata_json: Mapped[dict | None] = mapped_column("metadata", JSON, nullable=True)


__all__ = ["CurveTable"]
