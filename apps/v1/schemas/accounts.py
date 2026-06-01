from __future__ import annotations

from uuid import UUID

from pydantic import BaseModel, ConfigDict


class AccountListRow(BaseModel):
    model_config = ConfigDict(extra="ignore")

    uid: UUID
    display_name: str
    is_paper: bool
    account_is_active: bool


class AccountListResponse(BaseModel):
    model_config = ConfigDict(extra="ignore")

    count: int
    results: list[AccountListRow]
