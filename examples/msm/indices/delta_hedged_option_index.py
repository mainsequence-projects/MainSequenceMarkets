"""Delta-hedged current mark and valid self-financing performance index."""

from __future__ import annotations

import datetime
import uuid

import pandas as pd

from msm.api.indices import IndexCalculationDefinition, IndexCalculationLeg, calculate_index
from msm.analytics.indices import resolve_index_legs


def _definition(kind: str) -> IndexCalculationDefinition:
    return IndexCalculationDefinition(
        uid=uuid.uuid4(),
        effective_from=datetime.datetime(2025, 1, 1, tzinfo=datetime.UTC),
        calculation_kind=kind,
        calculation_family=(
            "delta_hedged_mark" if kind == "linear_combination" else "hedged_strategy"
        ),
        calculation_parameters_json=(
            None
            if kind == "linear_combination"
            else {
                "base_value": 100.0,
                "initial_capital": 100.0,
                "position_lag": 1,
                "financing_rate": 0.02,
                "periods_per_year": 252.0,
                "transaction_cost_bps": 1.0,
            }
        ),
        output_unit=("usd" if kind == "linear_combination" else "index_points"),
        composition_mode="rebalanced",
        rebalance_policy="daily",
    )


def _legs() -> list[IndexCalculationLeg]:
    return [
        IndexCalculationLeg(
            leg_key="option",
            leg_order=0,
            component_kind="asset",
            asset_uid=uuid.uuid4(),
            observable_code="price",
            input_unit="usd",
            coefficient_method="fixed",
            coefficient=1.0,
        ),
        IndexCalculationLeg(
            leg_key="underlying",
            leg_order=1,
            component_kind="asset",
            asset_uid=uuid.uuid4(),
            observable_code="price",
            input_unit="usd",
            coefficient_method="delta",
            coefficient_parameters_json={
                "lag": 0,
                "sign": -1.0,
                "observable_code": "delta",
                "fallback_policy": "fail",
            },
        ),
    ]


def run() -> dict[str, object]:
    times = pd.date_range("2025-01-01", periods=5, tz="UTC")
    observations = {
        "option": pd.Series([10.0, 10.8, 10.2, 11.1, 10.7], index=times),
        "underlying": pd.Series([100.0, 101.0, 100.5, 102.0, 101.5], index=times),
    }
    deltas = {"underlying": pd.Series([0.45, 0.47, 0.46, 0.50, 0.48], index=times)}
    mark_definition = _definition("linear_combination")
    mark_legs = _legs()
    resolved = resolve_index_legs(
        mark_definition,
        mark_legs,
        observations,
        index_identifier="OPTION_DELTA_HEDGED_MARK",
        calculation_times=times,
        component_identifiers={mark_legs[1].asset_uid: "UNDERLYING"},
        coefficient_inputs=deltas,
    )
    flat = resolved.reset_index()
    coefficients = pd.Series(
        flat["resolved_coefficient"].to_numpy(),
        index=pd.DatetimeIndex(flat["time_index"]),
    )
    source_times = pd.Series(
        flat["source_observation_time"].to_numpy(),
        index=pd.DatetimeIndex(flat["time_index"]),
    )
    current_mark = calculate_index(
        mark_definition,
        mark_legs,
        observations,
        index_identifier="OPTION_DELTA_HEDGED_MARK",
        resolved_coefficients={"underlying": coefficients},
        resolved_coefficient_source_times={"underlying": source_times},
    ).values

    performance_definition = _definition("self_financing")
    performance_legs = [leg.model_copy() for leg in mark_legs]
    performance_resolved = resolve_index_legs(
        performance_definition,
        performance_legs,
        observations,
        index_identifier="OPTION_DELTA_HEDGED_PERFORMANCE",
        calculation_times=times,
        component_identifiers={performance_legs[1].asset_uid: "UNDERLYING"},
        coefficient_inputs=deltas,
    ).reset_index()
    performance_coefficients = pd.Series(
        performance_resolved["resolved_coefficient"].to_numpy(),
        index=pd.DatetimeIndex(performance_resolved["time_index"]),
    )
    performance_sources = pd.Series(
        performance_resolved["source_observation_time"].to_numpy(),
        index=pd.DatetimeIndex(performance_resolved["time_index"]),
    )
    performance = calculate_index(
        performance_definition,
        performance_legs,
        observations,
        index_identifier="OPTION_DELTA_HEDGED_PERFORMANCE",
        resolved_coefficients={"underlying": performance_coefficients},
        resolved_coefficient_source_times={"underlying": performance_sources},
    ).values
    return {
        "current_mark": current_mark,
        "performance": performance,
        "resolved_deltas": resolved,
        "performance_uses_prior_positions": True,
    }


if __name__ == "__main__":
    output = run()
    print(output["current_mark"])
    print(output["performance"])
    print(output["resolved_deltas"])
