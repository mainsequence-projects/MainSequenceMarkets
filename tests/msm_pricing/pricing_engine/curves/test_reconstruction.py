from __future__ import annotations

# ruff: noqa: E402

import datetime as dt
import uuid

import pytest

ql = pytest.importorskip("QuantLib")

from msm_pricing.api import Curve, CurveBuildingDetails
from msm_pricing.pricing_engine.curves import (
    OISRateHelperSpec,
    OvernightDepositHelperSpec,
    curve_observation_value,
    export_curve_observation_nodes,
    helper_specs_from_key_nodes,
    ql_period_from_tenor,
    reconstruct_curve_handle_from_helper_specs,
)
from msm_pricing.pricing_engine.resolvers import build_curve_from_curve_observation
from msm_pricing.scenarios.curves.engine import build_scenario_curve_handle
from msm_pricing.scenarios.curves.models import CurveBumpSpec


def _curve(curve_uid: uuid.UUID | None = None) -> Curve:
    return Curve(
        uid=curve_uid or uuid.uuid4(),
        unique_identifier="USD-OVERNIGHT-DISCOUNT",
        display_name="USD Overnight Discount",
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


def _key_nodes() -> list[dict[str, object]]:
    return [
        {
            "helper_type": "overnight_deposit_helper",
            "quote": 4.75,
            "quote_type": "deposit_rate",
            "quote_unit": "percent",
            "tenor": "1D",
            "fixing_days": 0,
            "calendar_code": "TARGET",
            "business_day_convention": "Following",
            "day_counter_code": "Actual360",
        },
        {
            "helper_type": "ois_rate_helper",
            "quote": 4.80,
            "quote_type": "par_swap_rate",
            "quote_unit": "percent",
            "tenor": "1Y",
            "settlement_days": 2,
            "floating_index": "USD-OVERNIGHT",
        },
    ]


def test_ql_period_from_tenor_is_strict() -> None:
    assert ql_period_from_tenor("13M").length() == 13

    with pytest.raises(ValueError, match="Unsupported tenor"):
        ql_period_from_tenor("bad")


def test_helper_specs_from_key_nodes_require_explicit_overnight_index() -> None:
    with pytest.raises(ValueError, match="overnight_index"):
        helper_specs_from_key_nodes(_key_nodes())


def test_helper_specs_from_key_nodes_require_explicit_quote_units() -> None:
    key_nodes = _key_nodes()
    del key_nodes[0]["quote_unit"]

    with pytest.raises(ValueError, match="quote_unit"):
        helper_specs_from_key_nodes(key_nodes, overnight_index=ql.Sofr())


def test_reconstruct_curve_handle_from_helper_specs() -> None:
    valuation_date = dt.datetime(2026, 1, 2, tzinfo=dt.UTC)
    specs = (
        OvernightDepositHelperSpec(quote=0.0475, tenor="1D"),
        OISRateHelperSpec(
            quote=0.0480,
            tenor="1Y",
            settlement_days=2,
            overnight_index=ql.Sofr(),
        ),
    )

    handle = reconstruct_curve_handle_from_helper_specs(
        specs,
        valuation_date=valuation_date,
        day_counter=ql.Actual360(),
    )

    assert handle.discount(ql.Date(2, 1, 2027)) > 0.0


def test_build_curve_from_observation_supports_rate_helper_build_details() -> None:
    curve = _curve()
    valuation_date = dt.datetime(2026, 1, 2, tzinfo=dt.UTC)

    handle = build_curve_from_curve_observation(
        curve=curve,
        building_details=_rate_helper_details(curve.uid),
        observation={"time_index": valuation_date, "key_nodes": _key_nodes()},
        effective_curve_date=valuation_date,
        overnight_index=ql.Sofr(),
    )

    assert handle.discount(ql.Date(2, 1, 2027)) > 0.0


def test_build_curve_from_observation_supports_rate_helper_bootstrap_alias() -> None:
    curve = _curve()
    valuation_date = dt.datetime(2026, 1, 2, tzinfo=dt.UTC)
    details = _rate_helper_details(curve.uid).model_copy(
        update={"builder_type": "rate_helper_bootstrap"}
    )

    handle = build_curve_from_curve_observation(
        curve=curve,
        building_details=details,
        observation={"time_index": valuation_date, "key_nodes": _key_nodes()},
        effective_curve_date=valuation_date,
        overnight_index=ql.Sofr(),
    )

    assert handle.discount(ql.Date(2, 1, 2027)) > 0.0


def test_export_curve_observation_nodes_from_reconstructed_handle() -> None:
    valuation_date = dt.datetime(2026, 1, 2, tzinfo=dt.UTC)
    handle = reconstruct_curve_handle_from_helper_specs(
        (
            OvernightDepositHelperSpec(quote=0.0475, tenor="1D"),
            OISRateHelperSpec(
                quote=0.0480,
                tenor="1Y",
                settlement_days=2,
                overnight_index=ql.Sofr(),
            ),
        ),
        valuation_date=valuation_date,
        day_counter=ql.Actual360(),
    )

    nodes = export_curve_observation_nodes(
        handle,
        valuation_date=valuation_date,
        node_days=[1, 365],
        include_pillar_dates=False,
    )

    assert [node["days_to_maturity"] for node in nodes] == [1, 365]
    assert nodes[1]["zero"] > 0.0
    assert curve_observation_value(
        handle,
        maturity_date=ql.Date(2, 1, 2027),
    ) == pytest.approx(nodes[1]["zero"])


def test_build_scenario_curve_handle_reconstructs_helper_key_nodes_without_mutation() -> None:
    curve = _curve()
    valuation_date = dt.datetime(2026, 1, 2, tzinfo=dt.UTC)
    original_key_nodes = _key_nodes()

    handle = build_scenario_curve_handle(
        curve=curve,
        building_details=_rate_helper_details(curve.uid),
        observation={"time_index": valuation_date, "key_nodes": original_key_nodes},
        bump_spec=CurveBumpSpec(parallel_bp=10.0),
        effective_curve_date=valuation_date,
        overnight_index=ql.Sofr(),
    )

    assert handle.discount(ql.Date(2, 1, 2027)) > 0.0
    assert original_key_nodes[1]["quote"] == 4.80


def test_build_rate_helpers_rejects_empty_vectors() -> None:
    with pytest.raises(ValueError, match="At least one"):
        reconstruct_curve_handle_from_helper_specs(
            (),
            valuation_date=dt.datetime(2026, 1, 2, tzinfo=dt.UTC),
            day_counter=ql.Actual360(),
        )
