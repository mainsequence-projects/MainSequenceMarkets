"""Rolling M-Bond 2s5s yield spread with constituent provenance."""

from __future__ import annotations

import datetime
import uuid

import pandas as pd

from msm.api.indices import IndexCalculationDefinition, IndexCalculationLeg, calculate_index
from msm.analytics.indices import resolve_index_legs, resolve_selector

ROLLING_IDENTIFIER = "MX_MBONOS_2S5S_YIELD_SPREAD"
CURRENT_CONSTITUENTS_HISTORY_IDENTIFIER = "MX_MBONOS_CURRENT_2S5S_HISTORY"


def _selected_yield(
    candidates: pd.DataFrame,
    times: pd.DatetimeIndex,
    *,
    tenor: float,
) -> pd.Series:
    selected = resolve_selector(
        "nearest_tenor",
        candidates,
        times,
        parameters={"target_tenor_years": tenor},
    )
    values: dict[pd.Timestamp, float] = {}
    for row in selected.itertuples(index=False):
        snapshot = candidates.loc[
            (pd.to_datetime(candidates["time_index"], utc=True) == row.source_observation_time)
            & (candidates["component_key"] == row.resolved_component_key)
        ]
        values[pd.Timestamp(row.time_index)] = float(snapshot.iloc[0]["yield"])
    return pd.Series(values, dtype=float).sort_index()


def run() -> dict[str, object]:
    """Return storage-shaped values and resolved monthly M-Bond legs."""

    times = pd.DatetimeIndex(["2025-01-31T00:00:00Z", "2025-02-28T00:00:00Z"])
    candidates = pd.DataFrame(
        [
            {
                "time_index": times[0],
                "component_key": "MBONO_2027",
                "tenor_years": 2.0,
                "yield": 0.0724,
            },
            {
                "time_index": times[0],
                "component_key": "MBONO_2030",
                "tenor_years": 5.0,
                "yield": 0.0841,
            },
            {
                "time_index": times[1],
                "component_key": "MBONO_2028",
                "tenor_years": 2.0,
                "yield": 0.0730,
            },
            {
                "time_index": times[1],
                "component_key": "MBONO_2031",
                "tenor_years": 5.0,
                "yield": 0.0850,
            },
        ]
    )
    definition = IndexCalculationDefinition(
        uid=uuid.uuid4(),
        effective_from=datetime.datetime(2025, 1, 1, tzinfo=datetime.UTC),
        calculation_kind="linear_combination",
        calculation_family="yield_spread",
        output_unit="basis_points",
        alignment_policy="inner",
        missing_data_policy="drop",
        composition_mode="rule_selected",
        rebalance_policy="monthly",
    )
    legs = [
        IndexCalculationLeg(
            leg_key="long",
            leg_order=0,
            component_kind="selector",
            selector_code="nearest_tenor",
            selector_parameters_json={"target_tenor_years": 5.0},
            observable_code="yield",
            input_unit="decimal",
            coefficient_method="fixed",
            coefficient=1.0,
        ),
        IndexCalculationLeg(
            leg_key="short",
            leg_order=1,
            component_kind="selector",
            selector_code="nearest_tenor",
            selector_parameters_json={"target_tenor_years": 2.0},
            observable_code="yield",
            input_unit="decimal",
            coefficient_method="fixed",
            coefficient=-1.0,
        ),
    ]
    observations = {
        "long": _selected_yield(candidates, times, tenor=5.0),
        "short": _selected_yield(candidates, times, tenor=2.0),
    }
    values = calculate_index(
        definition,
        legs,
        observations,
        index_identifier=ROLLING_IDENTIFIER,
        calculation_times=times,
    ).values
    resolved_legs = resolve_index_legs(
        definition,
        legs,
        observations,
        index_identifier=ROLLING_IDENTIFIER,
        calculation_times=times,
        selector_candidates={"long": candidates, "short": candidates},
    )
    return {
        "definition": definition,
        "legs": legs,
        "values": values,
        "resolved_legs": resolved_legs,
        "historical_meaning": {
            ROLLING_IDENTIFIER: "Constituents resolved at each monthly effective date.",
            CURRENT_CONSTITUENTS_HISTORY_IDENTIFIER: (
                "A different identity: today's selected bonds applied to their available history."
            ),
        },
    }


if __name__ == "__main__":
    output = run()
    print(output["values"])
    print(output["resolved_legs"])
