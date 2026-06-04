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


class AccountModelPortfolioTable(MarketsMetaTableMixin, MarketsBase):
    """Named model portfolio that can be tracked by many accounts."""

    __metatable_identifier__ = "AccountModelPortfolio"
    __metatable_description__ = (
        "Account model-portfolio registry keyed by model_portfolio_name. Stores "
        "named portfolio policy metadata that many accounts can track through "
        "AccountTargetPortfolioTable rows."
    )
    __table_args__ = markets_table_args(
        __metatable_identifier__,
        Index(
            None,
            "model_portfolio_name",
            unique=True,
        ),
    )

    uid: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True),
        primary_key=True,
        default=new_markets_uid,
        info={
            "label": "UID",
            "description": "Stable account model-portfolio identity used by account target portfolios.",
        },
    )
    model_portfolio_name: Mapped[str] = mapped_column(
        String(100),
        nullable=False,
        info={
            "label": "Model Portfolio Name",
            "description": "Human-readable unique name for the reusable account model portfolio.",
        },
    )
    model_portfolio_description: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
        info={
            "label": "Model Portfolio Description",
            "description": "Free-form description of the account model-portfolio policy.",
        },
    )
    metadata_json: Mapped[dict | None] = mapped_column(
        JSON,
        nullable=True,
        info={
            "label": "Metadata",
            "description": "JSON metadata for model-portfolio governance, provenance, or labels.",
        },
    )


class AccountGroupTable(MarketsMetaTableMixin, MarketsBase):
    """Account grouping metadata used by market workflows."""

    __metatable_identifier__ = "AccountGroup"
    __metatable_description__ = (
        "Account group registry keyed by group_name. Defines reusable account "
        "sets such as risk buckets or operational groups; membership is stored "
        "on AccountTable.account_group_uid."
    )
    __table_args__ = markets_table_args(
        __metatable_identifier__,
        Index(
            None,
            "group_name",
            unique=True,
        ),
    )

    uid: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True),
        primary_key=True,
        default=new_markets_uid,
        info={
            "label": "UID",
            "description": "Stable account group identity referenced by AccountTable.account_group_uid.",
        },
    )
    group_name: Mapped[str | None] = mapped_column(
        String(100),
        nullable=True,
        info={
            "label": "Group Name",
            "description": "Unique account group name such as a risk bucket or operating desk.",
        },
    )
    group_description: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
        info={
            "label": "Group Description",
            "description": "Free-form description of the account group membership intent.",
        },
    )
    metadata_json: Mapped[dict | None] = mapped_column(
        JSON,
        nullable=True,
        info={
            "label": "Metadata",
            "description": "JSON metadata for group provenance, labels, or operational hints.",
        },
    )


__all__ = [
    "AccountGroupTable",
    "AccountModelPortfolioTable",
]
