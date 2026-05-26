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


class InstrumentsConfigurationTable(MarketsMetaTableMixin, MarketsBase):
    """DataNode bindings used by instrument pricing and curve construction."""

    __metatable_identifier__ = "InstrumentsConfiguration"
    __table_args__ = markets_table_args(
        __metatable_identifier__,
        Index(
            markets_index_name(__metatable_identifier__, "unique_configuration", unique=True),
            "configuration_key",
            unique=True,
        ),
    )

    uid: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True),
        primary_key=True,
        default=new_markets_uid,
    )
    configuration_key: Mapped[str] = mapped_column(
        String(64),
        default="default",
        nullable=False,
    )
    discount_curves_data_node_uid: Mapped[uuid.UUID | None] = mapped_column(
        Uuid(as_uuid=True),
        nullable=True,
    )
    reference_rates_fixings_data_node_uid: Mapped[uuid.UUID | None] = mapped_column(
        Uuid(as_uuid=True),
        nullable=True,
    )
    metadata_json: Mapped[dict | None] = mapped_column(JSON, nullable=True)


InstrumentsConfiguration = InstrumentsConfigurationTable

__all__ = ["InstrumentsConfiguration", "InstrumentsConfigurationTable"]
