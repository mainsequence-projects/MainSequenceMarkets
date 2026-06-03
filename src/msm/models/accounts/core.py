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
    markets_index_name,
    markets_table_args,
    new_markets_uid,
)

from .groups import AccountGroupTable, AccountModelPortfolioTable


class AccountTable(MarketsMetaTableMixin, MarketsBase):
    """Client account or execution account registered as a markets MetaTable."""

    __metatable_identifier__ = "Account"
    __metatable_description__ = (
        "Canonical account registry keyed by uid and unique_identifier. Stores "
        "client or execution-account identity, status flags, holdings DataNode "
        "linkage, optional account group membership, and account metadata used "
        "by holdings and execution workflows. Model-portfolio tracking belongs "
        "to AccountTargetPortfolioTable."
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
        Index(
            markets_index_name(__metatable_identifier__, "account_group_uid"),
            "account_group_uid",
        ),
    )

    uid: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True),
        primary_key=True,
        default=new_markets_uid,
        info={
            "label": "UID",
            "description": "Canonical account identity used by account-owned MetaTables and DataNodes.",
        },
    )
    unique_identifier: Mapped[str] = mapped_column(
        String(255),
        nullable=False,
        info={
            "label": "Unique Identifier",
            "description": "Stable external account business key used for idempotent upserts.",
        },
    )
    account_name: Mapped[str] = mapped_column(
        String(255),
        nullable=False,
        info={
            "label": "Account Name",
            "description": "Display name for the client, strategy, or execution account.",
        },
    )
    is_paper: Mapped[bool] = mapped_column(
        default=True,
        nullable=False,
        info={
            "label": "Is Paper",
            "description": "Whether the account is a paper or simulated account.",
        },
    )
    account_is_active: Mapped[bool] = mapped_column(
        default=False,
        nullable=False,
        info={
            "label": "Account Is Active",
            "description": "Whether the account is currently active for workflows.",
        },
    )
    account_group_uid: Mapped[uuid.UUID | None] = mapped_column(
        Uuid(as_uuid=True),
        MetaTableForeignKey(
            AccountGroupTable,
            column="uid",
            ondelete="SET NULL",
        ),
        nullable=True,
        info={
            "label": "Account Group UID",
            "description": "Optional AccountGroupTable.uid used to group accounts.",
        },
    )
    holdings_data_node_uid: Mapped[uuid.UUID | None] = mapped_column(
        Uuid(as_uuid=True),
        nullable=True,
        info={
            "label": "Holdings DataNode UID",
            "description": "Optional platform DataNodeStorage UID for this account's holdings history.",
        },
    )
    metadata_json: Mapped[dict | None] = mapped_column(
        JSON,
        nullable=True,
        info={
            "label": "Metadata",
            "description": "JSON metadata for account provenance, routing, or operational labels.",
        },
    )


class AccountTargetPortfolioTable(MarketsMetaTableMixin, MarketsBase):
    """Account-level target portfolio mandate tracked through position sets."""

    __metatable_identifier__ = "AccountTargetPortfolio"
    __metatable_description__ = (
        "Account target-portfolio registry keyed by unique_identifier. Each row "
        "connects one account to the account model portfolio it is intended to "
        "track, and acts as the parent for concrete target PositionSet rows."
    )
    __table_args__ = markets_table_args(
        __metatable_identifier__,
        Index(
            markets_index_name(__metatable_identifier__, "unique_identifier", unique=True),
            "unique_identifier",
            unique=True,
        ),
        Index(
            markets_index_name(__metatable_identifier__, "account_uid"),
            "account_uid",
        ),
        Index(
            markets_index_name(__metatable_identifier__, "account_model_portfolio_uid"),
            "account_model_portfolio_uid",
        ),
        Index(
            markets_index_name(__metatable_identifier__, "is_active"),
            "is_active",
        ),
    )

    uid: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True),
        primary_key=True,
        default=new_markets_uid,
        info={
            "label": "UID",
            "description": "Stable account target-portfolio identity referenced by PositionSetTable.",
        },
    )
    unique_identifier: Mapped[str] = mapped_column(
        String(255),
        nullable=False,
        info={
            "label": "Unique Identifier",
            "description": "Stable external business key for the account target-portfolio relation.",
        },
    )
    account_uid: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True),
        MetaTableForeignKey(
            AccountTable,
            column="uid",
            ondelete="CASCADE",
        ),
        nullable=False,
        info={
            "label": "Account UID",
            "description": "AccountTable.uid for the account that owns this target portfolio.",
        },
    )
    account_model_portfolio_uid: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True),
        MetaTableForeignKey(
            AccountModelPortfolioTable,
            column="uid",
            ondelete="RESTRICT",
        ),
        nullable=False,
        info={
            "label": "Account Model Portfolio UID",
            "description": "AccountModelPortfolioTable.uid for the reusable model being tracked.",
        },
    )
    display_name: Mapped[str | None] = mapped_column(
        String(255),
        nullable=True,
        info={
            "label": "Display Name",
            "description": "Optional display label for the account target-portfolio mandate.",
        },
    )
    is_active: Mapped[bool] = mapped_column(
        default=True,
        nullable=False,
        info={
            "label": "Is Active",
            "description": "Whether this account target-portfolio relation is currently active.",
        },
    )
    source: Mapped[str | None] = mapped_column(
        String(255),
        nullable=True,
        info={
            "label": "Source",
            "description": "Optional source system or workflow that created the relation.",
        },
    )
    metadata_json: Mapped[dict | None] = mapped_column(
        JSON,
        nullable=True,
        info={
            "label": "Metadata",
            "description": "JSON metadata for target-portfolio policy, provenance, or labels.",
        },
    )


class AccountHoldingsSetTable(MarketsMetaTableMixin, MarketsBase):
    """Concrete source holdings snapshot for an account."""

    __metatable_identifier__ = "AccountHoldingsSet"
    __metatable_description__ = (
        "Account holdings-set registry keyed by account_uid and time_index. Each "
        "row identifies one real account holdings snapshot; AccountHoldingsStorage "
        "rows reference it through holdings_set_uid, and virtual-fund allocation "
        "sets use it as their source holdings bound."
    )
    __table_args__ = markets_table_args(
        __metatable_identifier__,
        Index(
            markets_index_name(__metatable_identifier__, "account_uid"),
            "account_uid",
        ),
        Index(
            markets_index_name(__metatable_identifier__, "time_index"),
            "time_index",
        ),
        Index(
            markets_index_name(
                __metatable_identifier__,
                "account_uid",
                "time_index",
                unique=True,
            ),
            "account_uid",
            "time_index",
            unique=True,
        ),
    )

    uid: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True),
        primary_key=True,
        default=new_markets_uid,
        info={
            "label": "UID",
            "description": "Stable account holdings-set identity referenced by holdings storage.",
        },
    )
    account_uid: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True),
        MetaTableForeignKey(
            AccountTable,
            column="uid",
            ondelete="CASCADE",
        ),
        nullable=False,
        info={
            "label": "Account UID",
            "description": "AccountTable.uid for the account that owns this holdings snapshot.",
        },
    )
    time_index: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        info={
            "label": "Time Index",
            "description": "UTC timestamp identifying this account holdings snapshot.",
        },
    )
    source_data_node_uid: Mapped[uuid.UUID | None] = mapped_column(
        Uuid(as_uuid=True),
        nullable=True,
        info={
            "label": "Source DataNode UID",
            "description": "Optional DataNodeStorage uid that produced this holdings set.",
        },
    )


class PositionSetTable(MarketsMetaTableMixin, MarketsBase):
    """Concrete target-position snapshot for an account target portfolio."""

    __metatable_identifier__ = "PositionSet"
    __metatable_description__ = (
        "Target position-set registry keyed by account_target_portfolio_uid and "
        "position_set_time. Each row names one concrete target-position snapshot; "
        "actual asset exposure rows live in TargetPositionsStorage and reference "
        "this uid through position_set_uid."
    )
    __table_args__ = markets_table_args(
        __metatable_identifier__,
        Index(
            markets_index_name(__metatable_identifier__, "account_target_portfolio_uid"),
            "account_target_portfolio_uid",
        ),
        Index(
            markets_index_name(__metatable_identifier__, "position_set_time"),
            "position_set_time",
        ),
        Index(
            markets_index_name(
                __metatable_identifier__,
                "account_target_portfolio_uid",
                "position_set_time",
                unique=True,
            ),
            "account_target_portfolio_uid",
            "position_set_time",
            unique=True,
        ),
    )

    uid: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True),
        primary_key=True,
        default=new_markets_uid,
        info={
            "label": "UID",
            "description": "Stable position-set identity referenced by target-position exposure rows.",
        },
    )
    account_target_portfolio_uid: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True),
        MetaTableForeignKey(
            AccountTargetPortfolioTable,
            column="uid",
            ondelete="CASCADE",
        ),
        nullable=False,
        info={
            "label": "Account Target Portfolio UID",
            "description": (
                "AccountTargetPortfolioTable.uid for the account/model mandate this "
                "position set belongs to."
            ),
        },
    )
    position_set_time: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        info={
            "label": "Position Set Time",
            "description": "UTC timestamp identifying this concrete target-position snapshot.",
        },
    )
    source: Mapped[str | None] = mapped_column(
        String(255),
        nullable=True,
        info={
            "label": "Source",
            "description": "Optional source system or workflow that created the position set.",
        },
    )
    metadata_json: Mapped[dict | None] = mapped_column(
        JSON,
        nullable=True,
        info={
            "label": "Metadata",
            "description": (
                "JSON metadata for the target snapshot. Asset exposure values are "
                "stored in TargetPositionsStorage, not on this registry row."
            ),
        },
    )


__all__ = [
    "AccountHoldingsSetTable",
    "AccountTable",
    "AccountTargetPortfolioTable",
    "PositionSetTable",
]
