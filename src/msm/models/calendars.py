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


class CalendarTable(MarketsMetaTableMixin, MarketsBase):
    """Named market calendar used by portfolio and execution workflows."""

    __metatable_identifier__ = "Calendar"
    __metatable_description__ = (
        "Market calendar registry keyed by name. Stores named calendar date payloads "
        "and metadata used by portfolio, execution, and valuation workflows."
    )
    __table_args__ = markets_table_args(
        __metatable_identifier__,
        Index(
            markets_index_name(__metatable_identifier__, "name", unique=True),
            "name",
            unique=True,
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
    name: Mapped[str] = mapped_column(
        String(255),
        nullable=False,
        info={
            "label": "Name",
            "description": "Canonical human-readable name for this registry row.",
        },
    )
    calendar_dates: Mapped[dict | list | None] = mapped_column(
        JSON,
        nullable=True,
        info={
            "label": "Calendar Dates",
            "description": "Structured calendar date payload for the named market calendar.",
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


__all__ = ["CalendarTable"]
