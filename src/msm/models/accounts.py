from __future__ import annotations

import datetime as dt
import uuid

from mainsequence.meta_tables import MetaTableForeignKey
from sqlalchemy import DateTime, Index, String
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


class AccountTable(MarketsMetaTableMixin, MarketsBase):
    """Client account or execution account registered as a markets MetaTable."""

    __metatable_identifier__ = "Account"
    __metatable_description__ = (
        "Canonical account registry keyed by uid and unique_identifier. Stores "
        "client or execution-account identity, status flags, holdings DataNode "
        "linkage, and account metadata used by holdings and execution workflows."
    )
    __table_args__ = markets_table_args(
        __metatable_identifier__,
        Index(
            markets_index_name(__metatable_identifier__, "unique_identifier", unique=True),
            "unique_identifier",
            unique=True,
        ),
        Index(
            markets_index_name(__metatable_identifier__, "account_name"),
            "account_name",
        ),
        Index(
            markets_index_name(__metatable_identifier__, "account_is_active"),
            "account_is_active",
        ),
    )

    uid: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True),
        primary_key=True,
        default=new_markets_uid,
    )
    unique_identifier: Mapped[str] = mapped_column(String(255), nullable=False)
    account_name: Mapped[str] = mapped_column(String(255), nullable=False)
    is_paper: Mapped[bool] = mapped_column(default=True, nullable=False)
    account_is_active: Mapped[bool] = mapped_column(default=False, nullable=False)
    holdings_data_node_uid: Mapped[uuid.UUID | None] = mapped_column(
        Uuid(as_uuid=True),
        nullable=True,
    )
    metadata_json: Mapped[dict | None] = mapped_column(JSON, nullable=True)


class AccountTargetPositionAssignmentTable(MarketsMetaTableMixin, MarketsBase):
    """Binding from an account to a reusable target-position set."""

    __metatable_identifier__ = "AccountTargetPositionAssignment"
    __metatable_description__ = (
        "Account target-position binding keyed by account_uid and "
        "target_positions_time. Connects an account to a reusable target-position "
        "set for a specific UTC assignment timestamp."
    )
    __table_args__ = markets_table_args(
        __metatable_identifier__,
        Index(
            markets_index_name(__metatable_identifier__, "account_uid"),
            "account_uid",
        ),
        Index(
            markets_index_name(__metatable_identifier__, "target_positions_time"),
            "target_positions_time",
        ),
        Index(
            markets_index_name(
                __metatable_identifier__,
                "account_uid",
                "target_positions_time",
                unique=True,
            ),
            "account_uid",
            "target_positions_time",
            unique=True,
        ),
    )

    uid: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True),
        primary_key=True,
        default=new_markets_uid,
    )
    account_uid: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True),
        MetaTableForeignKey(
            AccountTable,
            column="uid",
            name=markets_fk_name(__metatable_identifier__, "Account", "account_uid"),
            ondelete="CASCADE",
        ),
        nullable=False,
    )
    target_positions_time: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
    )
    position_set_uid: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)


__all__ = [
    "AccountTable",
    "AccountTargetPositionAssignmentTable",
]
