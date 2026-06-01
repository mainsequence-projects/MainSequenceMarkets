from __future__ import annotations

import datetime as dt
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from apps.v1.runtime_bootstrap import prepare_apps_v1_import_namespace


def _account_contract():
    prepare_apps_v1_import_namespace()
    from msm.api.accounts import Account

    return Account


Account = _account_contract()


class AccountListResponse(BaseModel):
    model_config = ConfigDict(extra="ignore")

    count: int
    results: list[Account]


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
