from __future__ import annotations

import datetime as dt
import uuid

from sqlalchemy import Date, Index, String
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.types import JSON, Uuid

from msm.base import (
    MarketsBase,
    MarketsMetaTableMixin,
    markets_table_args,
    new_markets_uid,
)


class CalendarTable(MarketsMetaTableMixin, MarketsBase):
    """Calendar identity and bounded materialization metadata."""

    __metatable_identifier__ = "Calendar"
    __metatable_description__ = (
        "Calendar identity table keyed by unique_identifier. Stores the durable "
        "calendar definition, source adapter identity, timezone, and validity "
        "horizon used by portfolios, execution, pricing, settlement, and custom "
        "market workflows."
    )
    __table_args__ = markets_table_args(
        __metatable_identifier__,
        Index(None, "unique_identifier", unique=True),
        Index(None, "calendar_type"),
        Index(None, "source", "source_identifier"),
    )

    uid: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True),
        primary_key=True,
        default=new_markets_uid,
        info={
            "label": "UID",
            "description": "Canonical UUID primary key for this calendar identity row.",
        },
    )
    unique_identifier: Mapped[str] = mapped_column(
        String(255),
        nullable=False,
        info={
            "label": "Unique Identifier",
            "description": "Stable business key used for idempotent calendar lookup and joins.",
        },
    )
    display_name: Mapped[str] = mapped_column(
        String(255),
        nullable=False,
        info={
            "label": "Display Name",
            "description": "Human-readable calendar name shown in tools, examples, and reports.",
        },
    )
    calendar_type: Mapped[str] = mapped_column(
        String(64),
        nullable=False,
        info={
            "label": "Calendar Type",
            "description": "Calendar purpose such as TRADING, SETTLEMENT, FIXING, BUSINESS, HOLIDAY, EVENT, or CUSTOM.",
        },
    )
    timezone: Mapped[str] = mapped_column(
        String(64),
        nullable=False,
        default="UTC",
        info={
            "label": "Timezone",
            "description": "IANA timezone used to interpret local calendar dates and session labels.",
        },
    )
    source: Mapped[str | None] = mapped_column(
        String(128),
        nullable=True,
        info={
            "label": "Source",
            "description": "Adapter or provider that produced this calendar materialization.",
        },
    )
    source_identifier: Mapped[str | None] = mapped_column(
        String(255),
        nullable=True,
        info={
            "label": "Source Identifier",
            "description": "Provider-specific calendar key such as NYSE, TARGET, CME_EQ_INDEX, or a user-defined name.",
        },
    )
    valid_from: Mapped[dt.date] = mapped_column(
        Date,
        nullable=False,
        info={
            "label": "Valid From",
            "description": "First local date covered by the persisted calendar materialization.",
        },
    )
    valid_to: Mapped[dt.date] = mapped_column(
        Date,
        nullable=False,
        info={
            "label": "Valid To",
            "description": "Last local date covered by the persisted calendar materialization.",
        },
    )
    metadata_json: Mapped[dict | None] = mapped_column(
        JSON,
        nullable=True,
        info={
            "label": "Metadata JSON",
            "description": "Structured metadata for provider, desk, market, or workflow-specific calendar attributes.",
        },
    )


__all__ = ["CalendarTable"]
