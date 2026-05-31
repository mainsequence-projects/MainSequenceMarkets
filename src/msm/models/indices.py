from __future__ import annotations

import uuid

from sqlalchemy import Index as SqlIndex
from sqlalchemy import String, Text
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.types import JSON, Uuid

from msm.base import (
    MarketsBase,
    MarketsMetaTableMixin,
    markets_index_name,
    markets_table_args,
    new_markets_uid,
)


class IndexTypeTable(MarketsMetaTableMixin, MarketsBase):
    """Registered index type used to classify canonical market indexes."""

    __metatable_identifier__ = "IndexType"
    __metatable_description__ = (
        "Index type registry keyed by index_type. Documents and validates allowed "
        "Index.index_type values such as interest-rate indexes without embedding "
        "pricing conventions."
    )
    __table_args__ = markets_table_args(
        __metatable_identifier__,
        SqlIndex(
            markets_index_name(__metatable_identifier__, "index_type", unique=True),
            "index_type",
            unique=True,
        ),
        SqlIndex(
            markets_index_name(__metatable_identifier__, "display_name"),
            "display_name",
        ),
    )

    uid: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True),
        primary_key=True,
        default=new_markets_uid,
    )
    index_type: Mapped[str] = mapped_column(String(64), nullable=False)
    display_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    metadata_json: Mapped[dict | None] = mapped_column(JSON, nullable=True)


class IndexTable(MarketsMetaTableMixin, MarketsBase):
    """Reference row for market indexes used by derivative contracts."""

    __metatable_identifier__ = "Index"
    __metatable_description__ = (
        "Canonical market index identity table keyed by uid and unique_identifier. "
        "Stores index type, display metadata, provider, and metadata used by "
        "derivative contracts, fixings, conventions, and curves."
    )
    __table_args__ = markets_table_args(
        __metatable_identifier__,
        SqlIndex(
            markets_index_name(__metatable_identifier__, "unique_identifier", unique=True),
            "unique_identifier",
            unique=True,
        ),
        SqlIndex(
            markets_index_name(__metatable_identifier__, "display_name"),
            "display_name",
        ),
        SqlIndex(
            markets_index_name(__metatable_identifier__, "provider"),
            "provider",
        ),
        SqlIndex(
            markets_index_name(__metatable_identifier__, "index_type"),
            "index_type",
        ),
    )

    uid: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True),
        primary_key=True,
        default=new_markets_uid,
    )
    unique_identifier: Mapped[str] = mapped_column(String(255), nullable=False)
    index_type: Mapped[str] = mapped_column(String(64), nullable=False)
    display_name: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    provider: Mapped[str | None] = mapped_column(String(255), nullable=True)
    metadata_json: Mapped[dict | None] = mapped_column(JSON, nullable=True)


__all__ = ["IndexTable", "IndexTypeTable"]
