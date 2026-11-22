"""Virtual-fund time-index-table output contracts."""

from __future__ import annotations

import datetime
import uuid
from typing import ClassVar

from sqlalchemy import CheckConstraint, DateTime, Float, ForeignKey, Index, SmallInteger, String
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.types import Uuid

from msm.base import MarketsBase, MarketsTimeIndexMetaTableMixin
from msm.models.accounts import AccountHoldingsSetTable, AccountTable
from msm.models.assets.core import AssetTable
from msm.settings import ASSET_IDENTIFIER_DIMENSION
from msm.models.accounts.virtual_funds import VirtualFundHoldingsSetTable, VirtualFundTable


class VirtualFundHoldingsStorage(MarketsTimeIndexMetaTableMixin, MarketsBase):
    """Virtual-fund allocations keyed by virtual fund UID and held asset."""

    __metatable_identifier__ = "VirtualFundHoldingsTS"
    __metatable_description__ = (
        "Timestamped virtual-fund allocation storage keyed by (time_index, "
        "virtual_fund_uid, asset_identifier). Each row is a positive allocated "
        "quantity from a source account holdings set, with direction storing the "
        "long/short side."
    )
    __table_args__ = (
        CheckConstraint("direction IN (1, -1)", name="ck_virtual_fund_holdings_direction"),
        # The unique index leads with time_index; these serve one fund's rows from one
        # source holdings set, and the foreign keys that reference them (revision 0034).
        Index(None, "virtual_fund_uid", "source_account_holdings_set_uid"),
        Index(None, "source_account_holdings_set_uid"),
        Index(None, "virtual_fund_holdings_set_uid"),
    )
    __time_index_name__: ClassVar[str] = "time_index"
    __index_names__: ClassVar[list[str]] = [
        "time_index",
        "virtual_fund_uid",
        ASSET_IDENTIFIER_DIMENSION,
    ]

    time_index: Mapped[datetime.datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        info={
            "label": "Time Index",
            "description": (
                "UTC timestamp for the virtual-fund allocation snapshot. Rows with "
                "the same virtual_fund_uid and time_index belong to one allocation view."
            ),
        },
    )
    virtual_fund_uid: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey(
            f"{VirtualFundTable.__table__.fullname}.uid",
            ondelete="CASCADE",
        ),
        nullable=False,
        info={
            "label": "Virtual Fund UID",
            "description": (
                "Stable VirtualFundTable.uid that owns the allocation row. This "
                "dimension scopes allocation history to one virtual fund."
            ),
        },
    )
    asset_identifier: Mapped[str] = mapped_column(
        String(255),
        ForeignKey(
            f"{AssetTable.__table__.fullname}.unique_identifier",
            ondelete="RESTRICT",
        ),
        nullable=False,
        info={
            "label": "Asset Identifier",
            "description": "Asset unique identifier for the allocated instrument.",
        },
    )
    virtual_fund_holdings_set_uid: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey(
            f"{VirtualFundHoldingsSetTable.__table__.fullname}.uid",
            ondelete="CASCADE",
        ),
        nullable=False,
        info={
            "label": "Virtual Fund Holdings Set UID",
            "description": "VirtualFundHoldingsSetTable.uid shared by rows in one allocation set.",
        },
    )
    source_account_holdings_set_uid: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey(
            f"{AccountHoldingsSetTable.__table__.fullname}.uid",
            ondelete="RESTRICT",
        ),
        nullable=False,
        info={
            "label": "Source Account Holdings Set UID",
            "description": "AccountHoldingsSetTable.uid that bounds this allocation row.",
        },
    )
    allocated_quantity: Mapped[float] = mapped_column(
        Float,
        nullable=False,
        info={
            "label": "Allocated Quantity",
            "description": "Positive source-account holdings magnitude allocated to this virtual fund.",
        },
    )
    allocation_strategy: Mapped[str] = mapped_column(
        String(64),
        default="explicit",
        nullable=False,
        info={
            "label": "Allocation Strategy",
            "description": (
                "First-class strategy used to produce this virtual-fund allocation row. "
                "Low-level explicit publications use 'explicit'; rows written by an "
                "allocation use the policy id, such as 'proportional_attribution'."
            ),
        },
    )
    direction: Mapped[int] = mapped_column(
        SmallInteger,
        default=1,
        nullable=False,
        info={
            "label": "Direction",
            "description": "Allocation side: 1 for long, -1 for short.",
        },
    )
    target_trade_time: Mapped[datetime.datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
        info={
            "label": "Target Trade Time",
            "description": (
                "Requested or expected execution time as a timezone-aware UTC datetime when provided."
            ),
        },
    )
    extra_details: Mapped[dict | None] = mapped_column(
        JSONB,
        nullable=True,
        info={
            "label": "Extra Details",
            "description": "JSONB payload for provider-specific holdings attributes.",
        },
    )


OWNER_TYPE_FUND = "fund"
OWNER_TYPE_DIRECT = "direct"


class AccountAllocationLinesStorage(MarketsTimeIndexMetaTableMixin, MarketsBase):
    """The lines of one allocation of an account's holdings: target, assigned, per owner."""

    __metatable_identifier__ = "AccountAllocationLinesTS"
    __metatable_description__ = (
        "Timestamped record of one allocation of an account holdings set, keyed by "
        "(time_index, holdings_set_uid, owner_type, owner_uid, "
        "asset_identifier). One row per owner and asset, where the owner is a virtual "
        "fund or the account itself for what it holds outside its funds. A row holds the "
        "target units the provider sized and the units of the account's holdings the owner "
        "was assigned. The difference, target minus assigned, is what the owner would trade."
    )
    __table_args__ = (
        CheckConstraint(
            f"owner_type IN ('{OWNER_TYPE_FUND}', '{OWNER_TYPE_DIRECT}')",
            name="ck_account_allocation_lines_owner_type",
        ),
        CheckConstraint(
            f"(owner_type = '{OWNER_TYPE_FUND}' AND virtual_fund_uid IS NOT NULL "
            "AND owner_uid = virtual_fund_uid) OR "
            f"(owner_type = '{OWNER_TYPE_DIRECT}' AND virtual_fund_uid IS NULL "
            "AND owner_uid = account_uid)",
            name="ck_account_allocation_lines_owner_reference",
        ),
        CheckConstraint(
            "target_quantity >= 0 AND assigned_quantity >= 0",
            name="ck_account_allocation_lines_quantities",
        ),
        CheckConstraint(
            "target_direction IN (1, -1) AND assigned_direction IN (1, -1)",
            name="ck_account_allocation_lines_directions",
        ),
        # The unique index leads with time_index; these serve one account's lines and the
        # foreign keys that reference the account, its holdings sets and its funds
        # (revision 0034).
        Index(None, "account_uid", "time_index"),
        Index(None, "holdings_set_uid"),
        Index(None, "virtual_fund_uid"),
    )
    __time_index_name__: ClassVar[str] = "time_index"
    __index_names__: ClassVar[list[str]] = [
        "time_index",
        "holdings_set_uid",
        "owner_type",
        "owner_uid",
        ASSET_IDENTIFIER_DIMENSION,
    ]

    time_index: Mapped[datetime.datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        info={
            "label": "Time Index",
            "description": (
                "UTC timestamp of the allocated account holdings snapshot. Rows with the "
                "same holdings_set_uid belong to one allocation."
            ),
        },
    )
    holdings_set_uid: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey(
            f"{AccountHoldingsSetTable.__table__.fullname}.uid",
            ondelete="RESTRICT",
        ),
        nullable=False,
        info={
            "label": "Holdings Set UID",
            "description": (
                "AccountHoldingsSetTable.uid of the holdings snapshot that was allocated. "
                "An allocation is recorded once per holdings snapshot."
            ),
        },
    )
    owner_type: Mapped[str] = mapped_column(
        String(16),
        nullable=False,
        info={
            "label": "Owner Type",
            "description": (
                "Who the line belongs to: fund for a virtual fund, direct for what the "
                "account holds outside its funds."
            ),
        },
    )
    owner_uid: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True),
        nullable=False,
        info={
            "label": "Owner UID",
            "description": (
                "VirtualFundTable.uid when owner_type is fund; AccountTable.uid when "
                "owner_type is direct."
            ),
        },
    )
    asset_identifier: Mapped[str] = mapped_column(
        String(255),
        ForeignKey(
            f"{AssetTable.__table__.fullname}.unique_identifier",
            ondelete="RESTRICT",
        ),
        nullable=False,
        info={
            "label": "Asset Identifier",
            "description": "Asset unique identifier of the asset the line is about.",
        },
    )
    account_uid: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey(
            f"{AccountTable.__table__.fullname}.uid",
            ondelete="CASCADE",
        ),
        nullable=False,
        info={
            "label": "Account UID",
            "description": "AccountTable.uid of the account whose holdings were allocated.",
        },
    )
    virtual_fund_uid: Mapped[uuid.UUID | None] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey(
            f"{VirtualFundTable.__table__.fullname}.uid",
            ondelete="CASCADE",
        ),
        nullable=True,
        info={
            "label": "Virtual Fund UID",
            "description": "VirtualFundTable.uid when the owner is a virtual fund; null for a direct line.",
        },
    )
    target_quantity: Mapped[float] = mapped_column(
        Float,
        nullable=False,
        info={
            "label": "Target Quantity",
            "description": (
                "Units the provider sized as the owner's target for the asset at this "
                "allocation. Zero when the owner has units of an asset it does not target."
            ),
        },
    )
    target_direction: Mapped[int] = mapped_column(
        SmallInteger,
        default=1,
        nullable=False,
        info={
            "label": "Target Direction",
            "description": "Side of the target: 1 for long, -1 for short.",
        },
    )
    assigned_quantity: Mapped[float] = mapped_column(
        Float,
        nullable=False,
        info={
            "label": "Assigned Quantity",
            "description": (
                "Units of the account's holdings assigned to the owner. Zero when the owner "
                "targets the asset and gets none."
            ),
        },
    )
    assigned_direction: Mapped[int] = mapped_column(
        SmallInteger,
        default=1,
        nullable=False,
        info={
            "label": "Assigned Direction",
            "description": "Side of the assigned units: 1 for long, -1 for short.",
        },
    )
    allocation_strategy: Mapped[str] = mapped_column(
        String(64),
        nullable=False,
        info={
            "label": "Allocation Strategy",
            "description": "Id of the allocation policy that produced the line, such as proportional_attribution.",
        },
    )
    extra_details: Mapped[dict | None] = mapped_column(
        JSONB,
        nullable=True,
        info={
            "label": "Extra Details",
            "description": (
                "JSONB record of the allocation the line belongs to: the policy version, "
                "the PositionSet it was measured against and the plan digest."
            ),
        },
    )


__all__ = [
    "OWNER_TYPE_DIRECT",
    "OWNER_TYPE_FUND",
    "AccountAllocationLinesStorage",
    "VirtualFundHoldingsStorage",
]
