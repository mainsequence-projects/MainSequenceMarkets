from __future__ import annotations

# ruff: noqa: E402

import datetime as dt
import uuid

import pytest

ql = pytest.importorskip("QuantLib")

from msm_pricing.api import Curve, CurveBuildingDetails
from msm_pricing.instruments.json_codec import calendar_from_json
from msm_pricing.pricing_engine.curves import (
    ConstNotionalCrossCurrencyBasisSwapRateHelperSpec,
    FxSwapRateHelperSpec,
    MissingRateHelperDependencyError,
    StaticRateHelperRuntimeResolver,
    build_const_notional_cross_currency_basis_swap_rate_helper,
    build_fx_swap_rate_helper,
    helper_specs_from_key_nodes,
    key_node_basis_spread,
    key_node_decimal_rate,
    key_node_fx_forward_points,
    key_nodes_contain_rate_helpers,
    reconstruct_curve_result_from_key_nodes,
)
from msm_pricing.pricing_engine.resolvers import build_curve_from_curve_observation
from msm_pricing.scenarios.curves.engine import build_scenario_curve_handle
from msm_pricing.scenarios.curves.models import CurveBumpSpec


def _valuation_date() -> dt.datetime:
    return dt.datetime(2026, 1, 2, tzinfo=dt.UTC)


def _collateral_handle() -> ql.YieldTermStructureHandle:
    valuation_date = ql.Date(2, 1, 2026)
    return ql.YieldTermStructureHandle(ql.FlatForward(valuation_date, 0.03, ql.Actual360()))


def _runtime_resolver() -> StaticRateHelperRuntimeResolver:
    handle = _collateral_handle()
    return StaticRateHelperRuntimeResolver(
        yield_curves={"GENERIC-COLLATERAL": handle},
        indexes={
            "BASE-OVERNIGHT": ql.OvernightIndex(
                "BASE-ON",
                0,
                ql.USDCurrency(),
                ql.TARGET(),
                ql.Actual360(),
                handle,
            ),
            "QUOTE-OVERNIGHT": ql.OvernightIndex(
                "QUOTE-ON",
                0,
                ql.EURCurrency(),
                ql.TARGET(),
                ql.Actual360(),
                handle,
            ),
        },
    )


def _cross_currency_key_nodes() -> list[dict[str, object]]:
    return [
        {
            "source_reference": {
                "type": "index",
                "identifier": "BASE-QUOTE-SPOT",
            },
            "helper_type": "fx_spot",
            "quote": 1.1,
            "quote_type": "fx_spot",
            "quote_unit": "quote_per_base",
            "fx_pair": "BASE/QUOTE",
            "fx_base_currency": "BASE",
            "fx_quote_currency": "QUOTE",
        },
        {
            "source_reference": {
                "type": "index",
                "identifier": "BASE-QUOTE-FX-SWAP-1M",
            },
            "helper_type": "fx_swap_rate_helper",
            "quote": 0.001,
            "quote_type": "fx_forward_points",
            "quote_unit": "quote_per_base",
            "tenor": "1M",
            "fixing_days": 2,
            "calendar_code": "TARGET",
            "business_day_convention": "ModifiedFollowing",
            "end_of_month": False,
            "fx_pair": "BASE/QUOTE",
            "fx_base_currency": "BASE",
            "fx_quote_currency": "QUOTE",
            "is_fx_base_currency_collateral_currency": True,
            "collateral_curve": "GENERIC-COLLATERAL",
        },
        {
            "source_reference": {
                "type": "index",
                "identifier": "BASE-QUOTE-XCCY-BASIS-1Y",
            },
            "helper_type": "const_notional_cross_currency_basis_swap_rate_helper",
            "quote": 1.0,
            "quote_type": "basis_spread",
            "quote_unit": "basis_points",
            "tenor": "1Y",
            "fixing_days": 2,
            "calendar_code": "TARGET",
            "business_day_convention": "ModifiedFollowing",
            "end_of_month": False,
            "base_currency_index": "BASE-OVERNIGHT",
            "quote_currency_index": "QUOTE-OVERNIGHT",
            "collateral_curve": "GENERIC-COLLATERAL",
            "is_fx_base_currency_collateral_currency": True,
            "is_basis_on_fx_base_currency_leg": True,
            "payment_frequency": "Annual",
            "payment_lag": 0,
        },
    ]


def _rate_helper_details(
    curve_uid: uuid.UUID,
    helper_schema: str = "rate_helpers@v1",
) -> CurveBuildingDetails:
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
        builder_payload={"helper_schema": helper_schema},
    )


def test_cross_currency_quote_normalizers_are_explicit() -> None:
    assert key_node_fx_forward_points(
        {
            "quote": 10.0,
            "quote_type": "fx_forward_points",
            "quote_unit": "raw_points",
            "point_scale": 10000,
        }
    ) == pytest.approx(0.001)
    assert key_node_basis_spread(
        {"quote": 1.0, "quote_type": "basis_spread", "quote_unit": "basis_points"}
    ) == pytest.approx(0.0001)

    with pytest.raises(ValueError, match="supported explicit rate"):
        key_node_decimal_rate(
            {
                "quote": 0.001,
                "quote_type": "fx_forward_points",
                "quote_unit": "quote_per_base",
            }
        )


def test_joint_calendar_json_decodes_nested_calendars() -> None:
    calendar = calendar_from_json(
        {
            "name": "JointCalendar",
            "calendars": [{"name": "TARGET"}, {"name": "NullCalendar"}],
            "rule": "JoinHolidays",
        }
    )

    assert "JoinHolidays" in calendar.name()


def test_build_fx_swap_rate_helper_from_generic_spec() -> None:
    ql.Settings.instance().evaluationDate = ql.Date(2, 1, 2026)
    helper = build_fx_swap_rate_helper(
        FxSwapRateHelperSpec(
            forward_points=0.001,
            spot=1.1,
            tenor="1M",
            fixing_days=2,
            calendar="TARGET",
            convention="ModifiedFollowing",
            end_of_month=False,
            is_fx_base_currency_collateral_currency=True,
            collateral_curve=_collateral_handle(),
        )
    )

    assert helper.quote().value() == pytest.approx(0.001)
    assert helper.maturityDate() == ql.Date(6, 2, 2026)


def test_build_const_notional_cross_currency_basis_helper_from_generic_spec() -> None:
    ql.Settings.instance().evaluationDate = ql.Date(2, 1, 2026)
    resolver = _runtime_resolver()
    helper = build_const_notional_cross_currency_basis_swap_rate_helper(
        ConstNotionalCrossCurrencyBasisSwapRateHelperSpec(
            basis=0.0001,
            tenor="1Y",
            fixing_days=2,
            calendar="TARGET",
            convention="ModifiedFollowing",
            end_of_month=False,
            base_currency_index=resolver.resolve_index("BASE-OVERNIGHT", {}),
            quote_currency_index=resolver.resolve_index("QUOTE-OVERNIGHT", {}),
            collateral_curve=resolver.resolve_yield_curve("GENERIC-COLLATERAL", {}),
            is_fx_base_currency_collateral_currency=True,
            is_basis_on_fx_base_currency_leg=True,
            payment_frequency="Annual",
        )
    )

    assert helper.quote().value() == pytest.approx(0.0001)
    assert helper.maturityDate() == ql.Date(6, 1, 2027)


def test_helper_specs_from_key_nodes_maps_cross_currency_context_and_helpers() -> None:
    specs = helper_specs_from_key_nodes(
        _cross_currency_key_nodes(),
        helper_runtime_resolver=_runtime_resolver(),
    )

    assert isinstance(specs[0], FxSwapRateHelperSpec)
    assert specs[0].forward_points == pytest.approx(0.001)
    assert specs[0].spot == pytest.approx(1.1)
    assert isinstance(specs[1], ConstNotionalCrossCurrencyBasisSwapRateHelperSpec)
    assert specs[1].basis == pytest.approx(0.0001)
    assert key_nodes_contain_rate_helpers(_cross_currency_key_nodes())


def test_rate_helpers_v1_accepts_cross_currency_context_nodes() -> None:
    specs = helper_specs_from_key_nodes(
        _cross_currency_key_nodes(),
        helper_schema="rate_helpers@v1",
        helper_runtime_resolver=_runtime_resolver(),
    )

    assert len(specs) == 2
    assert isinstance(specs[0], FxSwapRateHelperSpec)
    assert isinstance(specs[1], ConstNotionalCrossCurrencyBasisSwapRateHelperSpec)


def test_cross_currency_helper_nodes_require_runtime_resolver() -> None:
    with pytest.raises(MissingRateHelperDependencyError, match="helper_runtime_resolver"):
        helper_specs_from_key_nodes(_cross_currency_key_nodes())


def test_fx_swap_helper_requires_inline_or_context_spot() -> None:
    key_nodes = _cross_currency_key_nodes()[1:]

    with pytest.raises(MissingRateHelperDependencyError, match="inline spot"):
        helper_specs_from_key_nodes(
            key_nodes,
            helper_runtime_resolver=_runtime_resolver(),
        )


def test_reconstruct_curve_result_from_cross_currency_key_nodes() -> None:
    result = reconstruct_curve_result_from_key_nodes(
        _cross_currency_key_nodes(),
        valuation_date=_valuation_date(),
        day_counter="Actual360",
        helper_runtime_resolver=_runtime_resolver(),
    )

    assert len(result.helpers) == 2
    assert len(result.context_nodes) == 1
    assert result.term_structure.discount(ql.Date(2, 1, 2027)) > 0.0
    assert abs(result.helper_quote_errors[0]) < 1e-10
    assert abs(result.helper_quote_errors[1]) < 1e-10


def test_build_curve_observation_supports_rate_helpers_v1_context_nodes() -> None:
    curve = Curve(
        uid=uuid.uuid4(),
        unique_identifier="GENERIC-XCCY-HELPER-DISCOUNT",
        display_name="Generic XCCY Helper Discount",
        curve_type="discount",
    )

    handle = build_curve_from_curve_observation(
        curve=curve,
        building_details=_rate_helper_details(curve.uid),
        observation={"time_index": _valuation_date(), "key_nodes": _cross_currency_key_nodes()},
        effective_curve_date=_valuation_date(),
        helper_runtime_resolver=_runtime_resolver(),
    )

    assert handle.discount(ql.Date(2, 1, 2027)) > 0.0


def test_scenario_curve_handle_forwards_cross_currency_runtime_resolver() -> None:
    curve = Curve(
        uid=uuid.uuid4(),
        unique_identifier="GENERIC-XCCY-HELPER-DISCOUNT",
        display_name="Generic XCCY Helper Discount",
        curve_type="discount",
    )
    key_nodes = _cross_currency_key_nodes()

    handle = build_scenario_curve_handle(
        curve=curve,
        building_details=_rate_helper_details(curve.uid),
        observation={"time_index": _valuation_date(), "key_nodes": key_nodes},
        bump_spec=CurveBumpSpec(),
        effective_curve_date=_valuation_date(),
        helper_runtime_resolver=_runtime_resolver(),
    )

    assert handle.discount(ql.Date(2, 1, 2027)) > 0.0
    assert key_nodes[1]["quote"] == pytest.approx(0.001)


def test_connector_owned_helper_schema_is_rejected_upstream() -> None:
    curve = Curve(
        uid=uuid.uuid4(),
        unique_identifier="GENERIC-XCCY-HELPER-DISCOUNT",
        display_name="Generic XCCY Helper Discount",
        curve_type="discount",
    )

    with pytest.raises(ValueError, match="rate_helpers@v1"):
        build_curve_from_curve_observation(
            curve=curve,
            building_details=_rate_helper_details(curve.uid, "valmer_xccy_helpers@v1"),
            observation={
                "time_index": _valuation_date(),
                "key_nodes": _cross_currency_key_nodes(),
            },
            effective_curve_date=_valuation_date(),
            helper_runtime_resolver=_runtime_resolver(),
        )
