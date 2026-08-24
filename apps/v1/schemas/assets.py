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
    """Latest timestamped display facts available for an Asset identity."""

    time_index: dt.datetime | None = Field(
        default=None,
        description="UTC timestamp of the latest available display-fact snapshot.",
    )
    asset_identifier: str | None = Field(
        default=None,
        description="Stable Asset.unique_identifier associated with the snapshot.",
    )
    name: str | None = Field(
        default=None,
        description="Provider-supplied security or instrument name at the snapshot time.",
    )
    ticker: str | None = Field(
        default=None,
        description="Provider-supplied ticker or display symbol at the snapshot time.",
    )
    exchange_code: str | None = Field(
        default=None,
        description="Provider-supplied exchange or market code at the snapshot time.",
    )
    asset_ticker_group_id: str | None = Field(
        default=None,
        description="Provider grouping identifier shared by related ticker or share-class records.",
    )


class AssetDetailResponse(BaseModel):
    """Composed Asset detail used by the Markets asset detail surface."""

    uid: UUID = Field(description="Canonical UUID primary key of the Asset identity.")
    unique_identifier: str = Field(
        description=(
            "Stable business identifier used for idempotent lookup and joins from asset-indexed "
            "data. It is not assumed to be a ticker."
        )
    )
    asset_type: str | None = Field(
        default=None,
        description=(
            "Normalized classification key registered by AssetType. Type-specific properties "
            "remain in separate detail models."
        ),
    )
    current_snapshot: AssetCurrentSnapshotResponse = Field(
        description=(
            "Latest timestamped name, ticker, exchange, and grouping facts; fields are null when "
            "no snapshot has been published."
        )
    )
    details: list[dict[str, Any]] = Field(
        default_factory=list,
        description="Resolved type-specific or provider-specific detail records for this Asset.",
    )
    trading_view: dict[str, Any] | None = Field(
        default=None,
        description="Optional trading-oriented presentation metadata when supported.",
    )
    order_form: dict[str, Any] | None = Field(
        default=None,
        description="Optional order-entry presentation metadata when supported.",
    )


class AssetPricingOperationParameterResponse(BaseModel):
    """One input required or accepted by an advertised Asset pricing operation."""

    model_config = ConfigDict(extra="forbid")

    key: str
    required: bool


class AssetPricingOperationLinkResponse(BaseModel):
    """Discoverable pricing operation that can be applied to the selected Asset."""

    model_config = ConfigDict(extra="forbid")

    key: str
    label: str
    method: str
    url: str
    requires_valuation_date: bool
    supports_market_data_set: bool
    requires_market_data_set: bool
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
    """Pricing capability declaration derived from the Asset's current instrument details."""

    model_config = ConfigDict(extra="forbid")

    supported: bool
    instrument_type: str
    operations: list[AssetPricingOperationLinkResponse] = Field(default_factory=list)
    reason: str | None = None


class AssetCurrentPricingDetailsResponse(BaseModel):
    """Current serialized pricing instrument details and supported pricing operations."""

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
