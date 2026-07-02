from __future__ import annotations

import datetime as dt
from types import SimpleNamespace

import pytest

from msm_pricing.scenarios.curves import (
    CurveBumpSpec,
    bump_key_node_rate,
    bump_key_nodes,
    key_node_days_to_maturity,
    key_node_decimal_rate,
    key_node_maturity_date,
    key_nodes_to_curve_observation_nodes,
    runtime_curve_quote_convention,
    runtime_curve_rate_unit,
    runtime_observation_building_details,
    tenor_to_days,
)


def _details(**overrides):
    values = {
        "curve_uid": "00000000-0000-0000-0000-000000000001",
        "builder_type": "zero_rate_curve",
        "quote_convention": "zero_rate",
        "rate_unit": "decimal",
        "day_counter_code": "Actual360",
        "calendar_code": "TARGET",
        "interpolation_method": "log_linear_discount",
        "compounding": "simple",
        "extrapolation_policy": "enabled",
        "builder_payload": None,
    }
    values.update(overrides)
    return SimpleNamespace(**values)


@pytest.mark.parametrize(
    ("tenor", "days"),
    [("28D", 28), ("2W", 14), ("3M", 90), ("5Y", 1825), ("bad", None)],
)
def test_tenor_to_days_is_runtime_interpolation_support(tenor: str, days: int | None) -> None:
    assert tenor_to_days(tenor) == days


def test_curve_bump_spec_interpolates_key_rates_and_rejects_invalid_keys() -> None:
    spec = CurveBumpSpec(parallel_bp=1.0, keyrate_bp={"30D": 5.0, "90D": 17.0})

    assert spec.keyrate_days_bp() == {30: 5.0, 90: 17.0}
    assert spec.total_bp_for_days(60) == pytest.approx(12.0)
    assert spec.total_bp_for_days(10) == pytest.approx(6.0)
    assert spec.total_bp_for_days(180) == pytest.approx(18.0)

    with pytest.raises(ValueError, match="keyrate_bp keys"):
        CurveBumpSpec(keyrate_bp={"bad": 1.0}).keyrate_days_bp()


def test_key_node_days_to_maturity_uses_days_dates_then_tenor() -> None:
    effective = dt.datetime(2026, 1, 1, tzinfo=dt.UTC)

    assert key_node_days_to_maturity(
        {"days_to_maturity": "30"},
        effective_curve_date=effective,
    ) == 30
    assert key_node_days_to_maturity(
        {"maturity_date": "2026-01-31"},
        effective_curve_date=effective,
    ) == 30
    assert key_node_days_to_maturity(
        {"pillar_date": dt.datetime(2026, 2, 1)},
        effective_curve_date=effective,
    ) == 31
    assert key_node_days_to_maturity({"tenor": "2W"}, effective_curve_date=effective) == 14
    assert key_node_maturity_date({"maturity_date": "2026-01-31"}).tzinfo is not None


def test_key_node_decimal_rate_requires_explicit_rate_units() -> None:
    assert key_node_decimal_rate({"yield": 0.05, "yield_unit": "decimal"}) == 0.05
    assert key_node_decimal_rate(
        {"quote": 5.0, "quote_type": "zero_rate", "quote_unit": "percent"}
    ) == pytest.approx(0.05)
    assert key_node_decimal_rate(
        {"implied_rate": 0.052, "implied_rate_unit": "decimal"}
    ) == pytest.approx(0.052)

    with pytest.raises(ValueError, match="rate unit"):
        key_node_decimal_rate({"yield": 0.05})
    with pytest.raises(ValueError, match="supported explicit rate"):
        key_node_decimal_rate(
            {"quote": 99.0, "quote_type": "clean_price", "quote_unit": "price_per_100"}
        )


def test_bump_key_nodes_copies_input_and_preserves_raw_units() -> None:
    key_nodes = [
        {
            "days_to_maturity": 30,
            "quote": 0.05,
            "quote_type": "zero_rate",
            "quote_unit": "decimal",
        },
        {
            "days_to_maturity": 90,
            "yield": 5.0,
            "yield_unit": "percent",
        },
    ]

    bumped = bump_key_nodes(
        key_nodes,
        CurveBumpSpec(parallel_bp=10.0),
        effective_curve_date=dt.datetime(2026, 1, 1, tzinfo=dt.UTC),
    )

    assert bumped == [
        {
            "days_to_maturity": 30,
            "quote": pytest.approx(0.051),
            "quote_type": "zero_rate",
            "quote_unit": "decimal",
        },
        {
            "days_to_maturity": 90,
            "yield": pytest.approx(5.1),
            "yield_unit": "percent",
        },
    ]
    assert key_nodes[0]["quote"] == 0.05
    assert key_nodes[1]["yield"] == 5.0


def test_bump_key_node_rate_rejects_clean_price_quotes() -> None:
    with pytest.raises(ValueError, match="supported rate"):
        bump_key_node_rate(
            {"quote": 99.5, "quote_type": "clean_price", "quote_unit": "price_per_100"},
            bump_bp=1.0,
        )


def test_key_nodes_to_curve_observation_nodes_respects_runtime_quote_convention() -> None:
    key_nodes = [
        {
            "days_to_maturity": 30,
            "quote": 0.05,
            "quote_type": "zero_rate",
            "quote_unit": "decimal",
        }
    ]

    assert key_nodes_to_curve_observation_nodes(
        key_nodes,
        building_details=_details(quote_convention="zero_rate", rate_unit="decimal"),
        effective_curve_date=dt.datetime(2026, 1, 1, tzinfo=dt.UTC),
    ) == [{"days_to_maturity": 30, "zero": 0.05}]
    assert key_nodes_to_curve_observation_nodes(
        key_nodes,
        building_details=_details(
            quote_convention="forward_rate",
            rate_unit="percent",
            builder_type="forward_rate_curve",
        ),
        effective_curve_date=dt.datetime(2026, 1, 1, tzinfo=dt.UTC),
    ) == [{"days_to_maturity": 30, "forward": 5.0}]


def test_runtime_observation_building_details_requires_explicit_placeholder_outputs() -> None:
    details = _details(
        quote_convention="key_node_quote",
        rate_unit="key_node_unit",
        builder_payload={
            "output_quote_type": "forward_rate",
            "output_quote_unit": "percent",
        },
    )

    runtime = runtime_observation_building_details(details)

    assert runtime_curve_quote_convention(runtime) == "forward_rate"
    assert runtime_curve_rate_unit(runtime) == "percent"
    assert runtime.builder_type == "forward_rate_curve"

    with pytest.raises(ValueError, match="builder_payload"):
        runtime_observation_building_details(
            _details(
                quote_convention="key_node_quote",
                rate_unit="decimal",
                builder_payload=None,
            )
        )
