from __future__ import annotations

import datetime as dt

from apps.v1.runtime_bootstrap import ensure_apps_v1_pricing_runtime
from apps.v1.schemas.common import FrontEndDetailSummary
from apps.v1.schemas.pricing_curves import (
    Curve,
    CurveSelectionsResponse,
    DiscountCurveResponse,
)


def list_pricing_curves(
    *,
    limit: int,
    offset: int,
    search: str | None = None,
    curve_type: str | None = None,
    source: str | None = None,
) -> dict:
    ensure_apps_v1_pricing_runtime()
    return Curve.list(
        limit=limit,
        offset=offset,
        search=search,
        curve_type=curve_type,
        source=source,
    )


def get_pricing_curve_summary(*, uid: str) -> FrontEndDetailSummary | None:
    ensure_apps_v1_pricing_runtime()
    summary = _get_curve_frontend_detail_summary(uid)
    if summary is None:
        return None
    return FrontEndDetailSummary.model_validate(summary)


def list_pricing_curve_selections(*, uid: str) -> CurveSelectionsResponse | None:
    ensure_apps_v1_pricing_runtime()
    response = _list_curve_selections(uid)
    if response is None:
        return None
    return CurveSelectionsResponse.model_validate(response)


def get_pricing_curve_discount_curve(
    *,
    uid: str,
    market_data_set: str,
    valuation_date: dt.datetime | None = None,
) -> DiscountCurveResponse | None:
    ensure_apps_v1_pricing_runtime()
    response = _get_curve_discount_curve_nodes(
        uid=uid,
        market_data_set=market_data_set,
        valuation_date=valuation_date,
    )
    if response is None:
        return None
    return DiscountCurveResponse.model_validate(response)


def _get_curve_frontend_detail_summary(uid: str):
    return Curve.get_frontend_detail_summary(uid)


def _list_curve_selections(uid: str):
    return Curve.list_curve_selections(uid)


def _get_curve_discount_curve_nodes(**kwargs):
    return Curve.get_discount_curve_nodes(**kwargs)
