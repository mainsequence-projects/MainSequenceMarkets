from __future__ import annotations

import datetime as dt
import math
from contextlib import contextmanager
from typing import Any

import QuantLib as ql


def _qld(d: dt.date | dt.datetime) -> ql.Date:
    return ql.Date(d.day, d.month, d.year)


def _is_missing(value: float | int | None) -> bool:
    if value is None:
        return True
    try:
        return math.isnan(float(value))
    except TypeError:
        return False


@contextmanager
def _ql_include_ref_events(include: bool):
    settings = ql.Settings.instance()
    previous = settings.includeReferenceDateEvents
    settings.includeReferenceDateEvents = include
    try:
        yield
    finally:
        settings.includeReferenceDateEvents = previous


def _get_ql_bond(bond: Any) -> ql.Bond:
    get_ql_bond = getattr(bond, "get_ql_bond", None)
    if callable(get_ql_bond):
        return get_ql_bond()
    ql_bond = getattr(bond, "bond", None)
    if ql_bond is None:
        raise TypeError("bond must expose get_ql_bond() or bond")
    return ql_bond


def _coupon_from_cashflow(cf: ql.CashFlow) -> ql.Coupon | None:
    floating_coupon = ql.as_floating_rate_coupon(cf)
    if floating_coupon is not None:
        return floating_coupon
    return ql.as_fixed_rate_coupon(cf)


def _count_future_coupons(
    ql_bond: ql.Bond,
    ref: ql.Date,
    *,
    include_ref_date_events: bool,
) -> int:
    count = 0
    with _ql_include_ref_events(include_ref_date_events):
        for cf in ql_bond.cashflows():
            if _coupon_from_cashflow(cf) is None:
                continue
            if not cf.hasOccurred(ref):
                count += 1
    return count


def _current_coupon_details(
    ql_bond: ql.Bond,
    *,
    bond: Any,
    ref: ql.Date,
) -> tuple[float, float]:
    running_coupon = float("nan")
    elapsed_coupon_days = float("nan")

    for cf in ql_bond.cashflows():
        coupon = _coupon_from_cashflow(cf)
        if coupon is None:
            continue
        if coupon.accrualStartDate() <= ref < coupon.accrualEndDate():
            running_coupon = 100.0 * float(coupon.rate())
            day_count = getattr(bond, "day_count", None)
            if day_count is not None:
                elapsed_coupon_days = int(day_count.dayCount(coupon.accrualStartDate(), ref))
            else:
                elapsed_coupon_days = int(ref - coupon.accrualStartDate())
            break

    return running_coupon, elapsed_coupon_days


def compare_bond_to_market_quote(
    bond: Any,
    *,
    market_dirty_price: float,
    market_clean_price: float,
    market_current_coupon: float | None,
    expected_future_coupon_count: int | None,
    yield_to_maturity: float | None,
    face_value: float,
    valuation_date: dt.date | dt.datetime | None = None,
    price_tolerance_bp: float = 2.0,
    from_settlement: bool = True,
    include_ref_date_events: bool = False,
) -> dict[str, Any]:
    """
    Compare a priced bond model against provider-neutral market quote fields.

    Price outputs use currency units: QuantLib per-100 analytics are scaled by
    `face_value` before comparison.
    """
    market_dirty = float(market_dirty_price)
    if market_dirty == 0.0:
        raise ValueError("market_dirty_price must be non-zero")
    face = float(face_value)
    if face == 0.0:
        raise ValueError("face_value must be non-zero")

    analytics = bond.analytics(with_yield=yield_to_maturity)
    ql_bond = _get_ql_bond(bond)

    model_dirty = float(analytics["dirty_price"]) * face / 100.0
    model_clean = float(analytics["clean_price"]) * face / 100.0
    model_accrued = model_dirty - model_clean
    model_accrued_per_100 = 100.0 * (model_accrued / face)

    if from_settlement:
        ref = ql_bond.settlementDate()
    else:
        if valuation_date is None:
            raise ValueError("valuation_date is required when from_settlement=False")
        ref = _qld(valuation_date)

    running_coupon, elapsed_coupon_days = _current_coupon_details(ql_bond, bond=bond, ref=ref)
    future_coupon_count = _count_future_coupons(
        ql_bond,
        ref,
        include_ref_date_events=include_ref_date_events,
    )

    expected_count = (
        None if _is_missing(expected_future_coupon_count) else int(expected_future_coupon_count)
    )
    price_diff_bp = 100.0 * (model_dirty - market_dirty) / market_dirty
    coupon_diff_bp = (
        float("nan")
        if _is_missing(market_current_coupon) or _is_missing(running_coupon)
        else (running_coupon - float(market_current_coupon)) * 100.0
    )

    return {
        "model_dirty_price": model_dirty,
        "model_clean_price": model_clean,
        "model_accrued_price": model_accrued,
        "model_accrued_per_100": model_accrued_per_100,
        "market_dirty_price": market_dirty,
        "market_clean_price": float(market_clean_price),
        "model_current_coupon": running_coupon,
        "coupon_diff_bp": coupon_diff_bp,
        "price_diff_bp": price_diff_bp,
        "expected_future_coupon_count": expected_count,
        "future_coupon_count": future_coupon_count,
        "elapsed_coupon_days": elapsed_coupon_days,
        "pass_price": abs(price_diff_bp) <= price_tolerance_bp,
        "pass_coupon_count": expected_count is None or future_coupon_count == expected_count,
    }
