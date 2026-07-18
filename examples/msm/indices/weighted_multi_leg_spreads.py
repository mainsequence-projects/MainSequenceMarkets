"""Curve butterfly and unit-normalized commodity crack spread."""

from __future__ import annotations

import datetime
import uuid

import pandas as pd

from msm.api.indices import IndexCalculationDefinition, IndexCalculationLeg, calculate_index


def _definition(family: str, output_unit: str) -> IndexCalculationDefinition:
    return IndexCalculationDefinition(
        uid=uuid.uuid4(),
        effective_from=datetime.datetime(2025, 1, 1, tzinfo=datetime.UTC),
        calculation_kind="linear_combination",
        calculation_family=family,
        output_unit=output_unit,
        composition_mode="fixed",
    )


def _leg(
    key: str, order: int, coefficient: float, unit: str, observable: str
) -> IndexCalculationLeg:
    return IndexCalculationLeg(
        leg_key=key,
        leg_order=order,
        component_kind="asset",
        asset_uid=uuid.uuid4(),
        observable_code=observable,
        input_unit=unit,
        coefficient_method="fixed",
        coefficient=coefficient,
    )


def run() -> dict[str, pd.DataFrame]:
    times = pd.date_range("2025-01-01", periods=2, tz="UTC")
    butterfly = calculate_index(
        _definition("curve_butterfly", "basis_points"),
        [
            _leg("two_year", 0, 1.0, "decimal", "yield"),
            _leg("five_year", 1, -2.0, "decimal", "yield"),
            _leg("ten_year", 2, 1.0, "decimal", "yield"),
        ],
        {
            "two_year": pd.Series([0.07, 0.071], index=times),
            "five_year": pd.Series([0.08, 0.081], index=times),
            "ten_year": pd.Series([0.09, 0.092], index=times),
        },
        index_identifier="MX_CURVE_2S5S10S_BUTTERFLY",
    ).values
    crack = calculate_index(
        _definition("crack_spread", "usd_per_barrel"),
        [
            _leg("gasoline", 0, 2.0, "usd_per_gallon", "settlement"),
            _leg("heating_oil", 1, 1.0, "usd_per_gallon", "settlement"),
            _leg("crude", 2, -3.0, "usd_per_barrel", "settlement"),
        ],
        {
            "gasoline": pd.Series([2.0, 2.1], index=times),
            "heating_oil": pd.Series([2.5, 2.6], index=times),
            "crude": pd.Series([70.0, 71.0], index=times),
        },
        index_identifier="THREE_TWO_ONE_CRACK_SPREAD",
    ).values
    return {"butterfly": butterfly, "crack_spread": crack}


if __name__ == "__main__":
    for name, frame in run().items():
        print(name)
        print(frame)
