"""Impact calculations for valuation scenario workflow results."""

from __future__ import annotations

import datetime as dt

from .models import (
    ValuationCarryImpact,
    ValuationCashflow,
    ValuationLineImpact,
    ValuationLinePrice,
    ValuationRunResult,
)


def line_impacts(
    base: ValuationRunResult,
    scenario: ValuationRunResult,
    *,
    scenario_name: str,
) -> tuple[ValuationLineImpact, ...]:
    """Return line-level market-value impacts for one scenario run.

    Rows are keyed by valuation ``line_index`` and preserve line metadata from
    the base or scenario price row. If either side failed to price, the market
    value delta is ``None`` and the line error text is carried forward.
    """

    base_by_line = {line.line_index: line for line in base.line_prices}
    scenario_by_line = {line.line_index: line for line in scenario.line_prices}
    rows: list[ValuationLineImpact] = []
    for line_index in sorted(set(base_by_line) | set(scenario_by_line)):
        base_line = base_by_line.get(line_index)
        scenario_line = scenario_by_line.get(line_index)
        rows.append(
            ValuationLineImpact(
                line_index=line_index,
                scenario_name=scenario_name,
                instrument_type=_first_present(base_line, scenario_line, "instrument_type"),
                asset_uid=_first_present(base_line, scenario_line, "asset_uid"),
                units=_first_present(base_line, scenario_line, "units"),
                base_market_value=base_line.market_value if base_line else None,
                scenario_market_value=scenario_line.market_value if scenario_line else None,
                market_value_delta=_market_value_delta(base_line, scenario_line),
                base_status=base_line.status if base_line else None,
                scenario_status=scenario_line.status if scenario_line else None,
                error=_combined_error(base_line, scenario_line),
                metadata_json=dict(
                    (base_line.metadata_json if base_line else None)
                    or (scenario_line.metadata_json if scenario_line else {})
                ),
            )
        )
    return tuple(rows)


def carry_impacts(
    base_cashflows: tuple[ValuationCashflow, ...] | list[ValuationCashflow],
    scenario_cashflows: tuple[ValuationCashflow, ...] | list[ValuationCashflow],
    *,
    valuation_date: dt.datetime,
    carry_days: int,
    scenario_name: str,
) -> tuple[ValuationCarryImpact, ...]:
    """Return carry impacts by line over ``valuation_date`` plus ``carry_days``.

    The helper sums typed cashflow amounts whose payment dates fall inside the
    inclusive carry window. It does not assume downstream table column names or
    source labels; callers can format the typed rows for dashboards or APIs.
    """

    base = _carry_by_line(base_cashflows, valuation_date=valuation_date, carry_days=carry_days)
    scenario = _carry_by_line(
        scenario_cashflows,
        valuation_date=valuation_date,
        carry_days=carry_days,
    )
    rows: list[ValuationCarryImpact] = []
    for line_index in sorted(set(base) | set(scenario)):
        base_value = base.get(line_index, 0.0)
        scenario_value = scenario.get(line_index, 0.0)
        rows.append(
            ValuationCarryImpact(
                line_index=line_index,
                scenario_name=scenario_name,
                base_carry=base_value,
                scenario_carry=scenario_value,
                carry_impact=scenario_value - base_value,
                carry_days=int(carry_days),
            )
        )
    return tuple(rows)


def _market_value_delta(
    base_line: ValuationLinePrice | None,
    scenario_line: ValuationLinePrice | None,
) -> float | None:
    if base_line is None or scenario_line is None:
        return None
    if base_line.market_value is None or scenario_line.market_value is None:
        return None
    return float(scenario_line.market_value) - float(base_line.market_value)


def _combined_error(
    base_line: ValuationLinePrice | None,
    scenario_line: ValuationLinePrice | None,
) -> str | None:
    errors = []
    for line in (base_line, scenario_line):
        if line is not None and line.error:
            errors.append(line.error)
    if not errors:
        return None
    return "; ".join(dict.fromkeys(errors))


def _carry_by_line(
    cashflows: tuple[ValuationCashflow, ...] | list[ValuationCashflow],
    *,
    valuation_date: dt.datetime,
    carry_days: int,
) -> dict[int, float]:
    start = _to_datetime(valuation_date)
    end = start + dt.timedelta(days=int(carry_days))
    out: dict[int, float] = {}
    for cashflow in cashflows:
        if cashflow.amount is None:
            continue
        payment_date = _to_datetime(cashflow.payment_date)
        if payment_date is None or payment_date < start or payment_date > end:
            continue
        out[cashflow.line_index] = out.get(cashflow.line_index, 0.0) + float(cashflow.amount)
    return out


def _to_datetime(value: object) -> dt.datetime | None:
    if isinstance(value, dt.datetime):
        return value if value.tzinfo is not None else value.replace(tzinfo=dt.UTC)
    if isinstance(value, dt.date):
        return dt.datetime.combine(value, dt.time(), tzinfo=dt.UTC)
    if isinstance(value, str):
        try:
            parsed = dt.datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            return None
        return parsed if parsed.tzinfo is not None else parsed.replace(tzinfo=dt.UTC)
    return None


def _first_present(
    first: ValuationLinePrice | None,
    second: ValuationLinePrice | None,
    field_name: str,
) -> object:
    if first is not None:
        return getattr(first, field_name)
    if second is not None:
        return getattr(second, field_name)
    return None


__all__ = ["carry_impacts", "line_impacts"]
