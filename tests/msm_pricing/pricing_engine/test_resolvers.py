from __future__ import annotations

# ruff: noqa: E402

import datetime as dt
import uuid

import pytest

ql = pytest.importorskip("QuantLib")

from msm.api.indices import Index
from msm_pricing.api import Curve, CurveBuildingDetails, IndexConventionDetails
from msm_pricing.api.market_data_bindings import PricingMarketDataSetCurveBinding
from msm_pricing.pricing_engine import resolvers


def _convention(index_uid: uuid.UUID) -> IndexConventionDetails:
    return IndexConventionDetails(
        index_uid=index_uid,
        index_family="overnight",
        convention_dump={
            "currency_code": "USD",
            "day_counter_code": "Actual360",
            "fixing_calendar_code": "TARGET",
            "period": "1D",
            "settlement_days": 0,
            "business_day_convention": "Following",
        },
    )


def _building_details(curve_uid: uuid.UUID) -> CurveBuildingDetails:
    return CurveBuildingDetails(
        curve_uid=curve_uid,
        builder_type="zero_rate_curve",
        quote_convention="zero_rate",
        rate_unit="decimal",
        day_counter_code="Actual360",
        calendar_code="TARGET",
        interpolation_method="log_linear_discount",
        compounding="simple",
        extrapolation_policy="enabled",
    )


def test_select_curve_uses_market_data_set_curve_binding(monkeypatch) -> None:
    index_uid = uuid.UUID("00000000-0000-0000-0000-000000000001")
    curve_uid = uuid.uuid4()
    curve = Curve(
        uid=curve_uid,
        unique_identifier="USD-SOFR-PROJECTION",
        display_name="USD SOFR Projection",
        curve_type="projection",
    )
    calls = []

    monkeypatch.setattr(
        PricingMarketDataSetCurveBinding,
        "resolve_curve_uid",
        staticmethod(
            lambda **kwargs: calls.append(("binding", kwargs)) or curve_uid
        ),
    )
    monkeypatch.setattr(
        Curve,
        "get_by_uid",
        staticmethod(lambda uid: calls.append(("curve", uid)) or curve),
    )

    selected = resolvers.select_curve(
        index_uid=index_uid,
        curve_type="projection",
        market_data_set="eod",
        quote_side="mid",
    )

    assert selected is curve
    assert calls == [
        (
            "binding",
            {
                "market_data_set": "eod",
                "role_key": "projection",
                "selector_type": "index",
                "selector_key": str(index_uid),
                "quote_side": "mid",
            },
        ),
        ("curve", curve_uid),
    ]


def test_select_curve_explicit_override_does_not_require_index_relationship(
    monkeypatch,
) -> None:
    curve = Curve(
        uid=uuid.uuid4(),
        unique_identifier="USD-OIS-DISCOUNT",
        display_name="USD OIS Discount",
        curve_type="discount",
        currency_code="USD",
    )

    monkeypatch.setattr(
        Curve,
        "get_by_unique_identifier",
        staticmethod(lambda unique_identifier: curve),
    )
    monkeypatch.setattr(
        PricingMarketDataSetCurveBinding,
        "resolve_curve_uid",
        staticmethod(lambda **_kwargs: (_ for _ in ()).throw(AssertionError("no binding"))),
    )

    selected = resolvers.select_curve(
        curve_unique_identifier="USD-OIS-DISCOUNT",
        curve_type="discount",
    )

    assert selected is curve


def test_resolve_quantlib_index_uses_curve_binding_and_build_details(monkeypatch) -> None:
    index_uid = uuid.UUID("00000000-0000-0000-0000-000000000001")
    curve_uid = uuid.uuid4()
    curve = Curve(
        uid=curve_uid,
        unique_identifier="USD-SOFR-PROJECTION",
        display_name="USD SOFR Projection",
        curve_type="projection",
    )
    calls = []

    monkeypatch.setattr(
        Index,
        "get_by_uid",
        staticmethod(
            lambda uid: (
                calls.append(("index", uid))
                or Index(
                    uid=uid,
                    unique_identifier="USD-SOFR",
                    index_type="interest_rate",
                    display_name="USD SOFR",
                )
            )
        ),
    )
    monkeypatch.setattr(
        IndexConventionDetails,
        "get_by_index_uid",
        staticmethod(lambda uid: calls.append(("convention", uid)) or _convention(uid)),
    )
    monkeypatch.setattr(
        PricingMarketDataSetCurveBinding,
        "resolve_curve_uid",
        staticmethod(
            lambda **kwargs: calls.append(("curve_binding", kwargs)) or curve_uid
        ),
    )
    monkeypatch.setattr(
        Curve,
        "get_by_uid",
        staticmethod(lambda uid: calls.append(("curve", uid)) or curve),
    )
    monkeypatch.setattr(
        CurveBuildingDetails,
        "get_by_curve_uid",
        staticmethod(
            lambda uid: calls.append(("build_details", uid)) or _building_details(uid)
        ),
    )
    monkeypatch.setattr(
        resolvers.data_interface,
        "get_historical_discount_curve",
        lambda curve_unique_identifier, target_date, *, market_data_set=None: (
            calls.append(("curve_data", curve_unique_identifier, target_date, market_data_set))
            or ([{"days_to_maturity": 1, "zero": 0.05}], target_date)
        ),
    )
    monkeypatch.setattr(
        resolvers,
        "add_historical_fixings",
        lambda target_date, ibor_index, *, reference_rate_uid, market_data_set=None: calls.append(
            ("fixings", target_date, reference_rate_uid, market_data_set)
        ),
    )

    valuation_date = dt.datetime(2026, 5, 27, tzinfo=dt.UTC)
    index = resolvers.resolve_quantlib_index(
        index_uid,
        valuation_date=valuation_date,
        hydrate_fixings=True,
        market_data_set="eod",
        quote_side="mid",
    )

    assert isinstance(index, ql.IborIndex)
    assert calls == [
        ("index", index_uid),
        ("convention", index_uid),
        (
            "curve_binding",
            {
                "market_data_set": "eod",
                "role_key": "projection",
                "selector_type": "index",
                "selector_key": str(index_uid),
                "quote_side": "mid",
            },
        ),
        ("curve", curve_uid),
        ("curve_data", "USD-SOFR-PROJECTION", valuation_date, "eod"),
        ("build_details", curve_uid),
        ("fixings", ql.Date(27, 5, 2026), "USD-SOFR", "eod"),
    ]
