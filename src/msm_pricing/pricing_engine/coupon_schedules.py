import datetime as dt

import QuantLib as ql


def _qld(d: dt.date) -> ql.Date:
    return ql.Date(d.day, d.month, d.year)


def _pyd(d: ql.Date) -> dt.date:
    return dt.date(d.year(), int(d.month()), d.dayOfMonth())


def compute_coupon_schedule_force_match(
    *,
    valuation_date: dt.date,
    maturity_date: dt.date,
    coupon_frequency_days: int,
    remaining_coupon_count: int | None,
    elapsed_coupon_days: int | None,
    calendar: ql.Calendar | None = None,
    business_day_convention: int = ql.Following,
    adjust_maturity_date: bool = False,
    settlement_days: int = 2,
    count_from_settlement: bool = True,
    include_boundary_for_count: bool = True,
) -> ql.Schedule:
    """
    Build an explicit coupon schedule that reconciles to normalized vendor facts.

    The inputs are provider-neutral: callers must parse provider-specific rows
    before calling this function.
    """
    if coupon_frequency_days <= 0:
        raise ValueError("coupon_frequency_days must be positive")

    calendar = calendar or ql.Mexico()
    frequency_delta = dt.timedelta(days=int(coupon_frequency_days))

    def adjust(d: dt.date, convention: int = business_day_convention) -> dt.date:
        return _pyd(calendar.adjust(_qld(d), convention))

    maturity_pay = adjust(maturity_date) if adjust_maturity_date else maturity_date

    if count_from_settlement:
        boundary = _pyd(
            calendar.advance(
                _qld(valuation_date),
                settlement_days,
                ql.Days,
                business_day_convention,
            )
        )
    else:
        boundary = valuation_date

    last_insertable = maturity_pay - dt.timedelta(days=1)
    if include_boundary_for_count:
        boundary_eff = min(boundary, maturity_pay)
    else:
        boundary_eff = min(boundary, last_insertable)

    if remaining_coupon_count is not None and remaining_coupon_count <= 0:
        dv = ql.DateVector()
        dv.push_back(_qld(maturity_pay))
        return ql.Schedule(dv, calendar, business_day_convention)

    nat_desc: list[dt.date] = [maturity_pay]
    d = maturity_pay
    while True:
        prev_unadj = d - frequency_delta
        prev_adj = adjust(prev_unadj)
        if prev_adj >= d:
            prev_adj = adjust(prev_unadj, ql.Preceding)
            while prev_adj >= d:
                prev_unadj -= dt.timedelta(days=1)
                prev_adj = adjust(prev_unadj, ql.Preceding)

        if prev_adj < boundary_eff:
            break
        nat_desc.append(prev_adj)
        d = prev_adj

    future_dates = sorted(set(nat_desc))
    natural_cnt = len(future_dates)

    if remaining_coupon_count is None:
        if elapsed_coupon_days is None:
            prev_unadj = future_dates[0] - frequency_delta
            prev_pay = adjust(prev_unadj)
            if prev_pay >= future_dates[0]:
                prev_pay = _pyd(calendar.advance(_qld(future_dates[0]), -1, ql.Days, ql.Preceding))
        else:
            prev_pay = valuation_date - dt.timedelta(days=int(elapsed_coupon_days))
            if prev_pay >= future_dates[0]:
                prev_pay = future_dates[0] - dt.timedelta(days=1)

        dv = ql.DateVector()
        dv.push_back(_qld(prev_pay))
        for x in future_dates:
            dv.push_back(_qld(x))
        return ql.Schedule(dv, calendar, business_day_convention)

    expected_coupon_count = int(remaining_coupon_count)

    if natural_cnt < expected_coupon_count:
        missing_count = expected_coupon_count - natural_cnt
        existing = set(future_dates)
        extra: list[dt.date] = []

        hi = last_insertable
        lo = boundary_eff if include_boundary_for_count else boundary_eff + dt.timedelta(days=1)

        span = (hi - lo).days + 1
        if span < missing_count:
            lo = hi - dt.timedelta(days=missing_count - 1)

        cand = hi
        safety = 0
        while len(extra) < missing_count:
            if cand not in existing and cand not in extra and cand < maturity_pay:
                extra.append(cand)
            cand -= dt.timedelta(days=1)
            if cand < lo:
                cand = hi - dt.timedelta(days=len(extra))
            safety += 1
            if safety > 2000:
                raise RuntimeError("Failed to insert extra dates.")

        future_dates = sorted(set(future_dates + extra))

    elif natural_cnt > expected_coupon_count:
        future_dates = future_dates[:expected_coupon_count]

    if elapsed_coupon_days is None:
        prev_unadj = future_dates[0] - frequency_delta
        prev_pay = adjust(prev_unadj)
        if prev_pay >= future_dates[0]:
            prev_pay = _pyd(calendar.advance(_qld(future_dates[0]), -1, ql.Days, ql.Preceding))
    else:
        prev_pay = valuation_date - dt.timedelta(days=int(elapsed_coupon_days))
        if prev_pay >= future_dates[0]:
            prev_pay = future_dates[0] - dt.timedelta(days=1)

    dv = ql.DateVector()
    dv.push_back(_qld(prev_pay))
    for x in future_dates:
        dv.push_back(_qld(x))
    return ql.Schedule(dv, calendar, business_day_convention)
