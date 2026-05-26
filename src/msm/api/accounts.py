from __future__ import annotations

import uuid
from typing import Any, ClassVar

from pydantic import BaseModel, ConfigDict, Field

from msm.api.base import MarketsRow
from msm.models import (
    AccountGroupTable,
    AccountModelPortfolioTable,
    AccountTable,
    AccountTargetPositionAssignmentTable,
)


class AccountModelPortfolio(MarketsRow):
    """Typed account model-portfolio row."""

    __table__: ClassVar[type[AccountModelPortfolioTable]] = AccountModelPortfolioTable
    __required_tables__: ClassVar[list[type[AccountModelPortfolioTable]]] = [
        AccountModelPortfolioTable
    ]
    __upsert_keys__: ClassVar[tuple[str, ...]] = ("model_portfolio_name",)

    model_portfolio_name: str
    model_portfolio_description: str | None = None
    metadata_json: dict[str, Any] | None = None


class AccountModelPortfolioCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    model_portfolio_name: str = Field(min_length=1, max_length=100)
    model_portfolio_description: str | None = None
    metadata_json: dict[str, Any] | None = None


class AccountModelPortfolioUpsert(AccountModelPortfolioCreate):
    """Payload for inserting or updating an account model portfolio."""


class AccountModelPortfolioUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    model_portfolio_description: str | None = None
    metadata_json: dict[str, Any] | None = None


class AccountGroup(MarketsRow):
    """Typed account group row."""

    __table__: ClassVar[type[AccountGroupTable]] = AccountGroupTable
    __required_tables__: ClassVar[list[type[Any]]] = [
        AccountModelPortfolioTable,
        AccountGroupTable,
    ]
    __upsert_keys__: ClassVar[tuple[str, ...]] = ("group_name",)

    group_name: str | None = None
    group_description: str | None = None
    account_model_portfolio_uid: uuid.UUID | None = None
    metadata_json: dict[str, Any] | None = None


class AccountGroupCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    group_name: str | None = Field(default=None, max_length=100)
    group_description: str | None = None
    account_model_portfolio_uid: uuid.UUID | str | None = None
    metadata_json: dict[str, Any] | None = None


class AccountGroupUpsert(AccountGroupCreate):
    """Payload for inserting or updating an account group."""


class AccountGroupUpdate(AccountGroupCreate):
    """Payload for updating mutable account group fields."""


class Account(MarketsRow):
    """Typed account row."""

    __table__: ClassVar[type[AccountTable]] = AccountTable
    __required_tables__: ClassVar[list[type[AccountTable]]] = [AccountTable]
    __upsert_keys__: ClassVar[tuple[str, ...]] = ("unique_identifier",)

    unique_identifier: str
    account_name: str
    is_paper: bool = True
    account_is_active: bool = False
    holdings_data_node_uid: uuid.UUID | None = None
    metadata_json: dict[str, Any] | None = None


class AccountCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    unique_identifier: str = Field(min_length=1, max_length=255)
    account_name: str = Field(min_length=1, max_length=255)
    is_paper: bool = True
    account_is_active: bool = False
    holdings_data_node_uid: uuid.UUID | str | None = None
    metadata_json: dict[str, Any] | None = None


class AccountUpsert(AccountCreate):
    """Payload for inserting or updating an account."""


class AccountUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    account_name: str | None = Field(default=None, max_length=255)
    is_paper: bool | None = None
    account_is_active: bool | None = None
    holdings_data_node_uid: uuid.UUID | str | None = None
    metadata_json: dict[str, Any] | None = None


class AccountTargetPositionAssignment(MarketsRow):
    """Typed binding from an account to a target-position set."""

    __table__: ClassVar[type[AccountTargetPositionAssignmentTable]] = (
        AccountTargetPositionAssignmentTable
    )
    __required_tables__: ClassVar[list[type[Any]]] = [
        AccountTable,
        AccountTargetPositionAssignmentTable,
    ]
    __upsert_keys__: ClassVar[tuple[str, ...]] = (
        "account_uid",
        "target_positions_time",
    )

    account_uid: uuid.UUID
    target_positions_time: str
    position_set_uid: uuid.UUID


class AccountTargetPositionAssignmentCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    account_uid: uuid.UUID | str
    target_positions_time: str = Field(min_length=1, max_length=64)
    position_set_uid: uuid.UUID | str


class AccountTargetPositionAssignmentUpsert(AccountTargetPositionAssignmentCreate):
    """Payload for inserting or updating a target-position assignment."""


class AccountTargetPositionAssignmentUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    position_set_uid: uuid.UUID | str | None = None


__all__ = [
    "Account",
    "AccountCreate",
    "AccountGroup",
    "AccountGroupCreate",
    "AccountGroupUpdate",
    "AccountGroupUpsert",
    "AccountModelPortfolio",
    "AccountModelPortfolioCreate",
    "AccountModelPortfolioUpdate",
    "AccountModelPortfolioUpsert",
    "AccountTargetPositionAssignment",
    "AccountTargetPositionAssignmentCreate",
    "AccountTargetPositionAssignmentUpdate",
    "AccountTargetPositionAssignmentUpsert",
    "AccountUpdate",
    "AccountUpsert",
]
