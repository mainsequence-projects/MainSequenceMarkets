from __future__ import annotations

import datetime as dt
from typing import Any, Generic, TypeVar

from pydantic import BaseModel, ConfigDict, Field

HoldingRowT = TypeVar("HoldingRowT", bound="BaseHoldingRow")


class HoldingAssetCurrentSnapshot(BaseModel):
    model_config = ConfigDict(extra="ignore")

    name: str | None = None
    ticker: str | None = None


class HoldingAssetReference(BaseModel):
    model_config = ConfigDict(extra="ignore")

    uid: str | None = None
    asset_identifier: str | None = None
    current_snapshot: HoldingAssetCurrentSnapshot = Field(
        default_factory=HoldingAssetCurrentSnapshot,
    )


class BaseHoldingRow(BaseModel):
    model_config = ConfigDict(extra="ignore")

    time_index: dt.datetime | None = None
    asset_identifier: str
    asset: HoldingAssetReference | None = None
    quantity: str | None = None
    direction: int = 1
    signed_quantity: str | None = None
    target_trade_time: dt.datetime | None = None
    extra_details: dict[str, Any] = Field(default_factory=dict)


class BaseHoldingsSnapshotResponse(BaseModel, Generic[HoldingRowT]):
    model_config = ConfigDict(extra="ignore")

    holdings_set_uid: str | None = None
    holdings_date: dt.datetime | None = None
    holdings: list[HoldingRowT] = Field(default_factory=list)
