"""Fixed and rolling commodity calendar-spread methodologies."""

from __future__ import annotations

import datetime
import uuid

import pandas as pd

from msm.api.indices import IndexCalculationDefinition, IndexCalculationLeg, calculate_index
from msm.analytics.indices import resolve_index_legs, resolve_selector


def _definition(*, dynamic: bool) -> IndexCalculationDefinition:
    return IndexCalculationDefinition(
        uid=uuid.uuid4(),
        effective_from=datetime.datetime(2025, 1, 1, tzinfo=datetime.UTC),
        calculation_kind="linear_combination",
        calculation_family="calendar_spread",
        output_unit="usd",
        composition_mode="rebalanced" if dynamic else "fixed",
        rebalance_policy="monthly" if dynamic else None,
    )


def _fixed_leg(key: str, order: int, coefficient: float) -> IndexCalculationLeg:
    return IndexCalculationLeg(
        leg_key=key,
        leg_order=order,
        component_kind="asset",
        asset_uid=uuid.uuid4(),
        observable_code="settlement",
        input_unit="usd",
        coefficient_method="fixed",
        coefficient=coefficient,
    )


def _rolling_leg(key: str, order: int, rank: int, coefficient: float) -> IndexCalculationLeg:
    return IndexCalculationLeg(
        leg_key=key,
        leg_order=order,
        component_kind="selector",
        selector_code="futures_rank",
        selector_parameters_json={"rank": rank},
        observable_code="settlement",
        input_unit="usd",
        coefficient_method="fixed",
        coefficient=coefficient,
    )


def _selected_settlement(
    candidates: pd.DataFrame,
    times: pd.DatetimeIndex,
    *,
    rank: int,
) -> pd.Series:
    selected = resolve_selector("futures_rank", candidates, times, parameters={"rank": rank})
    values: dict[pd.Timestamp, float] = {}
    for row in selected.itertuples(index=False):
        snapshot = candidates.loc[
            (pd.to_datetime(candidates["time_index"], utc=True) == row.source_observation_time)
            & (candidates["component_key"] == row.resolved_component_key)
        ]
        values[pd.Timestamp(row.time_index)] = float(snapshot.iloc[0]["settlement"])
    return pd.Series(values, dtype=float).sort_index()


def run() -> dict[str, pd.DataFrame]:
    times = pd.DatetimeIndex(["2025-01-31T00:00:00Z", "2025-02-28T00:00:00Z"])
    fixed_legs = [_fixed_leg("dec", 0, 1.0), _fixed_leg("mar", 1, -1.0)]
    fixed_values = calculate_index(
        _definition(dynamic=False),
        fixed_legs,
        {"dec": pd.Series([72.0, 74.0], index=times), "mar": pd.Series([70.0, 71.0], index=times)},
        index_identifier="CL_DEC_MAR_FIXED_SPREAD",
    ).values

    candidates = pd.DataFrame(
        [
            {"time_index": times[0], "component_key": "CLG25", "rank": 1, "settlement": 72.0},
            {"time_index": times[0], "component_key": "CLH25", "rank": 2, "settlement": 70.0},
            {"time_index": times[1], "component_key": "CLH25", "rank": 1, "settlement": 71.0},
            {"time_index": times[1], "component_key": "CLJ25", "rank": 2, "settlement": 69.5},
        ]
    )
    rolling_definition = _definition(dynamic=True)
    rolling_legs = [_rolling_leg("front", 0, 1, 1.0), _rolling_leg("second", 1, 2, -1.0)]
    rolling_observations = {
        "front": _selected_settlement(candidates, times, rank=1),
        "second": _selected_settlement(candidates, times, rank=2),
    }
    rolling_values = calculate_index(
        rolling_definition,
        rolling_legs,
        rolling_observations,
        index_identifier="CL_FRONT_SECOND_ROLLING_SPREAD",
        calculation_times=times,
    ).values
    resolved = resolve_index_legs(
        rolling_definition,
        rolling_legs,
        rolling_observations,
        index_identifier="CL_FRONT_SECOND_ROLLING_SPREAD",
        calculation_times=times,
        selector_candidates={"front": candidates, "second": candidates},
    )
    return {
        "fixed_values": fixed_values,
        "rolling_values": rolling_values,
        "resolved_legs": resolved,
    }


if __name__ == "__main__":
    for name, frame in run().items():
        print(name)
        print(frame)
