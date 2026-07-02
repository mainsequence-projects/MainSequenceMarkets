from __future__ import annotations

# ruff: noqa: E402

import datetime as dt
import uuid

import pytest

ql = pytest.importorskip("QuantLib")

from msm_pricing.api import Curve, CurveBuildingDetails
from msm_pricing.pricing_engine.curves import (
    export_curve_observation_nodes,
    reconstruct_curve_handle_from_key_nodes,
)
from msm_pricing.pricing_engine.resolvers import build_curve_from_curve_observation
from msm_pricing.scenarios.curves.engine import build_scenario_curve_handle
from msm_pricing.scenarios.curves.models import CurveBumpSpec


def _curve(curve_uid: uuid.UUID | None = None) -> Curve:
    return Curve(
        uid=curve_uid or uuid.uuid4(),
        unique_identifier="GENERIC-BOND-HELPER-DISCOUNT",
        display_name="Generic Bond Helper Discount",
        curve_type="discount",
    )


def _rate_helper_details(curve_uid: uuid.UUID) -> CurveBuildingDetails:
    return CurveBuildingDetails(
        curve_uid=curve_uid,
        builder_type="rate_helper_curve",
        quote_convention="helper_quote",
        rate_unit="decimal",
        day_counter_code="Actual360",
        calendar_code="TARGET",
        interpolation_method="log_linear_discount",
        compounding="simple",
        extrapolation_policy="enabled",
        bootstrap_method="piecewise_log_linear_discount",
        builder_payload={"helper_schema": "rate_helpers@v1"},
    )


def _bond_key_nodes() -> list[dict[str, object]]:
    return [
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
            "yield": 0.05,
            "yield_unit": "decimal",
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
            "yield": 0.052,
            "yield_unit": "decimal",
        },
    ]


def test_reconstruct_curve_handle_from_bond_helper_key_nodes() -> None:
    valuation_date = dt.datetime(2026, 1, 2, tzinfo=dt.UTC)

    handle = reconstruct_curve_handle_from_key_nodes(
        _bond_key_nodes(),
        valuation_date=valuation_date,
        day_counter=ql.Actual360(),
    )

    assert handle.discount(ql.Date(2, 1, 2027)) > 0.0


def test_build_curve_from_observation_supports_bond_helper_build_details() -> None:
    curve = _curve()
    valuation_date = dt.datetime(2026, 1, 2, tzinfo=dt.UTC)

    handle = build_curve_from_curve_observation(
        curve=curve,
        building_details=_rate_helper_details(curve.uid),
        observation={"time_index": valuation_date, "key_nodes": _bond_key_nodes()},
        effective_curve_date=valuation_date,
    )

    assert handle.discount(ql.Date(2, 1, 2027)) > 0.0


def test_export_curve_observation_nodes_from_bond_helper_curve() -> None:
    valuation_date = dt.datetime(2026, 1, 2, tzinfo=dt.UTC)
    handle = reconstruct_curve_handle_from_key_nodes(
        _bond_key_nodes(),
        valuation_date=valuation_date,
        day_counter=ql.Actual360(),
    )

    nodes = export_curve_observation_nodes(
        handle,
        valuation_date=valuation_date,
        node_days=[181, 365],
        include_pillar_dates=False,
    )

    assert [node["days_to_maturity"] for node in nodes] == [181, 365]
    assert nodes[0]["zero"] > 0.0
    assert nodes[1]["zero"] > 0.0


def test_bond_helper_scenario_noop_reconstructs_without_mutation() -> None:
    curve = _curve()
    valuation_date = dt.datetime(2026, 1, 2, tzinfo=dt.UTC)
    key_nodes = _bond_key_nodes()

    handle = build_scenario_curve_handle(
        curve=curve,
        building_details=_rate_helper_details(curve.uid),
        observation={"time_index": valuation_date, "key_nodes": key_nodes},
        bump_spec=CurveBumpSpec(),
        effective_curve_date=valuation_date,
    )

    assert handle.discount(ql.Date(2, 1, 2027)) > 0.0
    assert key_nodes[1]["yield"] == pytest.approx(0.052)


def test_bond_helper_scenario_yield_shock_requires_price_conversion() -> None:
    curve = _curve()
    valuation_date = dt.datetime(2026, 1, 2, tzinfo=dt.UTC)

    with pytest.raises(ValueError, match="yield-to-price conversion"):
        build_scenario_curve_handle(
            curve=curve,
            building_details=_rate_helper_details(curve.uid),
            observation={"time_index": valuation_date, "key_nodes": _bond_key_nodes()},
            bump_spec=CurveBumpSpec(parallel_bp=10.0),
            effective_curve_date=valuation_date,
        )

