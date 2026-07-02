"""Offline helper-based curve reconstruction and observation export example."""

from __future__ import annotations

import datetime as dt

import QuantLib as ql

from msm_pricing.pricing_engine.curves import (
    OISRateHelperSpec,
    OvernightDepositHelperSpec,
    export_curve_observation_nodes,
    reconstruct_curve_handle_from_helper_specs,
)


def main() -> None:
    """Build a curve from generic rate-helper specs and print exported nodes."""

    valuation_date = dt.datetime(2026, 1, 2, tzinfo=dt.UTC)
    handle = reconstruct_curve_handle_from_helper_specs(
        (
            OvernightDepositHelperSpec(quote=0.0475, tenor="1D"),
            OISRateHelperSpec(
                quote=0.0480,
                tenor="1Y",
                settlement_days=2,
                overnight_index=ql.Sofr(),
                payment_convention="ModifiedFollowing",
                payment_frequency="Annual",
                payment_calendar=ql.TARGET(),
                fixed_payment_frequency="Annual",
                fixed_calendar=ql.TARGET(),
                averaging_method="Compound",
            ),
        ),
        valuation_date=valuation_date,
        day_counter=ql.Actual360(),
    )
    nodes = export_curve_observation_nodes(
        handle,
        valuation_date=valuation_date,
        node_days=[7, 30, 90, 180, 365],
        include_pillar_dates=False,
    )
    for node in nodes:
        print(node)


if __name__ == "__main__":
    main()
