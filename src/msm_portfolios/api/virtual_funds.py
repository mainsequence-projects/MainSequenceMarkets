from __future__ import annotations

import uuid
from typing import Any, ClassVar

from pydantic import BaseModel, ConfigDict, Field

from msm.api.base import MarketsMetaTableRow
from msm.models import AccountTable, AssetTable

from msm_portfolios.models import FundTable, PortfolioTable


class Fund(MarketsMetaTableRow):
    """Typed fund row bound to an account and portfolio."""

    __table__: ClassVar[type[FundTable]] = FundTable
    __required_tables__: ClassVar[list[type[Any]]] = [
        AssetTable,
        AccountTable,
        PortfolioTable,
        FundTable,
    ]
    __upsert_keys__: ClassVar[tuple[str, ...]] = ("unique_identifier",)

    unique_identifier: str
    target_account_uid: uuid.UUID
    target_portfolio_uid: uuid.UUID
    requires_nav_adjustment: bool = False
    metadata_json: dict[str, Any] | None = None


class FundCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    unique_identifier: str = Field(min_length=1, max_length=255)
    target_account_uid: uuid.UUID | str
    target_portfolio_uid: uuid.UUID | str
    requires_nav_adjustment: bool = False
    metadata_json: dict[str, Any] | None = None


class FundUpsert(FundCreate):
    """Payload for inserting or updating a fund."""


class FundUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    target_account_uid: uuid.UUID | str | None = None
    target_portfolio_uid: uuid.UUID | str | None = None
    requires_nav_adjustment: bool | None = None
    metadata_json: dict[str, Any] | None = None


__all__ = [
    "Fund",
    "FundCreate",
    "FundUpdate",
    "FundUpsert",
]
