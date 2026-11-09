from __future__ import annotations

import datetime as dt
from typing import Any
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from apps.v1.runtime_bootstrap import prepare_apps_v1_import_namespace
from apps.v1.schemas.holdings import (
    BaseHoldingRow,
    BaseHoldingsSnapshotResponse,
    HoldingAssetReference,
)


def _account_contracts():
    prepare_apps_v1_import_namespace()
    import msm.api.accounts as contracts

    return contracts


_contracts = _account_contracts()
Account = _contracts.Account
AccountCreate = _contracts.AccountCreate
AccountUpdate = _contracts.AccountUpdate
AccountAddTargetPositionsRequest = _contracts.AccountAddTargetPositionsRequest
AccountTargetPositionsSnapshotResponse = _contracts.AccountTargetPositionsSnapshotResponse
AccountVirtualFundAllocationRequest = _contracts.AccountVirtualFundAllocationRequest
AccountVirtualFundAllocationResponse = _contracts.AccountVirtualFundAllocationResponse


class AccountWithIncludes(Account):
    """`Account` plus the provider sidecar rows requested with `include` (ADR 0047)."""

    includes: dict[str, dict[str, Any] | None] = Field(
        default_factory=dict,
        description=(
            "Provider sidecar rows requested with `include`, keyed by sidecar MetaTable uid; "
            "`null` when the sidecar has no row for this uid. Empty when nothing was included."
        ),
    )


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
