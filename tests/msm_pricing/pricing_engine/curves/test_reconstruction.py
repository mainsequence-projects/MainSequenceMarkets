from __future__ import annotations

# ruff: noqa: E402

import datetime as dt
import uuid

import pytest

ql = pytest.importorskip("QuantLib")

from msm_pricing.api import Curve, CurveBuildingDetails
from msm_pricing.pricing_engine.curves import (
    CurveKeyNodeSourceReference,
    CurveObservationExportConfig,
    InterestRateFutureHelperKeyNode,
    InterestRateFutureHelperSpec,
    OISRateHelperKeyNode,
    OISRateHelperSpec,
    OvernightDepositHelperSpec,
    build_interest_rate_future_helper,
    build_ois_rate_helper,
    curve_observation_value,
    export_curve_observation_nodes,
    helper_specs_from_key_nodes,
    ql_period_from_tenor,
    reconstruct_curve_handle_from_helper_specs,
    reconstruct_curve_term_structure_from_helper_specs,
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
            "source_reference": {
                "type": "index",
                "identifier": "USD-OVERNIGHT-DEPOSIT-1D",
            },
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
            "source_reference": {
                "type": "index",
                "identifier": "USD-OVERNIGHT-OIS-1Y",
            },
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


def test_fixed_income_rate_key_nodes_accept_index_sources() -> None:
    ois_node = OISRateHelperKeyNode.model_validate(_key_nodes()[1])
    future_node = InterestRateFutureHelperKeyNode.model_validate(
        {
            "source_reference": {
                "type": "index",
                "identifier": "CME-SOFR-JUN-2026",
            },
            "helper_type": "sofr_future_rate_helper",
            "quote": 95.25,
            "quote_type": "futures_price",
            "quote_unit": "price",
            "reference_month": "JUN",
            "reference_year": 2026,
            "reference_frequency": "Monthly",
        }
    )

    assert ois_node.source_reference == CurveKeyNodeSourceReference(
        type="index",
        identifier="USD-OVERNIGHT-OIS-1Y",
    )
    assert future_node.source_reference == CurveKeyNodeSourceReference(
        type="index",
        identifier="CME-SOFR-JUN-2026",
    )
    assert "floating_index" not in InterestRateFutureHelperKeyNode.model_fields


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


def test_build_ois_rate_helper_supports_extended_schedule_fields() -> None:
    previous_evaluation_date = ql.Settings.instance().evaluationDate
    ql.Settings.instance().evaluationDate = ql.Date(30, 6, 2026)
    try:
        helper = build_ois_rate_helper(
            OISRateHelperSpec(
                quote=0.065256,
                tenor="28D",
                overnight_index=ql.Sofr(),
                settlement_days=1,
                payment_convention="ModifiedFollowing",
                payment_frequency="EveryFourthWeek",
                payment_calendar="TARGET",
                fixed_payment_frequency="EveryFourthWeek",
                fixed_calendar="TARGET",
                averaging_method="Compound",
            )
        )
        earliest_date = helper.earliestDate()
        maturity_date = helper.maturityDate()
        pillar_date = helper.pillarDate()
    finally:
        ql.Settings.instance().evaluationDate = previous_evaluation_date

    assert earliest_date == ql.Date(1, 7, 2026)
    assert maturity_date == ql.Date(29, 7, 2026)
    assert pillar_date == ql.Date(29, 7, 2026)


def test_build_interest_rate_future_helper_supports_sofr_future_family() -> None:
    helper = build_interest_rate_future_helper(
        InterestRateFutureHelperSpec(
            quote=95.25,
            reference_month="JUN",
            reference_year=2026,
            reference_frequency="Monthly",
        )
    )

    assert helper.earliestDate() == ql.Date(1, 6, 2026)
    assert helper.maturityDate() == ql.Date(1, 7, 2026)
    assert helper.pillarDate() == ql.Date(1, 7, 2026)
    assert helper.quote().value() == pytest.approx(95.25)


def test_reconstruct_curve_handle_from_helper_specs_supports_sofr_future() -> None:
    valuation_date = dt.datetime(2026, 1, 2, tzinfo=dt.UTC)
    handle = reconstruct_curve_handle_from_helper_specs(
        (
            OvernightDepositHelperSpec(quote=0.0475, tenor="1D"),
            InterestRateFutureHelperSpec(
                quote=95.25,
                reference_month="JUN",
                reference_year=2026,
                reference_frequency="Monthly",
            ),
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

    assert handle.discount(ql.Date(2, 1, 2027)) > 0.0


def test_helper_specs_from_key_nodes_maps_extended_ois_fields() -> None:
    specs = helper_specs_from_key_nodes(
        [
            {
                "helper_type": "ois_rate_helper",
                "quote": 6.5256,
                "quote_type": "par_swap_rate",
                "quote_unit": "percent",
                "tenor": "28D",
                "settlement_days": 1,
                "floating_index": "OVERNIGHT-INDEX",
                "payment_convention": "ModifiedFollowing",
                "fixed_payment_frequency": "EveryFourthWeek",
                "fixed_calendar_code": "TARGET",
                "averaging_method": "Compound",
            }
        ],
        overnight_index=ql.Sofr(),
    )

    spec = specs[0]
    assert isinstance(spec, OISRateHelperSpec)
    assert spec.quote == pytest.approx(0.065256)
    assert spec.payment_frequency == "EveryFourthWeek"
    assert spec.payment_calendar == "TARGET"
    assert spec.fixed_payment_frequency == "EveryFourthWeek"
    assert spec.fixed_calendar == "TARGET"
    assert spec.payment_convention == "ModifiedFollowing"


def test_helper_specs_from_key_nodes_maps_sofr_future_price_fields() -> None:
    specs = helper_specs_from_key_nodes(
        [
            {
                "helper_type": "sofr_future_rate_helper",
                "quote": 95.25,
                "quote_type": "futures_price",
                "quote_unit": "price",
                "reference_month": "JUN",
                "reference_year": 2026,
                "reference_frequency": "Monthly",
                "convexity_adjustment": 0.0001,
            }
        ]
    )

    spec = specs[0]
    assert isinstance(spec, InterestRateFutureHelperSpec)
    assert spec.quote == pytest.approx(95.25)
    assert spec.reference_month == "JUN"
    assert spec.reference_year == 2026
    assert spec.reference_frequency == "Monthly"
    assert spec.future_family == "sofr"
    assert spec.convexity_adjustment == pytest.approx(0.0001)


def test_helper_specs_from_key_nodes_rejects_future_without_price_unit() -> None:
    with pytest.raises(ValueError, match="price unit"):
        helper_specs_from_key_nodes(
            [
                {
                    "helper_type": "sofr_future_rate_helper",
                    "quote": 95.25,
                    "quote_type": "futures_price",
                    "quote_unit": "percent",
                    "reference_month": "JUN",
                    "reference_year": 2026,
                    "reference_frequency": "Monthly",
                }
            ]
        )


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


def test_rate_helper_build_details_require_helper_schema() -> None:
    curve = _curve()
    valuation_date = dt.datetime(2026, 1, 2, tzinfo=dt.UTC)
    details = _rate_helper_details(curve.uid).model_copy(update={"builder_payload": None})

    with pytest.raises(ValueError, match="helper_schema='rate_helpers@v1'"):
        build_curve_from_curve_observation(
            curve=curve,
            building_details=details,
            observation={"time_index": valuation_date, "key_nodes": _key_nodes()},
            effective_curve_date=valuation_date,
            overnight_index=ql.Sofr(),
        )


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


def test_curve_observation_export_config_from_building_details_normalizes_runtime_output() -> None:
    details = _rate_helper_details(uuid.uuid4()).model_copy(
        update={
            "quote_convention": "helper_quote",
            "rate_unit": "helper_unit",
            "compounding": "compounded_annual",
            "builder_payload": {
                "helper_schema": "rate_helpers@v1",
                "output_quote_convention": "zero_rate",
                "output_rate_unit": "decimal",
            },
        }
    )

    config = CurveObservationExportConfig.from_curve_building_details(details)

    assert config.quote_convention == "zero_rate"
    assert config.rate_unit == "decimal"
    assert config.day_counter_code == "Actual360"
    assert config.compounding == "compounded"
    assert config.compounding_frequency == "annual"


def test_export_curve_observation_nodes_supports_front_days_and_compounded_annual() -> None:
    valuation_date = dt.datetime(2026, 1, 2, tzinfo=dt.UTC)
    term_structure = reconstruct_curve_term_structure_from_helper_specs(
        (
            OvernightDepositHelperSpec(quote=0.0475, tenor="1D"),
            InterestRateFutureHelperSpec(
                quote=95.25,
                reference_month="JUN",
                reference_year=2026,
                reference_frequency="Monthly",
            ),
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
    config = CurveObservationExportConfig(
        quote_convention="zero_rate",
        rate_unit="decimal",
        day_counter_code="Actual360",
        compounding="compounded",
        compounding_frequency="annual",
    )

    nodes = export_curve_observation_nodes(
        term_structure,
        valuation_date=valuation_date,
        node_days=[1],
        include_pillar_dates=True,
        config=config,
    )

    days = [int(node["days_to_maturity"]) for node in nodes]
    assert 1 in days
    assert 180 in days
    day_180 = next(node for node in nodes if node["days_to_maturity"] == 180)
    expected = curve_observation_value(
        term_structure,
        valuation_date=valuation_date,
        maturity_date=dt.date(2026, 7, 1),
        config=config,
    )
    assert day_180["zero"] == pytest.approx(expected)


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
