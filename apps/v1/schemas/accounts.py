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
AccountRegistrationRequest = _contracts.AccountRegistrationRequest
AccountRegistrationResponse = _contracts.AccountRegistrationResponse


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


AccountDeletedRows = dict[str, int]


class AccountDeleteResponse(BaseModel):
    """One account deleted with its history (ADR 0050)."""

    model_config = ConfigDict(extra="ignore")

    detail: str
    uid: str
    unique_identifier: str
    deleted_count: int = 1
    deleted_rows: AccountDeletedRows = Field(
        default_factory=dict,
        description=(
            "Markets rows deleted with the account, per table: order_events, trades, "
            "orders, order_managers, virtual_fund_holdings, virtual_fund_holdings_sets, "
            "virtual_funds, target_positions, position_sets, target_allocations, holdings "
            "and holdings_sets. Counted just before the delete ran."
        ),
    )
    other_namespace_cascades: list[str] = Field(
        default_factory=list,
        description=(
            "Tables in other namespaces whose own CASCADE keys delete their rows that "
            "reference the account or its rows. Markets sends them no statement."
        ),
    )


class AccountDeleteFailure(BaseModel):
    model_config = ConfigDict(extra="ignore")

    uid: str
    detail: str


class AccountBulkDeleteResponse(BaseModel):
    """Accounts deleted with their history, each in its own transaction."""

    model_config = ConfigDict(extra="ignore")

    detail: str
    deleted_count: int = 0
    deleted: list[AccountDeleteResponse] = Field(default_factory=list)
    failed: list[AccountDeleteFailure] = Field(default_factory=list)
    other_namespace_cascades: list[str] = Field(default_factory=list)


class AccountDeletePreflightItem(BaseModel):
    model_config = ConfigDict(extra="ignore")

    uid: str
    unique_identifier: str
    row_counts: AccountDeletedRows = Field(
        default_factory=dict,
        description="Markets rows the delete would remove, per table.",
    )
    blockers: list[str] = Field(default_factory=list)


def _bulk_delete_preflight_response() -> type[BaseModel]:
    prepare_apps_v1_import_namespace()
    from msm.api.http import BulkDeletePreflightResponse

    return BulkDeletePreflightResponse


class AccountDeletePreflightResponse(_bulk_delete_preflight_response()):
    """What deleting the selected accounts removes, reaches and is blocked by (ADR 0050)."""

    accounts: list[AccountDeletePreflightItem] = Field(default_factory=list)
    other_namespace_cascades: list[str] = Field(
        default_factory=list,
        description=(
            "Tables in other namespaces whose own CASCADE keys delete their rows that "
            "reference the accounts or their rows. Markets sends them no statement."
        ),
    )
    other_namespace_restricts: list[str] = Field(
        default_factory=list,
        description=(
            "Tables in other namespaces whose RESTRICT keys refuse the delete while they "
            "hold rows that reference the accounts or their rows. Markets cannot count "
            "those rows; the application that owns each table deletes them first."
        ),
    )
