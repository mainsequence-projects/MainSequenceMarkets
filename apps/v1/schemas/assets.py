from __future__ import annotations

import datetime as dt
from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict


class AssetListRow(BaseModel):
    model_config = ConfigDict(extra="ignore")

    uid: UUID
    unique_identifier: str
    figi: str | None = None
    name: str | None = None
    ticker: str | None = None
    exchange_code: str | None = None
    security_market_sector: str | None = None
    security_type: str | None = None
    is_custom_by_organization: bool = True


class AssetCurrentPricingDetailsResponse(BaseModel):
    model_config = ConfigDict(extra="ignore")

    asset_uid: UUID
    instrument_type: str
    instrument_dump: dict[str, Any]
    pricing_details_date: dt.datetime
    serialization_format: str
    pricing_package_version: str | None = None
    source: str | None = None
    metadata_json: dict[str, Any] | None = None
