from __future__ import annotations

import datetime
import uuid

import pandas as pd
import pytest
from pydantic import ValidationError

from msm.api.indices import (
    IncompleteObservationsError,
    IndexCalculationDefinition,
    IndexCalculationError,
    IndexCalculationLeg,
    LookAheadError,
    calculate_index,
    compute_definition_hash,
)
from msm.analytics.indices import resolve_index_legs, validate_calculation_contract


UTC_START = datetime.datetime(2025, 1, 1, tzinfo=datetime.UTC)


def _definition(**updates) -> IndexCalculationDefinition:
    values = {
        "uid": uuid.uuid4(),
        "effective_from": UTC_START,
        "calculation_kind": "linear_combination",
        "calculation_family": "relative_value",
        "output_unit": "usd",
        "alignment_policy": "inner",
        "missing_data_policy": "drop",
        "composition_mode": "fixed",
    }
    values.update(updates)
    return IndexCalculationDefinition(**values)


def _asset_leg(key: str, order: int, **updates) -> IndexCalculationLeg:
    values = {
        "leg_key": key,
        "leg_order": order,
        "component_kind": "asset",
        "asset_uid": uuid.uuid4(),
        "observable_code": "price",
        "input_unit": "usd",
        "coefficient_method": "fixed",
        "coefficient": 1.0,
    }
    values.update(updates)
    return IndexCalculationLeg(**values)


def _series(values, *, start: str = "2025-01-01") -> pd.Series:
    return pd.Series(values, index=pd.date_range(start, periods=len(values), tz="UTC"), dtype=float)


def test_linear_combination_normalizes_percent_and_decimal_to_basis_points() -> None:
    definition = _definition(output_unit="basis_points", calculation_family="yield_spread")
    legs = [
        _asset_leg("long", 0, observable_code="yield", input_unit="percent"),
        _asset_leg(
            "short",
            1,
            observable_code="yield",
            input_unit="decimal",
            coefficient=-1.0,
        ),
    ]

    result = calculate_index(
        definition,
        legs,
        {"long": _series([8.41]), "short": _series([0.0724])},
        index_identifier="MX_MBONOS_2S5S_YIELD_SPREAD",
    ).values

    assert result.iloc[0]["value"] == pytest.approx(117.0)
    assert result.iloc[0]["unit"] == "basis_points"
    assert result.index.names == ["time_index", "index_identifier"]
    assert str(result.reset_index()["time_index"].dtype) == "datetime64[ns, UTC]"


def test_ratio_validates_units_and_zero_denominator() -> None:
    definition = _definition(calculation_kind="ratio", output_unit="ratio")
    compatible = [_asset_leg("a", 0), _asset_leg("b", 1)]

    with pytest.raises(IndexCalculationError, match="denominator contains zero"):
        calculate_index(definition, compatible, {"a": _series([2.0]), "b": _series([0.0])})

    incompatible = [
        _asset_leg("a", 0, input_unit="usd"),
        _asset_leg("b", 1, input_unit="decimal"),
    ]
    with pytest.raises(ValueError, match="incompatible units"):
        calculate_index(
            definition,
            incompatible,
            {"a": _series([2.0]), "b": _series([1.0])},
        )


def test_rebased_basket_chained_return_and_self_financing_operators() -> None:
    basket = calculate_index(
        _definition(
            calculation_kind="rebased_basket",
            calculation_parameters_json={"base_value": 100.0},
            output_unit="index_points",
        ),
        [_asset_leg("a", 0, coefficient=0.5), _asset_leg("b", 1, coefficient=0.5)],
        {"a": _series([10.0, 11.0]), "b": _series([20.0, 18.0])},
    ).values
    assert basket["value"].tolist() == pytest.approx([100.0, 100.0])

    chained = calculate_index(
        _definition(
            calculation_kind="chained_return",
            calculation_parameters_json={"base_value": 100.0},
            output_unit="index_points",
        ),
        [_asset_leg("return", 0, observable_code="simple_return", input_unit="decimal")],
        {"return": _series([0.01, -0.02, 0.03])},
    ).values
    assert chained["value"].tolist() == pytest.approx([101.0, 98.98, 101.9494])

    strategy = calculate_index(
        _definition(
            calculation_kind="self_financing",
            calculation_parameters_json={
                "base_value": 100.0,
                "initial_capital": 100.0,
                "position_lag": 1,
                "financing_rate": 0.0,
                "transaction_cost_bps": 0.0,
            },
            output_unit="index_points",
        ),
        [_asset_leg("option", 0), _asset_leg("spot", 1, coefficient=-0.5)],
        {"option": _series([10.0, 12.0, 11.0]), "spot": _series([100.0, 102.0, 101.0])},
    ).values
    assert strategy["value"].tolist() == pytest.approx([100.0, 101.0, 100.5])


def test_crack_spread_uses_registered_physical_unit_conversion() -> None:
    result = calculate_index(
        _definition(output_unit="usd_per_barrel", calculation_family="crack_spread"),
        [
            _asset_leg("gasoline", 0, input_unit="usd_per_gallon", coefficient=2.0),
            _asset_leg("heating_oil", 1, input_unit="usd_per_gallon", coefficient=1.0),
            _asset_leg("crude", 2, input_unit="usd_per_barrel", coefficient=-3.0),
        ],
        {
            "gasoline": _series([2.0]),
            "heating_oil": _series([2.5]),
            "crude": _series([70.0]),
        },
    ).values

    assert result.iloc[0]["value"] == pytest.approx(63.0)


def test_hash_is_order_stable_and_changes_only_for_output_semantics() -> None:
    definition = _definition(metadata_json={"label": "display only"}, source="desk-a")
    legs = [_asset_leg("a", 0), _asset_leg("b", 1, coefficient=-1.0)]
    expected = compute_definition_hash(definition, legs)

    assert compute_definition_hash(definition, list(reversed(legs))) == expected
    assert (
        compute_definition_hash(
            definition.model_copy(
                update={"metadata_json": {"label": "renamed"}, "source": "desk-b"}
            ),
            legs,
        )
        == expected
    )
    assert (
        compute_definition_hash(
            definition, [legs[0], legs[1].model_copy(update={"coefficient": -2.0})]
        )
        != expected
    )
    assert (
        compute_definition_hash(
            definition.model_copy(
                update={"effective_to": datetime.datetime(2025, 2, 1, tzinfo=datetime.UTC)}
            ),
            legs,
        )
        == expected
    )
    assert (
        compute_definition_hash(
            definition.model_copy(
                update={"effective_from": datetime.datetime(2025, 1, 2, tzinfo=datetime.UTC)}
            ),
            legs,
        )
        != expected
    )


def test_alignment_missing_and_staleness_policies_are_explicit() -> None:
    times = pd.date_range("2025-01-01", periods=3, tz="UTC")
    observations = {
        "a": pd.Series([10.0, 12.0], index=times[[0, 2]]),
        "b": pd.Series([1.0, 1.0, 1.0], index=times),
    }
    legs = [_asset_leg("a", 0), _asset_leg("b", 1, coefficient=-1.0)]
    asof = calculate_index(
        _definition(
            alignment_policy="asof",
            alignment_parameters_json={"max_staleness_seconds": 172_800},
        ),
        legs,
        observations,
        calculation_times=times,
    ).values.reset_index()

    assert asof["value"].tolist() == pytest.approx([9.0, 9.0, 11.0])
    assert asof["calculation_status"].tolist() == ["ready", "stale", "ready"]

    with pytest.raises(IncompleteObservationsError, match="incomplete required observations"):
        calculate_index(
            _definition(
                alignment_policy="calendar_aligned",
                missing_data_policy="fail",
            ),
            legs,
            observations,
            calculation_times=times,
        )

    filled = calculate_index(
        _definition(
            alignment_policy="calendar_aligned",
            missing_data_policy="forward_fill",
            missing_data_parameters_json={"max_age_seconds": 172_800},
        ),
        legs,
        observations,
        calculation_times=times,
    ).values
    assert filled["value"].tolist() == pytest.approx([9.0, 9.0, 11.0])


def test_dynamic_parameter_contracts_validate_window_fallback_and_bounds() -> None:
    with pytest.raises(ValidationError, match="min_observations cannot exceed window"):
        validate_calculation_contract(
            _definition(),
            [
                _asset_leg("reference", 0),
                _asset_leg(
                    "hedge",
                    1,
                    coefficient_method="beta_neutral",
                    coefficient=None,
                    coefficient_parameters_json={
                        "window": 5,
                        "min_observations": 6,
                        "lag": 1,
                    },
                ),
            ],
        )

    definition = _definition()
    legs = [
        _asset_leg("reference", 0),
        _asset_leg(
            "hedge",
            1,
            coefficient_method="beta_neutral",
            coefficient=None,
            coefficient_parameters_json={
                "window": 3,
                "min_observations": 3,
                "lag": 1,
                "fallback_policy": "fail",
            },
        ),
    ]
    with pytest.raises(IncompleteObservationsError, match="could not resolve every"):
        calculate_index(
            definition,
            legs,
            {"reference": _series([1.0, 2.0, 3.0]), "hedge": _series([1.0, 2.0, 3.0])},
        )


@pytest.mark.parametrize("method", ["price_ols", "return_ols", "beta_neutral"])
def test_rolling_estimated_coefficients_do_not_use_future_observations(method: str) -> None:
    times = pd.date_range("2025-01-01", periods=8, tz="UTC")
    hedge = pd.Series([10.0, 11.0, 12.0, 13.0, 14.0, 15.0, 16.0, 17.0], index=times)
    reference = hedge * 2.0 + 1.0
    definition = _definition()
    legs = [
        _asset_leg("reference", 0),
        _asset_leg(
            "hedge",
            1,
            coefficient_method=method,
            coefficient=None,
            coefficient_parameters_json={"window": 4, "min_observations": 3, "lag": 1},
        ),
    ]
    baseline = resolve_index_legs(
        definition,
        legs,
        {"reference": reference, "hedge": hedge},
        index_identifier="TEST",
        calculation_times=times,
        component_identifiers={legs[1].asset_uid: "HEDGE"},
    ).reset_index()
    changed_reference = reference.copy()
    changed_reference.iloc[-1] = 10_000.0
    changed = resolve_index_legs(
        definition,
        legs,
        {"reference": changed_reference, "hedge": hedge},
        index_identifier="TEST",
        calculation_times=times,
        component_identifiers={legs[1].asset_uid: "HEDGE"},
    ).reset_index()

    pd.testing.assert_series_equal(
        baseline["resolved_coefficient"],
        changed["resolved_coefficient"],
        check_names=False,
    )
    assert (baseline["source_observation_time"] < baseline["time_index"]).all()


@pytest.mark.parametrize("method", ["delta", "dv01_neutral"])
def test_risk_coefficients_are_lagged_and_preserve_source_provenance(method: str) -> None:
    times = pd.date_range("2025-01-01", periods=4, tz="UTC")
    definition = _definition()
    legs = [
        _asset_leg("reference", 0),
        _asset_leg(
            "hedge",
            1,
            coefficient_method=method,
            coefficient=None,
            coefficient_parameters_json={"lag": 1, "observable_code": method},
        ),
    ]
    inputs = {"hedge": pd.Series([0.5, 0.6, 0.7, 0.8], index=times)}
    if method == "dv01_neutral":
        inputs["reference"] = pd.Series([2.0, 2.0, 2.0, 2.0], index=times)
        inputs["hedge"] = pd.Series([1.0, 1.0, 1.0, 1.0], index=times)
    resolved = resolve_index_legs(
        definition,
        legs,
        {
            "reference": pd.Series([10.0, 11.0, 12.0, 13.0], index=times),
            "hedge": pd.Series([20.0, 21.0, 22.0, 23.0], index=times),
        },
        index_identifier="TEST",
        calculation_times=times,
        component_identifiers={legs[1].asset_uid: "HEDGE"},
        coefficient_inputs=inputs,
    ).reset_index()

    expected = [-0.5, -0.6, -0.7] if method == "delta" else [-2.0, -2.0, -2.0]
    assert resolved["resolved_coefficient"].tolist() == pytest.approx(expected)
    assert (resolved["source_observation_time"] < resolved["time_index"]).all()


def test_external_dynamic_coefficient_rejects_future_source_timestamp() -> None:
    times = pd.date_range("2025-01-01", periods=2, tz="UTC")
    definition = _definition()
    legs = [
        _asset_leg("reference", 0),
        _asset_leg(
            "hedge",
            1,
            coefficient_method="delta",
            coefficient=None,
            coefficient_parameters_json={"lag": 1},
        ),
    ]

    with pytest.raises(LookAheadError, match="future source observation"):
        calculate_index(
            definition,
            legs,
            {
                "reference": pd.Series([10.0, 11.0], index=times),
                "hedge": pd.Series([20.0, 21.0], index=times),
            },
            resolved_coefficients={"hedge": pd.Series([-0.5, -0.6], index=times)},
            resolved_coefficient_source_times={
                "hedge": pd.Series([times[1], times[1] + pd.Timedelta(days=1)], index=times)
            },
        )


def test_external_dynamic_coefficients_preserve_values_when_input_is_unsorted() -> None:
    times = pd.date_range("2025-01-01", periods=3, tz="UTC")
    definition = _definition()
    legs = [
        _asset_leg("reference", 0),
        _asset_leg(
            "hedge",
            1,
            coefficient_method="delta",
            coefficient=None,
            coefficient_parameters_json={"lag": 1},
        ),
    ]
    unsorted = times[[2, 0, 1]]

    result = calculate_index(
        definition,
        legs,
        {
            "reference": pd.Series([10.0, 10.0, 10.0], index=times),
            "hedge": pd.Series([2.0, 2.0, 2.0], index=times),
        },
        resolved_coefficients={
            "hedge": pd.Series([-3.0, -1.0, -2.0], index=unsorted),
        },
        resolved_coefficient_source_times={
            "hedge": pd.Series(unsorted, index=unsorted),
        },
    ).values

    assert result["value"].tolist() == pytest.approx([8.0, 6.0, 4.0])


def test_monthly_rebalance_holds_dynamic_coefficients_within_each_period() -> None:
    times = pd.DatetimeIndex(
        [
            "2025-01-30T00:00:00Z",
            "2025-01-31T00:00:00Z",
            "2025-02-01T00:00:00Z",
            "2025-02-02T00:00:00Z",
        ]
    )
    definition = _definition(
        composition_mode="rebalanced",
        rebalance_policy="monthly",
        rebalance_parameters_json={"timezone": "UTC"},
    )
    legs = [
        _asset_leg("reference", 0),
        _asset_leg(
            "hedge",
            1,
            coefficient_method="delta",
            coefficient=None,
            coefficient_parameters_json={"lag": 1},
        ),
    ]

    result = calculate_index(
        definition,
        legs,
        {
            "reference": pd.Series(10.0, index=times),
            "hedge": pd.Series(2.0, index=times),
        },
        resolved_coefficients={
            "hedge": pd.Series([-1.0, -2.0, -3.0, -4.0], index=times),
        },
        resolved_coefficient_source_times={
            "hedge": pd.Series(times, index=times),
        },
    ).values

    assert result["value"].tolist() == pytest.approx([8.0, 8.0, 4.0, 4.0])
