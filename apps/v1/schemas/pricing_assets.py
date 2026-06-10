from __future__ import annotations

import datetime as dt
from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

APP_COMPONENT_OPERATION_EXTRA = {
    "x-command-center-consumer": "app-component",
    "x-ui-output-root": "response:$",
    "x-ui-response-mode": "provider-native-json",
}

ASSET_PRICING_REQUEST_EXTRA = {
    "x-command-center-consumer": "app-component",
    "x-ui-form-source": "openapi-request-body",
}


def _operation_response_extra(
    *,
    kind: str,
    flat_outputs: list[str],
    response_mappings: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    extra = {
        **APP_COMPONENT_OPERATION_EXTRA,
        "x-ui-result-kind": kind,
        "x-ui-flat-outputs": flat_outputs,
    }
    if response_mappings is not None:
        extra["x-response-mappings"] = response_mappings
    return extra


class AssetPricingOperationRequest(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
        json_schema_extra=ASSET_PRICING_REQUEST_EXTRA,
    )

    valuation_date: dt.datetime = Field(
        ...,
        description="Valuation date used by the pricing instrument.",
        json_schema_extra={
            "x-ui-field-kind": "date-time",
            "x-ui-token": "pricing.valuation_date",
        },
    )
    market_data_set: str | None = Field(
        default=None,
        description=(
            "Pricing market-data set selector passed to the instrument operation. "
            "Required by the pricing operation registry for market-data-backed operations."
        ),
        json_schema_extra={
            "x-ui-field-kind": "string",
            "x-ui-token": "pricing.market_data_set",
        },
    )
    parameters: dict[str, Any] = Field(
        default_factory=dict,
        description="Operation-specific parameters validated by the pricing registry.",
        json_schema_extra={
            "x-ui-field-kind": "json",
            "x-ui-token": "pricing.parameters",
        },
    )


class AssetPricingOperationResponseBase(BaseModel):
    model_config = ConfigDict(
        extra="ignore",
        json_schema_extra=APP_COMPONENT_OPERATION_EXTRA,
    )

    asset_uid: UUID
    instrument_type: str
    operation: str
    valuation_date: dt.datetime
    market_data_set: str | None = None


class BondPriceResponse(AssetPricingOperationResponseBase):
    model_config = ConfigDict(
        extra="ignore",
        json_schema_extra=_operation_response_extra(
            kind="scalar",
            flat_outputs=["price", "units"],
        ),
    )

    price: float
    units: str


class BondAnalyticsResponse(AssetPricingOperationResponseBase):
    model_config = ConfigDict(
        extra="ignore",
        json_schema_extra=_operation_response_extra(
            kind="metrics",
            flat_outputs=[
                "analytics.clean_price",
                "analytics.dirty_price",
                "analytics.accrued_amount",
            ],
        ),
    )

    analytics: dict[str, Any]


class BondDurationResponse(AssetPricingOperationResponseBase):
    model_config = ConfigDict(
        extra="ignore",
        json_schema_extra=_operation_response_extra(
            kind="scalar",
            flat_outputs=["duration", "duration_type"],
        ),
    )

    duration_type: str
    duration: float


class BondYieldResponse(AssetPricingOperationResponseBase):
    model_config = ConfigDict(
        extra="ignore",
        populate_by_name=True,
        json_schema_extra=_operation_response_extra(
            kind="scalar",
            flat_outputs=["yield"],
        ),
    )

    yield_value: float = Field(alias="yield")


class BondZSpreadResponse(AssetPricingOperationResponseBase):
    model_config = ConfigDict(
        extra="ignore",
        json_schema_extra=_operation_response_extra(
            kind="scalar",
            flat_outputs=["z_spread", "target_dirty_ccy", "units"],
        ),
    )

    target_dirty_ccy: float
    z_spread: float
    units: str


class BondCashflowsResponse(AssetPricingOperationResponseBase):
    model_config = ConfigDict(
        extra="ignore",
        json_schema_extra=_operation_response_extra(
            kind="cashflow-legs",
            flat_outputs=["legs"],
            response_mappings=[
                {
                    "id": "cashflow_rows_by_leg",
                    "label": "Cashflow rows by leg",
                    "contract": "core.tabular_frame@v1",
                    "statusCode": "200",
                    "contentType": "application/json",
                    "rowsPath": "$.legs.*[*]",
                    "fieldTypes": {
                        "payment_date": "date",
                        "amount": "number",
                        "rate": "number",
                    },
                }
            ],
        ),
    )

    legs: dict[str, list[dict[str, Any]]]


class BondNetCashflowRow(BaseModel):
    model_config = ConfigDict(extra="forbid")

    payment_date: str | None = None
    net_cashflow: float


class BondNetCashflowsResponse(AssetPricingOperationResponseBase):
    model_config = ConfigDict(
        extra="ignore",
        json_schema_extra=_operation_response_extra(
            kind="cashflow-table",
            flat_outputs=["cashflows"],
            response_mappings=[
                {
                    "id": "net_cashflows",
                    "label": "Net cashflows",
                    "contract": "core.tabular_frame@v1",
                    "statusCode": "200",
                    "contentType": "application/json",
                    "rowsPath": "$.cashflows",
                    "fieldTypes": {
                        "payment_date": "date",
                        "net_cashflow": "number",
                    },
                }
            ],
        ),
    )

    cashflows: list[BondNetCashflowRow]


class BondCarryRollDownResponse(AssetPricingOperationResponseBase):
    model_config = ConfigDict(
        extra="ignore",
        json_schema_extra=_operation_response_extra(
            kind="metrics",
            flat_outputs=["horizon_days", "metrics"],
        ),
    )

    horizon_days: int
    metrics: dict[str, Any]


class BondCurvePreviewCurveReference(BaseModel):
    model_config = ConfigDict(extra="forbid")

    role: str
    curve_uid: UUID
    curve_identifier: str
    curve_type: str
    index_uid: UUID
    source: str | None = None
    discount_curve_url: str
    discount_curve_query_params: dict[str, Any]


class BondCurvePreviewResponse(AssetPricingOperationResponseBase):
    model_config = ConfigDict(
        extra="ignore",
        json_schema_extra=_operation_response_extra(
            kind="diagnostics",
            flat_outputs=["curves", "diagnostics.pricing_engine_id"],
        ),
    )

    curves: list[BondCurvePreviewCurveReference]
    diagnostics: dict[str, Any]


class BondFixingAvailabilityRow(BaseModel):
    model_config = ConfigDict(extra="forbid")

    index_uid: UUID
    index_identifier: str
    required_start_date: dt.date
    required_end_date: dt.date
    available_start_date: dt.date | None = None
    available_end_date: dt.date | None = None
    missing_count: int
    status: str


class BondFixingsAvailabilityResponse(AssetPricingOperationResponseBase):
    model_config = ConfigDict(
        extra="ignore",
        json_schema_extra=_operation_response_extra(
            kind="diagnostics",
            flat_outputs=["status", "fixings"],
        ),
    )

    status: str
    fixings: list[BondFixingAvailabilityRow]
