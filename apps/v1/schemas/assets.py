from __future__ import annotations

from uuid import UUID

from pydantic import BaseModel, ConfigDict


class AssetListRow(BaseModel):
    model_config = ConfigDict(extra="ignore")

    id: str
    uid: UUID
    unique_identifier: str
    figi: str | None = None
    name: str | None = None
    ticker: str | None = None
    exchange_code: str | None = None
    security_market_sector: str | None = None
    security_type: str | None = None
    is_custom_by_organization: bool = True
