from __future__ import annotations

import datetime as dt

from pydantic import BaseModel, ConfigDict, Field


def _portfolio_contracts():
    import msm.api.portfolios as contracts

    return contracts


def _portfolio_metadata_contract():
    from msm_portfolios.api.portfolios import PortfolioMetadata

    return PortfolioMetadata


_contracts = _portfolio_contracts()
Portfolio = _contracts.Portfolio
PortfolioDeletedRows = _contracts.PortfolioDeletedRows
PortfolioDeleteResponse = _contracts.PortfolioDeleteResponse
PortfolioBulkDeleteResponse = _contracts.PortfolioBulkDeleteResponse
PortfolioMetadata = _portfolio_metadata_contract()


class PortfolioDetailTab(BaseModel):
    model_config = ConfigDict(extra="ignore")

    key: str
    label: str
    url: str


class PortfolioDetailLinks(BaseModel):
    model_config = ConfigDict(extra="ignore")

    summary: str
    latest_weights: str
    delete: str


class PortfolioDetailResponse(BaseModel):
    model_config = ConfigDict(extra="ignore")

    portfolio: Portfolio
    metadata: PortfolioMetadata | None = None
    tabs: list[PortfolioDetailTab] = Field(default_factory=list)
    links: PortfolioDetailLinks


class PortfolioWeightAssetCurrentSnapshot(BaseModel):
    model_config = ConfigDict(extra="ignore")

    name: str | None = None
    ticker: str | None = None


class PortfolioWeightAssetReference(BaseModel):
    model_config = ConfigDict(extra="ignore")

    uid: str | None = None
    unique_identifier: str | None = None
    current_snapshot: PortfolioWeightAssetCurrentSnapshot = Field(
        default_factory=PortfolioWeightAssetCurrentSnapshot,
    )


class PortfolioWeightRow(BaseModel):
    model_config = ConfigDict(extra="ignore")

    time_index: dt.datetime | None = None
    portfolio_identifier: str | None = None
    asset_identifier: str
    weight: str | None = None
    weight_before: str | None = None
    price_current: str | None = None
    price_before: str | None = None
    volume_current: str | None = None
    volume_before: str | None = None
    asset: PortfolioWeightAssetReference | None = None


class PortfolioWeightsSnapshotResponse(BaseModel):
    model_config = ConfigDict(extra="ignore")

    portfolio_uid: str | None = None
    portfolio_unique_identifier: str | None = None
    published_index_uid: str | None = None
    portfolio_identifier: str | None = None
    weights_date: dt.datetime | None = None
    resolution_warning: str | None = None
    weights: list[PortfolioWeightRow] = Field(default_factory=list)


class PortfolioDeletePreflightItem(BaseModel):
    model_config = ConfigDict(extra="ignore")

    uid: str
    unique_identifier: str
    row_counts: PortfolioDeletedRows = Field(
        default_factory=dict,
        description="The portfolio's rows the delete would remove, per dataset.",
    )
    blockers: list[str] = Field(
        default_factory=list,
        description=(
            "Account history that names the portfolio, and tables of other applications "
            "whose RESTRICT keys reference it and that hold rows of it or cannot be checked."
        ),
    )


def _bulk_delete_preflight_response() -> type[BaseModel]:
    from msm.api.http import BulkDeletePreflightResponse

    return BulkDeletePreflightResponse


class PortfolioDeletePreflightResponse(_bulk_delete_preflight_response()):
    """What deleting the selected portfolios removes and what blocks it (issue 93)."""

    portfolios: list[PortfolioDeletePreflightItem] = Field(default_factory=list)


class PortfolioWeightsDeleteResponse(BaseModel):
    model_config = ConfigDict(extra="ignore")

    detail: str
    portfolio_uid: str
    portfolio_identifier: str | None = None
    weights_date: dt.datetime | None = None
    deleted_count: int = 0
