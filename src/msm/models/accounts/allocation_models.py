from __future__ import annotations

import uuid

from sqlalchemy import Index, String, Text
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.types import JSON, Uuid

from msm.base import (
    MarketsBase,
    MarketsMetaTableMixin,
    markets_table_args,
    new_markets_uid,
)


class AccountAllocationModelTable(MarketsMetaTableMixin, MarketsBase):
    """Reusable account allocation model that can be tracked by many accounts."""

    __metatable_identifier__ = "AccountAllocationModel"
    __metatable_description__ = (
        "Account allocation-model registry keyed by allocation_model_name. Stores "
        "named allocation policy metadata that many accounts can track through "
        "AccountTargetAllocationTable rows."
    )
    __table_args__ = markets_table_args(
        __metatable_identifier__,
        Index(
            None,
            "allocation_model_name",
            unique=True,
        ),
    )

    uid: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True),
        primary_key=True,
        default=new_markets_uid,
        info={
            "label": "UID",
            "description": "Stable account allocation-model identity used by account target allocations.",
        },
    )
    allocation_model_name: Mapped[str] = mapped_column(
        String(100),
        nullable=False,
        info={
            "label": "Allocation Model Name",
            "description": "Human-readable unique name for the reusable account allocation model.",
        },
    )
    allocation_model_description: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
        info={
            "label": "Allocation Model Description",
            "description": "Free-form description of the account allocation-model policy.",
        },
    )
    metadata_json: Mapped[dict | None] = mapped_column(
        JSON,
        nullable=True,
        info={
            "label": "Metadata",
            "description": "JSON metadata for allocation-model governance, provenance, or labels.",
        },
    )


__all__ = ["AccountAllocationModelTable"]
