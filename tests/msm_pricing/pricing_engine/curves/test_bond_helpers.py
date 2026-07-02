from __future__ import annotations

# ruff: noqa: E402

import datetime as dt

import pytest

ql = pytest.importorskip("QuantLib")

from msm_pricing.pricing_engine.curves import (
    FixedRateBondHelperSpec,
    ZeroCouponBondHelperSpec,
    build_fixed_rate_bond_helper,
    build_zero_coupon_bond_helper,
    helper_specs_from_key_nodes,
    normalize_bond_price_value,
)


def test_normalize_bond_price_value_scales_price_per_100() -> None:
    assert normalize_bond_price_value(
        98.5,
        "price_per_100",
        face_value=10.0,
    ) == pytest.approx(9.85)
    assert normalize_bond_price_value(
        98.5,
        "price_per_face",
        face_value=10.0,
    ) == pytest.approx(98.5)


def test_build_zero_coupon_bond_helper_from_generic_spec() -> None:
    helper = build_zero_coupon_bond_helper(
        ZeroCouponBondHelperSpec(
            quote=97.5,
            quote_type="clean_price",
            quote_unit="price_per_100",
            settlement_days=0,
            calendar="TARGET",
            face_value=100.0,
            maturity_date=dt.date(2026, 7, 2),
            payment_convention="Following",
            issue_date=dt.date(2026, 1, 2),
        )
    )

    assert helper.quote().value() == pytest.approx(97.5)
    assert helper.maturityDate() == ql.Date(2, 7, 2026)
    assert helper.pillarDate() == ql.Date(2, 7, 2026)


def test_build_fixed_rate_bond_helper_from_generic_spec() -> None:
    helper = build_fixed_rate_bond_helper(
        FixedRateBondHelperSpec(
            quote=99.0,
            quote_type="clean_price",
            quote_unit="price_per_100",
            coupon_rate=0.05,
            issue_date=dt.date(2026, 1, 2),
            maturity_date=dt.date(2027, 1, 2),
            tenor="6M",
            settlement_days=0,
            face_value=100.0,
            calendar="TARGET",
            day_counter="Actual360",
            payment_convention="Following",
            business_day_convention="Following",
        )
    )

    assert helper.quote().value() == pytest.approx(99.0)
    assert helper.maturityDate() == ql.Date(4, 1, 2027)
    assert helper.pillarDate() == ql.Date(4, 1, 2027)


def test_helper_specs_from_key_nodes_maps_bond_helper_nodes() -> None:
    specs = helper_specs_from_key_nodes(
        [
            {
                "helper_type": "zero_coupon_bond_helper",
                "quote": 97.5,
                "quote_type": "clean_price",
                "quote_unit": "price_per_100",
                "maturity_date": "2026-07-02",
                "issue_date": "2026-01-02",
                "settlement_days": 0,
                "calendar_code": "TARGET",
                "face_value": 100.0,
            },
            {
                "helper_type": "fixed_rate_bond_helper",
                "quote": 99.0,
                "quote_type": "clean_price",
                "quote_unit": "price_per_100",
                "coupon_rate": 0.05,
                "issue_date": "2026-01-02",
                "maturity_date": "2027-01-02",
                "tenor": "6M",
                "settlement_days": 0,
                "calendar_code": "TARGET",
                "face_value": 100.0,
                "day_counter_code": "Actual360",
            },
        ]
    )

    assert isinstance(specs[0], ZeroCouponBondHelperSpec)
    assert specs[0].quote == pytest.approx(97.5)
    assert isinstance(specs[1], FixedRateBondHelperSpec)
    assert specs[1].coupon_rate == pytest.approx(0.05)

