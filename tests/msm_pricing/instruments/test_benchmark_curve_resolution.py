from __future__ import annotations

# ruff: noqa: E402

import datetime as dt
import uuid
from collections.abc import Callable

import pytest

ql = pytest.importorskip("QuantLib")

from msm_pricing.instruments import FixedRateBond, ZeroCouponBond


def _flat_curve(valuation_date: dt.datetime) -> ql.YieldTermStructureHandle:
    return ql.YieldTermStructureHandle(
        ql.FlatForward(
            ql.Date(valuation_date.day, valuation_date.month, valuation_date.year),
            0.05,
            ql.Actual360(),
        )
    )


def _fixed_rate_bond(index_uid: uuid.UUID) -> FixedRateBond:
    return FixedRateBond(
        face_value=100.0,
        issue_date=dt.date(2026, 1, 1),
        maturity_date=dt.date(2031, 1, 1),
        day_count=ql.Actual360(),
        calendar=ql.TARGET(),
        business_day_convention=ql.Following,
        settlement_days=2,
        coupon_frequency=ql.Period("6M"),
        coupon_rate=0.05,
        benchmark_rate_index_uid=index_uid,
    )


def _zero_coupon_bond(index_uid: uuid.UUID) -> ZeroCouponBond:
    return ZeroCouponBond(
        face_value=100.0,
        issue_date=dt.date(2026, 1, 1),
        maturity_date=dt.date(2031, 1, 1),
        day_count=ql.Actual360(),
        calendar=ql.TARGET(),
        business_day_convention=ql.Following,
        settlement_days=2,
        benchmark_rate_index_uid=index_uid,
    )


@pytest.mark.parametrize("bond_factory", [_fixed_rate_bond, _zero_coupon_bond])
def test_benchmark_z_spread_resolves_curve_from_index_binding(
    monkeypatch,
    bond_factory: Callable[[uuid.UUID], FixedRateBond | ZeroCouponBond],
) -> None:
    index_uid = uuid.uuid4()
    market_data_set_uid = uuid.uuid4()
    valuation_date = dt.datetime(2026, 6, 9, tzinfo=dt.UTC)
    bond = bond_factory(index_uid)
    bond.set_valuation_date(valuation_date)
    calls = []
    handle = _flat_curve(valuation_date)

    monkeypatch.setattr(
        "msm_pricing.instruments.bond.PricingMarketDataSet.resolve_uid",
        staticmethod(lambda selector: market_data_set_uid if selector == "eod" else None),
    )
    monkeypatch.setattr(
        "msm_pricing.instruments.bond.resolve_curve_for_index_binding",
        lambda **kwargs: calls.append(kwargs) or handle,
    )
    monkeypatch.setattr(
        type(bond),
        "_z_spread_continuous",
        lambda self, target_dirty_ccy, discount_curve, *, tol, max_iter: 0.0042,
    )

    result = bond.z_spread(
        100.0,
        market_data_set="eod",
        curve_quote_side="offer",
        benchmark_curve_quote_side=" MID ",
        benchmark_expected_curve_type="discount",
        use_quantlib=False,
    )

    assert result == 0.0042
    assert calls == [
        {
            "index_uid": index_uid,
            "valuation_date": valuation_date,
            "market_data_set": market_data_set_uid,
            "role_key": "z_spread_base",
            "quote_side": "mid",
            "curve_uid": None,
            "curve_unique_identifier": None,
            "expected_curve_type": "discount",
        }
    ]


def test_benchmark_z_spread_missing_binding_raises_actionable_error(monkeypatch) -> None:
    index_uid = uuid.uuid4()
    market_data_set_uid = uuid.uuid4()
    valuation_date = dt.datetime(2026, 6, 9, tzinfo=dt.UTC)
    bond = _fixed_rate_bond(index_uid)
    bond.set_valuation_date(valuation_date)

    monkeypatch.setattr(
        "msm_pricing.instruments.bond.PricingMarketDataSet.resolve_uid",
        staticmethod(lambda selector: market_data_set_uid if selector == "eod" else None),
    )
    monkeypatch.setattr(
        "msm_pricing.instruments.bond.resolve_curve_for_index_binding",
        lambda **_kwargs: (_ for _ in ()).throw(LookupError("missing binding")),
    )

    with pytest.raises(LookupError) as exc_info:
        bond.z_spread(
            100.0,
            market_data_set="eod",
            benchmark_curve_quote_side="mid",
            use_quantlib=False,
        )

    message = str(exc_info.value)
    assert "Unable to resolve benchmark curve for z_spread" in message
    assert f"benchmark_rate_index_uid={index_uid}" in message
    assert f"market_data_set={market_data_set_uid}" in message
    assert "role_key='z_spread_base'" in message
    assert "selector_type='index'" in message
    assert f"selector_key='{index_uid}'" in message
    assert "quote_side='mid'" in message


def test_benchmark_z_spread_cache_key_includes_quote_side(monkeypatch) -> None:
    index_uid = uuid.uuid4()
    market_data_set_uid = uuid.uuid4()
    valuation_date = dt.datetime(2026, 6, 9, tzinfo=dt.UTC)
    bond = _fixed_rate_bond(index_uid)
    bond.set_valuation_date(valuation_date)
    handles = {
        "mid": _flat_curve(valuation_date),
        "offer": _flat_curve(valuation_date),
    }
    computations = []

    monkeypatch.setattr(
        "msm_pricing.instruments.bond.PricingMarketDataSet.resolve_uid",
        staticmethod(lambda selector: market_data_set_uid if selector == "eod" else None),
    )
    monkeypatch.setattr(
        "msm_pricing.instruments.bond.resolve_curve_for_index_binding",
        lambda **kwargs: handles[kwargs["quote_side"]],
    )
    monkeypatch.setattr(
        FixedRateBond,
        "_z_spread_continuous",
        lambda self, target_dirty_ccy, discount_curve, *, tol, max_iter: (
            computations.append(discount_curve) or 0.0042
        ),
    )

    assert bond.z_spread(
        100.0,
        market_data_set="eod",
        benchmark_curve_quote_side="mid",
        use_quantlib=False,
    ) == 0.0042
    assert bond.z_spread(
        100.0,
        market_data_set="eod",
        benchmark_curve_quote_side=" MID ",
        use_quantlib=False,
    ) == 0.0042
    assert bond.z_spread(
        100.0,
        market_data_set="eod",
        benchmark_curve_quote_side="offer",
        use_quantlib=False,
    ) == 0.0042

    assert len(computations) == 2
