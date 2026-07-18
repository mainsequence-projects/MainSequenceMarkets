from __future__ import annotations

import datetime as dt
from typing import Any
from uuid import UUID

from pydantic import BaseModel, Field
from pydantic import ConfigDict

from apps.v1.runtime_bootstrap import prepare_apps_v1_import_namespace
from apps.v1.schemas.common import PaginatedResponse


def _curve_contract():
    prepare_apps_v1_import_namespace()
    from msm_pricing.api import Curve

    return Curve


Curve = _curve_contract()


class CurveListResponse(PaginatedResponse[Curve]):
    model_config = ConfigDict(extra="ignore")


class CurveDeleteStorageCleanup(BaseModel):
    model_config = ConfigDict(extra="ignore")

    data_node_uid: UUID
    storage_table_identifier: str | None = None
    deleted_count: int = 0
    table_empty: bool | None = None


class CurveDeleteResponse(BaseModel):
    model_config = ConfigDict(extra="ignore")

    detail: str
    uid: UUID
    curve_identifier: str
    deleted_count: int = 0
    deleted_values_count: int = 0
    deleted_curve_selections_count: int = 0
    deleted_curve_building_details_count: int = 0
    delete_values: bool = False
    delete_curve_selections: bool = False
    storage_cleanups: list[CurveDeleteStorageCleanup] = Field(default_factory=list)


class CurveSelectionCurve(BaseModel):
    model_config = ConfigDict(extra="ignore")

    uid: UUID
    unique_identifier: str
    display_name: str | None = None
    curve_type: str


class CurveSelectionMarketDataSet(BaseModel):
    model_config = ConfigDict(extra="ignore")

    uid: UUID
    set_key: str | None = None
    display_name: str | None = None


class CurveSelectionSelector(BaseModel):
    model_config = ConfigDict(extra="ignore")

    type: str
    selector_key: str | None = None
    index_uid: UUID | None = None
    index_identifier: str | None = None
    display_name: str | None = None


class CurveSelection(BaseModel):
    model_config = ConfigDict(extra="ignore")

    binding_uid: UUID
    market_data_set: CurveSelectionMarketDataSet
    role_key: str
    quote_side: str | None = None
    selector: CurveSelectionSelector
    status: str
    source: str | None = None


class CurveSelectionsResponse(BaseModel):
    model_config = ConfigDict(extra="ignore")

    curve: CurveSelectionCurve
    count: int
    results: list[CurveSelection]


class DiscountCurveNode(BaseModel):
    model_config = ConfigDict(extra="forbid")

    days_to_maturity: int
    zero: float


class DiscountCurveMarketDataSet(BaseModel):
    model_config = ConfigDict(extra="ignore")

    uid: UUID
    set_key: str
    display_name: str


class DiscountCurveBinding(BaseModel):
    model_config = ConfigDict(extra="ignore")

    uid: UUID
    concept_key: str
    data_node_uid: UUID
    storage_table_identifier: str | None = None


class DiscountCurveResponse(BaseModel):
    model_config = ConfigDict(extra="ignore")

    curve_uid: UUID
    curve_identifier: str
    curve: dict[str, Any]
    market_data_set: DiscountCurveMarketDataSet
    binding: DiscountCurveBinding
    valuation_date: dt.datetime | None = None
    effective_date: dt.datetime
    request_mode: str
    nodes: list[DiscountCurveNode]
    key_nodes: Any | None = None
    metadata_json: dict[str, Any] | None = None
