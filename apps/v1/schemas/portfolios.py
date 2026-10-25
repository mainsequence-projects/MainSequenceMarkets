from __future__ import annotations

import datetime as dt
from typing import Any

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


def _portfolio_dataset_contracts():
    prepare_apps_v1_import_namespace()
    from msm_portfolios.services.portfolio_datasets import (
        PortfolioDatasetReconciliationResult,
        PortfolioDatasetState,
    )

    return PortfolioDatasetState, PortfolioDatasetReconciliationResult


Portfolio = _portfolio_contract()
PortfolioMetadata = _portfolio_metadata_contract()
PortfolioDatasetState, PortfolioDatasetReconciliationResult = _portfolio_dataset_contracts()


class PortfolioWithIncludes(Portfolio):
    """`Portfolio` plus the provider sidecar rows requested with `include` (ADR 0047)."""

    includes: dict[str, dict[str, Any] | None] = Field(
        default_factory=dict,
        description=(
            "Provider sidecar rows requested with `include`, keyed by sidecar MetaTable uid; "
            "`null` when the sidecar has no row for this uid. Empty when nothing was included."
        ),
    )


class PortfolioDatasetRegistrationRequest(BaseModel):
    """The instance tables a producer declares for one portfolio (ADR 0047)."""

    model_config = ConfigDict(extra="forbid")

    values_meta_table_uid: str = Field(
        min_length=1,
        max_length=255,
        description="TimeIndexMetaTable uid of the PortfoliosTS instance holding the values.",
    )
    weights_meta_table_uid: str | None = Field(
        default=None,
        min_length=1,
        max_length=255,
        description="TimeIndexMetaTable uid of the PortfolioWeightsTS instance, if any.",
    )
    signal_meta_table_uid: str | None = Field(
        default=None,
        min_length=1,
        max_length=255,
        description="TimeIndexMetaTable uid of the SignalWeightsTS instance, if any.",
    )
    reconcile: bool = Field(
        default=True,
        description="Reconcile the values instance at once; false records the row as not reconciled.",
    )


class PortfolioDatasetReconcileRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    portfolio_uids: list[str] = Field(default_factory=list, max_length=500)
    portfolio_identifiers: list[str] = Field(default_factory=list, max_length=500)


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


class PortfolioDeleteRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    uids: list[str] = Field(default_factory=list)


class PortfolioDeleteFailure(BaseModel):
    model_config = ConfigDict(extra="ignore")

    uid: str
    reason: str


class PortfolioDeleteResponse(BaseModel):
    model_config = ConfigDict(extra="ignore")

    detail: str
    deleted_count: int = 0
    deleted_weights_count: int = 0
    deleted_values_count: int = 0


class PortfolioBulkDeleteResponse(PortfolioDeleteResponse):
    failed: list[PortfolioDeleteFailure] = Field(default_factory=list)


class PortfolioCascadeDeleteResponse(PortfolioDeleteResponse):
    deleted_target_positions_count: int = 0
    deleted_virtual_funds_count: int = 0
    deleted_virtual_fund_holdings_sets_count: int = 0
    deleted_virtual_fund_holdings_count: int = 0


class PortfolioBulkCascadeDeleteResponse(PortfolioCascadeDeleteResponse):
    failed: list[PortfolioDeleteFailure] = Field(default_factory=list)


class PortfolioWeightsDeleteResponse(BaseModel):
    model_config = ConfigDict(extra="ignore")

    detail: str
    portfolio_uid: str
    portfolio_identifier: str | None = None
    weights_date: dt.datetime | None = None
    deleted_count: int = 0
