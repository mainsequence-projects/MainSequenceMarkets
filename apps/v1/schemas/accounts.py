from __future__ import annotations

import datetime as dt
from typing import Any
from typing import Annotated
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from apps.v1.runtime_bootstrap import prepare_apps_v1_import_namespace
from apps.v1.schemas.common import PaginatedResponse
from apps.v1.schemas.holdings import (
    BaseHoldingRow,
    BaseHoldingsSnapshotResponse,
    HoldingAssetCurrentSnapshot,
    HoldingAssetReference,
)


def _account_contract():
    prepare_apps_v1_import_namespace()
    from msm.api.accounts import Account

    return Account


Account = _account_contract()


class AccountListResponse(PaginatedResponse[Account]):
    model_config = ConfigDict(extra="ignore")


class AccountHoldingRow(BaseHoldingRow):
    model_config = ConfigDict(extra="ignore")

    position_type: str = "units"
    price: str | None = None
    missing_price: bool = True


class AccountHoldingsSnapshotResponse(BaseHoldingsSnapshotResponse[AccountHoldingRow]):
    model_config = ConfigDict(extra="ignore")


class AccountHoldingsByFundAllocation(BaseModel):
    model_config = ConfigDict(extra="ignore")

    target_gap_signed_quantity: str | None = None
    scale: str | None = None
    target_row_key: str | None = None
    position_set_uid: str | None = None


class AccountHoldingsByFundHoldingRow(BaseHoldingRow):
    model_config = ConfigDict(extra="ignore")

    allocation_strategy: str | None = None
    allocation: AccountHoldingsByFundAllocation = Field(
        default_factory=AccountHoldingsByFundAllocation,
    )


class AccountHoldingsByFundGroup(BaseModel):
    model_config = ConfigDict(extra="ignore")

    virtual_fund_uid: str
    virtual_fund_unique_identifier: str | None = None
    target_portfolio_uid: str | None = None
    holdings_set_uid: str | None = None
    holdings: list[AccountHoldingsByFundHoldingRow] = Field(default_factory=list)


class AccountHoldingsByFundResidual(BaseModel):
    model_config = ConfigDict(extra="ignore")

    asset_identifier: str
    source_signed_quantity: str
    allocated_signed_quantity: str
    residual_signed_quantity: str
    asset: HoldingAssetReference | None = None


class AccountHoldingsByFundResponse(BaseModel):
    model_config = ConfigDict(extra="ignore")

    account_uid: str
    source_account_holdings_set_uid: str | None = None
    holdings_date: dt.datetime | None = None
    funds: list[AccountHoldingsByFundGroup] = Field(default_factory=list)
    residuals: list[AccountHoldingsByFundResidual] = Field(default_factory=list)
    allocation_warnings: list[str] = Field(default_factory=list)


class AccountAddHoldingsPositionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    asset_identifier: str = Field(min_length=1)
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
    current_snapshot: HoldingAssetCurrentSnapshot = Field(
        default_factory=HoldingAssetCurrentSnapshot,
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


class _AccountAddTargetPositionBaseRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    target_uid: str = Field(min_length=1)
    weight_notional_exposure: str | int | float | None = None
    constant_notional_exposure: str | int | float | None = None
    single_asset_quantity: str | int | float | None = None
    metadata_json: dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode="after")
    def _validate_single_exposure(self):
        provided_fields = [
            field_name
            for field_name in (
                "weight_notional_exposure",
                "constant_notional_exposure",
                "single_asset_quantity",
            )
            if getattr(self, field_name) is not None
        ]
        if len(provided_fields) != 1:
            raise ValueError("Each target position must provide exactly one exposure field.")
        return self


class AccountAddAssetTargetPositionRequest(_AccountAddTargetPositionBaseRequest):
    target_type: Literal["asset"]
    asset_uid: str = Field(min_length=1)
    portfolio_uid: None = None


class AccountAddPortfolioTargetPositionRequest(_AccountAddTargetPositionBaseRequest):
    target_type: Literal["portfolio"]
    asset_uid: None = None
    portfolio_uid: str = Field(min_length=1)

    @model_validator(mode="after")
    def _reject_portfolio_units(self):
        if self.single_asset_quantity is not None:
            raise ValueError("Portfolio target positions cannot use single_asset_quantity.")
        return self


AccountAddTargetPositionRequest = Annotated[
    AccountAddAssetTargetPositionRequest | AccountAddPortfolioTargetPositionRequest,
    Field(discriminator="target_type"),
]


class AccountAddTargetPositionsRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    target_positions_date: dt.datetime
    overwrite: bool
    positions: list[AccountAddTargetPositionRequest] = Field(min_length=1)


AccountTargetAllocationTargetSearchType = Literal["all", "asset", "portfolio"]


class AccountTargetAllocationCandidateCurrentSnapshot(BaseModel):
    model_config = ConfigDict(extra="ignore")

    name: str | None = None
    ticker: str | None = None


class AccountTargetAllocationCandidate(BaseModel):
    model_config = ConfigDict(extra="ignore")

    target_type: Literal["asset", "portfolio"]
    target_uid: str
    asset_uid: str | None = None
    portfolio_uid: str | None = None
    identifier: str
    display_label: str
    secondary_label: str | None = None
    current_snapshot: AccountTargetAllocationCandidateCurrentSnapshot | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class AccountTargetAllocationCandidateResponse(PaginatedResponse[AccountTargetAllocationCandidate]):
    model_config = ConfigDict(extra="ignore")
