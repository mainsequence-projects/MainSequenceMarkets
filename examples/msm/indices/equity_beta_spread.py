"""Equity return spread with lagged rolling beta-neutral coefficients."""

from __future__ import annotations

import datetime
import uuid

import pandas as pd

from msm.api.indices import IndexCalculationDefinition, IndexCalculationLeg, calculate_index
from msm.analytics.indices import resolve_index_legs


def run() -> dict[str, object]:
    times = pd.date_range("2025-01-01", periods=9, tz="UTC")
    wal_mart = pd.Series([50.0, 50.5, 51.2, 51.0, 52.0, 52.5, 53.4, 53.0, 54.0], index=times)
    femsa = pd.Series([100.0, 100.4, 101.0, 100.9, 101.6, 102.0, 102.7, 102.5, 103.1], index=times)
    definition = IndexCalculationDefinition(
        uid=uuid.uuid4(),
        effective_from=datetime.datetime(2025, 1, 1, tzinfo=datetime.UTC),
        calculation_kind="linear_combination",
        calculation_family="equity_relative_value",
        output_unit="decimal",
        composition_mode="rebalanced",
        rebalance_policy="daily",
    )
    legs = [
        IndexCalculationLeg(
            leg_key="walmex",
            leg_order=0,
            component_kind="asset",
            asset_uid=uuid.uuid4(),
            observable_code="price",
            input_unit="mxn",
            transform_code="simple_return",
            coefficient_method="fixed",
            coefficient=1.0,
        ),
        IndexCalculationLeg(
            leg_key="femsa",
            leg_order=1,
            component_kind="asset",
            asset_uid=uuid.uuid4(),
            observable_code="price",
            input_unit="mxn",
            transform_code="simple_return",
            coefficient_method="beta_neutral",
            coefficient_parameters_json={
                "window": 4,
                "min_observations": 3,
                "lag": 1,
                "include_intercept": True,
                "fallback_policy": "drop",
            },
        ),
    ]
    observations = {"walmex": wal_mart, "femsa": femsa}
    resolved = resolve_index_legs(
        definition,
        legs,
        observations,
        index_identifier="WALMEX_FEMSA_BETA_NEUTRAL",
        calculation_times=times,
        component_identifiers={legs[1].asset_uid: "FEMSA_UB"},
    )
    flat_resolved = resolved.reset_index()
    coefficients = pd.Series(
        flat_resolved["resolved_coefficient"].to_numpy(),
        index=pd.DatetimeIndex(flat_resolved["time_index"]),
    )
    coefficient_sources = pd.Series(
        flat_resolved["source_observation_time"].to_numpy(),
        index=pd.DatetimeIndex(flat_resolved["time_index"]),
    )
    values = calculate_index(
        definition,
        legs,
        observations,
        index_identifier="WALMEX_FEMSA_BETA_NEUTRAL",
        calculation_times=times,
        resolved_coefficients={"femsa": coefficients},
        resolved_coefficient_source_times={"femsa": coefficient_sources},
    ).values
    return {
        "values": values,
        "resolved_legs": resolved,
        "no_lookahead": bool(
            (flat_resolved["source_observation_time"] < flat_resolved["time_index"]).all()
        ),
    }


if __name__ == "__main__":
    output = run()
    print(output["values"])
    print(output["resolved_legs"])
    print("no look-ahead:", output["no_lookahead"])
