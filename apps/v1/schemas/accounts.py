from __future__ import annotations

import datetime as dt
from typing import Any
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from apps.v1.runtime_bootstrap import prepare_apps_v1_import_namespace
from apps.v1.schemas.common import PaginatedResponse


def _account_contract():
    prepare_apps_v1_import_namespace()
    from msm.api.accounts import Account

    return Account


Account = _account_contract()


class AccountListResponse(PaginatedResponse[Account]):
    model_config = ConfigDict(extra="ignore")


class AccountHoldingAssetCurrentSnapshot(BaseModel):
    model_config = ConfigDict(extra="ignore")

    name: str | None = None
    ticker: str | None = None


class AccountHoldingAssetReference(BaseModel):
    model_config = ConfigDict(extra="ignore")

    uid: str | None = None
    figi: str | None = None
    current_snapshot: AccountHoldingAssetCurrentSnapshot = Field(
        default_factory=AccountHoldingAssetCurrentSnapshot,
    )


class AccountHoldingRow(BaseModel):
    model_config = ConfigDict(extra="ignore")

    time_index: dt.datetime
    unique_identifier: str
    asset_id: None = None
    asset: AccountHoldingAssetReference | None = None
    position_type: str = "units"
    price: str | None = None
    quantity: str | None = None
    direction: int = 1
    missing_price: bool = True
    target_trade_time: dt.datetime | None = None
    extra_details: dict[str, Any] = Field(default_factory=dict)


class AccountHoldingsSnapshotResponse(BaseModel):
    model_config = ConfigDict(extra="ignore")

    id: str | None = None
    snapshot_uid: str | None = None
    holdings_set_uid: str | None = None
    holdings_date: dt.datetime | None = None
    nav: str | None = None
    related_account_uid: str | None = None
    is_trade_snapshot: bool = False
    target_trade_time: dt.datetime | None = None
    related_expected_asset_exposure_df: list[Any] = Field(default_factory=list)
    holdings: list[AccountHoldingRow] = Field(default_factory=list)


class AccountAddHoldingsPositionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    unique_identifier: str = Field(min_length=1)
    asset_uid: str | None = None
    position_type: Literal["units"] = "units"
    quantity: str = Field(min_length=1)
    direction: Literal[-1, 1] = 1
    target_trade_time: dt.datetime | None = None
    extra_details: dict[str, Any] = Field(default_factory=dict)


class AccountAddHoldingsRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    holdings_date: dt.datetime
    overwrite: bool = False
    positions: list[AccountAddHoldingsPositionRequest] = Field(min_length=1)


class AccountTargetPositionAssetReference(BaseModel):
    model_config = ConfigDict(extra="ignore")

    uid: str | None = None
    unique_identifier: str | None = None
    current_snapshot: AccountHoldingAssetCurrentSnapshot = Field(
        default_factory=AccountHoldingAssetCurrentSnapshot,
    )


class AccountTargetPositionPortfolioReference(BaseModel):
    model_config = ConfigDict(extra="ignore")

    uid: str | None = None
    unique_identifier: str | None = None
    portfolio_index_uid: str | None = None


class AccountTargetPositionRow(BaseModel):
    model_config = ConfigDict(extra="ignore")

    target_type: Literal["asset", "portfolio"]
    target_uid: str
    asset_uid: str | None = None
    portfolio_uid: str | None = None
    unique_identifier: str
    weight_notional_exposure: str | None = None
    constant_notional_exposure: str | None = None
    single_asset_quantity: str | None = None
    asset: AccountTargetPositionAssetReference | None = None
    portfolio: AccountTargetPositionPortfolioReference | None = None


class AccountTargetPositionsSnapshotResponse(BaseModel):
    model_config = ConfigDict(extra="ignore")

    related_account_uid: str | None = None
    target_positions_date: dt.datetime | None = None
    position_set_uid: str | None = None
    positions: list[AccountTargetPositionRow] = Field(default_factory=list)
