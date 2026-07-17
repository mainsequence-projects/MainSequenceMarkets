"""Offline helper-based curve reconstruction and observation export example."""

from __future__ import annotations

import datetime as dt

import QuantLib as ql

from msm_pricing.pricing_engine.curves import (
    FixedRateBondHelperSpec,
    InterestRateFutureHelperSpec,
    OISRateHelperSpec,
    OvernightDepositHelperSpec,
    StaticRateHelperRuntimeResolver,
    ZeroCouponBondHelperSpec,
    export_curve_observation_nodes,
    reconstruct_curve_handle_from_helper_specs,
    reconstruct_curve_result_from_key_nodes,
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

    collateral_handle = ql.YieldTermStructureHandle(
        ql.FlatForward(ql.Date(2, 1, 2026), 0.03, ql.Actual360())
    )
    runtime_resolver = StaticRateHelperRuntimeResolver(
        yield_curves={"GENERIC-COLLATERAL": collateral_handle},
        indexes={
            "BASE-OVERNIGHT": ql.OvernightIndex(
                "BASE-ON",
                0,
                ql.USDCurrency(),
                ql.TARGET(),
                ql.Actual360(),
                collateral_handle,
            ),
            "QUOTE-OVERNIGHT": ql.OvernightIndex(
                "QUOTE-ON",
                0,
                ql.EURCurrency(),
                ql.TARGET(),
                ql.Actual360(),
                collateral_handle,
            ),
        },
    )
    xccy_result = reconstruct_curve_result_from_key_nodes(
        [
            {
                "helper_type": "fx_spot",
                "quote": 1.1,
                "quote_type": "fx_spot",
                "quote_unit": "quote_per_base",
                "fx_pair": "BASE/QUOTE",
                "fx_base_currency": "BASE",
                "fx_quote_currency": "QUOTE",
            },
            {
                "helper_type": "fx_swap_rate_helper",
                "quote": 0.001,
                "quote_type": "fx_forward_points",
                "quote_unit": "quote_per_base",
                "tenor": "1M",
                "fixing_days": 2,
                "calendar_code": "TARGET",
                "business_day_convention": "ModifiedFollowing",
                "end_of_month": False,
                "fx_pair": "BASE/QUOTE",
                "fx_base_currency": "BASE",
                "fx_quote_currency": "QUOTE",
                "is_fx_base_currency_collateral_currency": True,
                "collateral_curve": "GENERIC-COLLATERAL",
            },
            {
                "helper_type": "const_notional_cross_currency_basis_swap_rate_helper",
                "quote": 1.0,
                "quote_type": "basis_spread",
                "quote_unit": "basis_points",
                "tenor": "1Y",
                "fixing_days": 2,
                "calendar_code": "TARGET",
                "business_day_convention": "ModifiedFollowing",
                "end_of_month": False,
                "base_currency_index": "BASE-OVERNIGHT",
                "quote_currency_index": "QUOTE-OVERNIGHT",
                "collateral_curve": "GENERIC-COLLATERAL",
                "is_fx_base_currency_collateral_currency": True,
                "is_basis_on_fx_base_currency_leg": True,
                "payment_frequency": "Annual",
            },
        ],
        valuation_date=valuation_date,
        day_counter=ql.Actual360(),
        helper_runtime_resolver=runtime_resolver,
    )
    xccy_nodes = export_curve_observation_nodes(
        xccy_result.term_structure,
        valuation_date=valuation_date,
        node_days=[30, 365],
        include_pillar_dates=False,
    )
    for node in xccy_nodes:
        print("cross-currency-helper", node)
    for quote_error in xccy_result.helper_quote_errors:
        print("cross-currency-helper quote-error", quote_error)


if __name__ == "__main__":
    main()
