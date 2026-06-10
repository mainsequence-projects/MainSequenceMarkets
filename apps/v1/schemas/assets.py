from __future__ import annotations

import datetime as dt
from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from apps.v1.runtime_bootstrap import prepare_apps_v1_import_namespace


def _asset_contract():
    prepare_apps_v1_import_namespace()
    from msm.api.assets import Asset

    return Asset


Asset = _asset_contract()


class AssetCurrentSnapshotResponse(BaseModel):
    time_index: dt.datetime | None = None
    asset_identifier: str | None = None
    name: str | None = None
    ticker: str | None = None
    exchange_code: str | None = None
    asset_ticker_group_id: str | None = None


class AssetDetailResponse(BaseModel):
    uid: UUID
    unique_identifier: str
    asset_type: str | None = None
    current_snapshot: AssetCurrentSnapshotResponse
    details: list[dict[str, Any]] = Field(default_factory=list)
    trading_view: dict[str, Any] | None = None
    order_form: dict[str, Any] | None = None


class AssetPricingOperationParameterResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    key: str
    required: bool


class AssetPricingOperationLinkResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    key: str
    label: str
    method: str
    url: str
    requires_valuation_date: bool
    supports_market_data_set: bool
    request_model: str
    response_model: str
    response_contract: str
    app_component: dict[str, Any]
    parameters: list[AssetPricingOperationParameterResponse] = Field(default_factory=list)
    response_mappings: list[dict[str, Any]] = Field(default_factory=list)
    frame_url: str | None = None
    frame_response_model: str | None = None
    frame_response_contract: str | None = None


class AssetPricingSupportResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    supported: bool
    instrument_type: str
    operations: list[AssetPricingOperationLinkResponse] = Field(default_factory=list)
    reason: str | None = None


class AssetCurrentPricingDetailsResponse(BaseModel):
    model_config = ConfigDict(extra="ignore")

    asset_uid: UUID
    instrument_type: str
    instrument_dump: dict[str, Any]
    pricing_details_date: dt.datetime
    serialization_format: str
    pricing_package_version: str | None = None
    source: str | None = None
    metadata_json: dict[str, Any] | None = None
    pricing_support: AssetPricingSupportResponse | None = None
