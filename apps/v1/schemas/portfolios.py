from __future__ import annotations

import datetime as dt

from pydantic import BaseModel, ConfigDict, Field

from apps.v1.runtime_bootstrap import prepare_apps_v1_import_namespace


def _portfolio_contract():
    prepare_apps_v1_import_namespace()
    from msm.api.portfolios import Portfolio

    return Portfolio


def _portfolio_metadata_contract():
    prepare_apps_v1_import_namespace()
    from msm_portfolios.api.portfolios import PortfolioMetadata

    return PortfolioMetadata


Portfolio = _portfolio_contract()
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


PortfolioDeletedRows = dict[str, int]


class PortfolioDeleteResponse(BaseModel):
    """One portfolio deleted with its datasets in one transaction (ADR 0049, issue 93)."""

    model_config = ConfigDict(extra="ignore")

    detail: str
    uid: str
    unique_identifier: str
    deleted_count: int = 1
    deleted_rows: PortfolioDeletedRows = Field(
        default_factory=dict,
        description=(
            "The portfolio's rows deleted with it, per dataset: weights, values, "
            "rebalance_state, analytics, event_ledger, state and cash_flows. Counted "
            "just before the delete ran."
        ),
    )


class PortfolioDeleteFailure(BaseModel):
    model_config = ConfigDict(extra="ignore")

    uid: str
    detail: str


class PortfolioBulkDeleteResponse(BaseModel):
    """Portfolios deleted with their datasets, each in its own transaction."""

    model_config = ConfigDict(extra="ignore")

    detail: str
    deleted_count: int = 0
    deleted: list[PortfolioDeleteResponse] = Field(default_factory=list)
    failed: list[PortfolioDeleteFailure] = Field(default_factory=list)


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
    prepare_apps_v1_import_namespace()
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
