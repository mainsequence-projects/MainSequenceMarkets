from __future__ import annotations

import uuid

from mainsequence.meta_tables import MetaTableForeignKey
from sqlalchemy import Index, String
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.types import JSON, Uuid

from msm.base import (
    MarketsBase,
    MarketsMetaTableMixin,
    markets_fk_name,
    markets_index_name,
    markets_table_args,
)
from msm.models import IndexTable


class IndexConventionDetailsTable(MarketsMetaTableMixin, MarketsBase):
    """Pricing convention details linked to a canonical market index."""

    __metatable_identifier__ = "IndexConventionDetails"
    __metatable_description__ = (
        "Pricing index convention detail table keyed by IndexTable.uid. Stores "
        "serialized convention payloads, index family, format, source, and metadata "
        "used to reconstruct QuantLib index definitions."
    )
    __table_args__ = markets_table_args(
        __metatable_identifier__,
        Index(
            markets_index_name(__metatable_identifier__, "index_family"),
            "index_family",
        ),
        Index(
            markets_index_name(__metatable_identifier__, "source"),
            "source",
        ),
    )

    index_uid: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True),
        MetaTableForeignKey(
            IndexTable,
            column="uid",
            name=markets_fk_name(__metatable_identifier__, "Index", "index_uid"),
            ondelete="CASCADE",
        ),
        primary_key=True,
        nullable=False,
    )
    index_family: Mapped[str] = mapped_column(String(64), nullable=False)
    convention_dump: Mapped[dict] = mapped_column(JSON, nullable=False)
    serialization_format: Mapped[str] = mapped_column(String(128), nullable=False)
    source: Mapped[str | None] = mapped_column(String(255), nullable=True)
    metadata_json: Mapped[dict | None] = mapped_column("metadata", JSON, nullable=True)


__all__ = ["IndexConventionDetailsTable"]
