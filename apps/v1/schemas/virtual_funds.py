from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field

from apps.v1.runtime_bootstrap import prepare_apps_v1_import_namespace
from apps.v1.schemas.common import PaginatedResponse
from apps.v1.schemas.holdings import BaseHoldingRow, BaseHoldingsSnapshotResponse


def _virtual_fund_contract():
    prepare_apps_v1_import_namespace()
    from msm.api.virtual_funds import VirtualFund

    return VirtualFund


VirtualFund = _virtual_fund_contract()


class VirtualFundListResponse(PaginatedResponse[VirtualFund]):
    model_config = ConfigDict(extra="ignore")


class VirtualFundDetailTab(BaseModel):
    model_config = ConfigDict(extra="ignore")

    key: str
    label: str
    url: str


class VirtualFundDetailLinks(BaseModel):
    model_config = ConfigDict(extra="ignore")

    summary: str
    latest_holdings: str
    account: str
    portfolio: str


class VirtualFundDetailResponse(BaseModel):
    model_config = ConfigDict(extra="ignore")

    virtual_fund: VirtualFund
    tabs: list[VirtualFundDetailTab] = Field(default_factory=list)
    links: VirtualFundDetailLinks


class VirtualFundHoldingRow(BaseHoldingRow):
    model_config = ConfigDict(extra="ignore")

    virtual_fund_holdings_set_uid: str | None = None
    source_account_holdings_set_uid: str | None = None


class VirtualFundHoldingsSnapshotResponse(BaseHoldingsSnapshotResponse[VirtualFundHoldingRow]):
    model_config = ConfigDict(extra="ignore")

    virtual_fund_uid: str | None = None
    virtual_fund_unique_identifier: str | None = None
    source_account_holdings_set_uid: str | None = None
