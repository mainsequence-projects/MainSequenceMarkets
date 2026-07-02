"""Offline provider-neutral bond terms construction example."""

from __future__ import annotations

import datetime as dt
import uuid

import QuantLib as ql

from msm_pricing.instruments import BondInstrumentTerms, build_bond_instrument_from_terms


def main() -> None:
    """Build generic bond instruments without provider row parsing."""

    valuation_date = dt.date(2026, 1, 2)
    benchmark_uid = uuid.UUID("11111111-1111-4111-8111-111111111111")
    floating_uid = uuid.UUID("22222222-2222-4222-8222-222222222222")

    terms = [
        BondInstrumentTerms(
            instrument_type="zero_coupon_bond",
            valuation_date=valuation_date,
            issue_date=dt.date(2025, 1, 2),
            maturity_date=dt.date(2027, 1, 2),
            face_value=100.0,
            day_count=ql.Actual360(),
            calendar=ql.TARGET(),
            business_day_convention=ql.Following,
            settlement_days=2,
        ),
        BondInstrumentTerms(
            instrument_type="fixed_rate_bond",
            valuation_date=valuation_date,
            issue_date=dt.date(2025, 1, 2),
            maturity_date=dt.date(2027, 1, 2),
            face_value=100.0,
            day_count=ql.Actual360(),
            calendar=ql.TARGET(),
            business_day_convention=ql.Following,
            settlement_days=2,
            benchmark_rate_index_uid=benchmark_uid,
            coupon_rate=0.05,
            coupon_frequency=ql.Period(6, ql.Months),
        ),
        BondInstrumentTerms(
            instrument_type="floating_rate_bond",
            valuation_date=valuation_date,
            issue_date=dt.date(2025, 1, 2),
            maturity_date=dt.date(2027, 1, 2),
            face_value=100.0,
            day_count=ql.Actual360(),
            calendar=ql.TARGET(),
            business_day_convention=ql.Following,
            settlement_days=2,
            floating_rate_index_uid=floating_uid,
            spread=0.0025,
            coupon_frequency=ql.Period(3, ql.Months),
        ),
    ]

    for item in terms:
        instrument = build_bond_instrument_from_terms(item)
        print(
            type(instrument).__name__,
            instrument.valuation_date,
            getattr(instrument, "benchmark_rate_index_uid", None),
        )


if __name__ == "__main__":
    main()
