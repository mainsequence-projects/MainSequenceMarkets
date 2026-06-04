from __future__ import annotations

import uuid

from sqlalchemy import Index as SqlIndex
from sqlalchemy import String, Text
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.types import JSON, Uuid

from msm.base import (
    MarketsBase,
    MarketsMetaTableMixin,
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
            None,
            "index_type",
            unique=True,
        ),
        SqlIndex(
            None,
            "display_name",
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
    index_type: Mapped[str] = mapped_column(
        String(64),
        nullable=False,
        info={
            "label": "Index Type",
            "description": "Canonical index type code used to classify rows in IndexTable.",
        },
    )
    display_name: Mapped[str | None] = mapped_column(
        String(255),
        nullable=True,
        info={
            "label": "Display Name",
            "description": "Human-readable display name for UI, logs, and operator workflows.",
        },
    )
    description: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
        info={
            "label": "Description",
            "description": "Human-readable description of the registry row and its intended use.",
        },
    )
    metadata_json: Mapped[dict | None] = mapped_column(
        JSON,
        nullable=True,
        info={
            "label": "Metadata JSON",
            "description": "Structured metadata JSON for provider, application, or workflow-specific attributes.",
        },
    )


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
            None,
            "unique_identifier",
            unique=True,
        ),
        SqlIndex(
            None,
            "display_name",
        ),
        SqlIndex(
            None,
            "provider",
        ),
        SqlIndex(
            None,
            "index_type",
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
    index_type: Mapped[str] = mapped_column(
        String(64),
        nullable=False,
        info={
            "label": "Index Type",
            "description": "Canonical index type code used to classify rows in IndexTable.",
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
    description: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
        info={
            "label": "Description",
            "description": "Human-readable description of the registry row and its intended use.",
        },
    )
    provider: Mapped[str | None] = mapped_column(
        String(255),
        nullable=True,
        info={
            "label": "Provider",
            "description": "External provider or vendor that supplied the reference row.",
        },
    )
    metadata_json: Mapped[dict | None] = mapped_column(
        JSON,
        nullable=True,
        info={
            "label": "Metadata JSON",
            "description": "Structured metadata JSON for provider, application, or workflow-specific attributes.",
        },
    )


__all__ = ["IndexTable", "IndexTypeTable"]
