from __future__ import annotations

import datetime as dt
from typing import Any
from uuid import UUID

from pydantic import BaseModel
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
