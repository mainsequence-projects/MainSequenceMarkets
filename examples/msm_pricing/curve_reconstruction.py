"""Offline helper-based curve reconstruction and observation export example."""

from __future__ import annotations

import datetime as dt

import QuantLib as ql

from msm_pricing.pricing_engine.curves import (
    FixedRateBondHelperSpec,
    InterestRateFutureHelperSpec,
    OISRateHelperSpec,
    OvernightDepositHelperSpec,
    ZeroCouponBondHelperSpec,
    export_curve_observation_nodes,
    reconstruct_curve_handle_from_helper_specs,
)


def main() -> None:
    """Build curves from generic helper specs and print exported nodes."""

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
        print("rate-helper", node)

    bond_handle = reconstruct_curve_handle_from_helper_specs(
        (
            ZeroCouponBondHelperSpec(
                quote=97.5,
                quote_type="clean_price",
                quote_unit="price_per_100",
                settlement_days=0,
                face_value=100.0,
                maturity_date=dt.date(2026, 7, 2),
                issue_date=dt.date(2026, 1, 2),
            ),
            FixedRateBondHelperSpec(
                quote=99.0,
                quote_type="clean_price",
                quote_unit="price_per_100",
                coupon_rate=0.05,
                issue_date=dt.date(2026, 1, 2),
                maturity_date=dt.date(2027, 1, 2),
                tenor="6M",
                settlement_days=0,
                face_value=100.0,
                day_counter=ql.Actual360(),
            ),
        ),
        valuation_date=valuation_date,
        day_counter=ql.Actual360(),
    )
    bond_nodes = export_curve_observation_nodes(
        bond_handle,
        valuation_date=valuation_date,
        node_days=[181, 365],
        include_pillar_dates=False,
    )
    for node in bond_nodes:
        print("bond-helper", node)


if __name__ == "__main__":
    main()
