from __future__ import annotations

from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from apps.v1.runtime_bootstrap import prepare_apps_v1_import_namespace
from apps.v1.schemas.common import PaginatedResponse


def _pricing_market_data_contracts():
    prepare_apps_v1_import_namespace()
    from msm_pricing.api import (
        PricingMarketDataSet,
        PricingMarketDataSetBinding,
        PricingMarketDataSetBindingCreate,
        PricingMarketDataSetBindingUpdate,
        PricingMarketDataSetBindingUpsert,
        PricingMarketDataSetCreate,
        PricingMarketDataSetUpdate,
        PricingMarketDataSetUpsert,
    )

    return {
        "PricingMarketDataSet": PricingMarketDataSet,
        "PricingMarketDataSetBinding": PricingMarketDataSetBinding,
        "PricingMarketDataSetBindingCreate": PricingMarketDataSetBindingCreate,
        "PricingMarketDataSetBindingUpdate": PricingMarketDataSetBindingUpdate,
        "PricingMarketDataSetBindingUpsert": PricingMarketDataSetBindingUpsert,
        "PricingMarketDataSetCreate": PricingMarketDataSetCreate,
        "PricingMarketDataSetUpdate": PricingMarketDataSetUpdate,
        "PricingMarketDataSetUpsert": PricingMarketDataSetUpsert,
    }


_CONTRACTS = _pricing_market_data_contracts()
PricingMarketDataSet = _CONTRACTS["PricingMarketDataSet"]
PricingMarketDataSetBinding = _CONTRACTS["PricingMarketDataSetBinding"]
PricingMarketDataSetBindingCreate = _CONTRACTS["PricingMarketDataSetBindingCreate"]
PricingMarketDataSetBindingUpdate = _CONTRACTS["PricingMarketDataSetBindingUpdate"]
PricingMarketDataSetBindingUpsert = _CONTRACTS["PricingMarketDataSetBindingUpsert"]
PricingMarketDataSetCreate = _CONTRACTS["PricingMarketDataSetCreate"]
PricingMarketDataSetUpdate = _CONTRACTS["PricingMarketDataSetUpdate"]
PricingMarketDataSetUpsert = _CONTRACTS["PricingMarketDataSetUpsert"]


class PricingMarketDataResourceLink(BaseModel):
    model_config = ConfigDict(extra="forbid")

    key: str
    model: str
    list_url: str
    create_url: str
    upsert_url: str


class PricingMarketDataCardResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    resource: str = "pricing_market_data"
    description: str
    resources: list[PricingMarketDataResourceLink]


class PricingMarketDataSetListResponse(PaginatedResponse[PricingMarketDataSet]):
    model_config = ConfigDict(extra="ignore")


class PricingMarketDataSetBindingListResponse(
    PaginatedResponse[PricingMarketDataSetBinding],
):
    model_config = ConfigDict(extra="ignore")


class PricingMarketDataSetDeleteResponse(BaseModel):
    model_config = ConfigDict(extra="ignore")

    detail: str
    uid: UUID
    deleted_count: int = Field(ge=0)


class PricingMarketDataSetBindingDeleteResponse(BaseModel):
    model_config = ConfigDict(extra="ignore")

    detail: str
    uid: UUID
    deleted_count: int = Field(ge=0)


class PricingMarketDataBindingResolveResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    market_data_set: str | None = None
    concept_key: str
    data_node_uid: UUID
