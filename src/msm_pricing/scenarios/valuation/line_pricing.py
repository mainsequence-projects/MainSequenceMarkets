"""Partial-success line valuation helpers for scenario workflows."""

from __future__ import annotations

import math
import uuid
from collections import defaultdict
from collections.abc import Mapping

from msm_pricing.instruments.base_instrument import InstrumentModel
from msm_pricing.valuation import PricingValuationContext, ValuationPosition

from .models import (
    ValuationCashflow,
    ValuationLineAnalytics,
    ValuationLinePrice,
    ValuationRunResult,
    ValuationWorkflowDiagnostic,
)


def price_valuation_lines(
    position: ValuationPosition,
    *,
    context: PricingValuationContext | None = None,
    curve_handles_by_line: Mapping[int, object] | None = None,
    scenario_name: str = "base",
    include_analytics: bool = True,
    include_cashflows: bool = True,
    strict: bool = False,
) -> ValuationRunResult:
    """Price each valuation line and keep line failures as diagnostics.

    This helper intentionally differs from ``ValuationPosition.price()``:
    ``strict=False`` lets callers price the lines that can be priced while
    returning structured diagnostics for failed lines. Submitted instruments
    are prepared through ``PricingValuationContext`` so caller-owned instrument
    objects are not mutated. Optional analytics and cashflows are collected
    through the same prepared-instrument path when the instrument exposes
    ``analytics()`` or ``get_cashflows()``.

    The result is typed and table-adapter friendly, but it is not a pandas or
    dashboard response model. Downstream callers own any final table shaping.
    """

    pricing_context = position._context(context)
    diagnostics: list[ValuationWorkflowDiagnostic] = []
    line_prices: list[ValuationLinePrice] = []
    line_analytics: list[ValuationLineAnalytics] = []
    cashflows: list[ValuationCashflow] = []
    total = 0.0
    priced_any = False

    for line_index, line in enumerate(position.lines):
        metadata = dict(line.metadata_json)
        instrument_type = type(line.instrument).__name__
        curve_handles = _line_curve_handles(curve_handles_by_line, line_index)
        try:
            prepared = pricing_context.prepare_instrument(
                line.instrument,
                curve_handles=curve_handles,
            )
            unit_price = float(prepared.price())
            market_value = float(line.units) * unit_price
            priced_any = True
            total += market_value
            line_prices.append(
                ValuationLinePrice(
                    line_index=line_index,
                    instrument_type=instrument_type,
                    asset_uid=line.asset_uid,
                    units=float(line.units),
                    unit_price=unit_price,
                    market_value=market_value,
                    status="priced",
                    metadata_json=metadata,
                )
            )
        except Exception as exc:
            _record_or_raise(
                ValuationWorkflowDiagnostic(
                    stage="price",
                    message=str(exc),
                    scenario_name=scenario_name,
                    line_index=line_index,
                    asset_uid=line.asset_uid,
                    metadata_json=metadata,
                ),
                diagnostics=diagnostics,
                strict=strict,
            )
            line_prices.append(
                ValuationLinePrice(
                    line_index=line_index,
                    instrument_type=instrument_type,
                    asset_uid=line.asset_uid,
                    units=float(line.units),
                    unit_price=None,
                    market_value=None,
                    status="error",
                    error=str(exc),
                    metadata_json=metadata,
                )
            )

        if include_analytics and _instrument_supports(line.instrument, "analytics"):
            analytics = _line_analytics(
                line.instrument,
                context=pricing_context,
                curve_handles=curve_handles,
                line_index=line_index,
                instrument_type=instrument_type,
                asset_uid=line.asset_uid,
                units=float(line.units),
                metadata_json=metadata,
                scenario_name=scenario_name,
                strict=strict,
                diagnostics=diagnostics,
            )
            if analytics is not None:
                line_analytics.append(analytics)

        if include_cashflows and _instrument_supports(line.instrument, "get_cashflows"):
            cashflows.extend(
                _line_cashflows(
                    line.instrument,
                    context=pricing_context,
                    curve_handles=curve_handles,
                    line_index=line_index,
                    instrument_type=instrument_type,
                    asset_uid=line.asset_uid,
                    units=float(line.units),
                    metadata_json=metadata,
                    scenario_name=scenario_name,
                    strict=strict,
                    diagnostics=diagnostics,
                )
            )

    total_market_value = 0.0 if not position.lines else (total if priced_any else None)
    return ValuationRunResult(
        scenario_name=scenario_name,
        total_market_value=total_market_value,
        line_prices=tuple(line_prices),
        line_analytics=tuple(line_analytics),
        cashflows=tuple(cashflows),
        diagnostics=tuple(diagnostics),
    )


def _line_analytics(
    instrument: InstrumentModel,
    *,
    context: PricingValuationContext,
    curve_handles: object | None,
    line_index: int,
    instrument_type: str,
    asset_uid: uuid.UUID | None,
    units: float,
    metadata_json: Mapping[str, object],
    scenario_name: str,
    strict: bool,
    diagnostics: list[ValuationWorkflowDiagnostic],
) -> ValuationLineAnalytics | None:
    try:
        prepared = context.prepare_instrument(instrument, curve_handles=curve_handles)
        analytics = prepared.analytics()
        if not isinstance(analytics, Mapping):
            raise TypeError(f"{instrument_type}.analytics() must return a mapping.")
        scaled: dict[str, float] = defaultdict(float)
        for key, value in analytics.items():
            if isinstance(value, (int, float)) and math.isfinite(float(value)):
                scaled[str(key)] += units * float(value)
        return ValuationLineAnalytics(
            line_index=line_index,
            instrument_type=instrument_type,
            asset_uid=asset_uid,
            units=units,
            raw_analytics=dict(analytics),
            scaled_analytics=dict(scaled),
            status="ready",
            metadata_json=dict(metadata_json),
        )
    except Exception as exc:
        _record_or_raise(
            ValuationWorkflowDiagnostic(
                stage="analytics",
                message=str(exc),
                scenario_name=scenario_name,
                line_index=line_index,
                asset_uid=asset_uid,
                metadata_json=dict(metadata_json),
            ),
            diagnostics=diagnostics,
            strict=strict,
        )
        return ValuationLineAnalytics(
            line_index=line_index,
            instrument_type=instrument_type,
            asset_uid=asset_uid,
            units=units,
            status="error",
            error=str(exc),
            metadata_json=dict(metadata_json),
        )


def _line_cashflows(
    instrument: InstrumentModel,
    *,
    context: PricingValuationContext,
    curve_handles: object | None,
    line_index: int,
    instrument_type: str,
    asset_uid: uuid.UUID | None,
    units: float,
    metadata_json: Mapping[str, object],
    scenario_name: str,
    strict: bool,
    diagnostics: list[ValuationWorkflowDiagnostic],
) -> tuple[ValuationCashflow, ...]:
    try:
        prepared = context.prepare_instrument(instrument, curve_handles=curve_handles)
        raw_cashflows = prepared.get_cashflows()
        if not isinstance(raw_cashflows, Mapping):
            raise TypeError(f"{instrument_type}.get_cashflows() must return a mapping.")
        rows: list[ValuationCashflow] = []
        for leg, leg_rows in raw_cashflows.items():
            if not isinstance(leg_rows, list):
                raise TypeError(f"{instrument_type}.get_cashflows()[{leg!r}] must be a list.")
            for raw_row in leg_rows:
                if not isinstance(raw_row, Mapping):
                    raise TypeError("cashflow rows must be mappings.")
                row = dict(raw_row)
                amount = _scaled_amount(row.get("amount"), units=units)
                if amount is not None:
                    row["amount"] = amount
                rows.append(
                    ValuationCashflow(
                        line_index=line_index,
                        instrument_type=instrument_type,
                        asset_uid=asset_uid,
                        units=units,
                        leg=str(leg),
                        amount=amount,
                        payment_date=_cashflow_payment_date(row),
                        cashflow=row,
                        metadata_json=dict(metadata_json),
                    )
                )
        return tuple(rows)
    except Exception as exc:
        _record_or_raise(
            ValuationWorkflowDiagnostic(
                stage="cashflows",
                message=str(exc),
                scenario_name=scenario_name,
                line_index=line_index,
                asset_uid=asset_uid,
                metadata_json=dict(metadata_json),
            ),
            diagnostics=diagnostics,
            strict=strict,
        )
        return ()


def _line_curve_handles(
    curve_handles_by_line: Mapping[int, object] | None,
    line_index: int,
) -> object | None:
    if curve_handles_by_line is None:
        return None
    return curve_handles_by_line.get(line_index)


def _instrument_supports(instrument: InstrumentModel, method_name: str) -> bool:
    return callable(getattr(instrument, method_name, None))


def _scaled_amount(value: object, *, units: float) -> float | None:
    if isinstance(value, (int, float)) and math.isfinite(float(value)):
        return units * float(value)
    return None


def _cashflow_payment_date(row: Mapping[str, object]) -> object | None:
    return (
        row.get("payment_date")
        or row.get("cashflow_date")
        or row.get("date")
        or row.get("time_index")
    )


def _record_or_raise(
    diagnostic: ValuationWorkflowDiagnostic,
    *,
    diagnostics: list[ValuationWorkflowDiagnostic],
    strict: bool,
) -> None:
    if strict:
        raise RuntimeError(diagnostic.message)
    diagnostics.append(diagnostic)


__all__ = ["price_valuation_lines"]
