from __future__ import annotations

import datetime as dt
import json
import sys
import uuid
from pathlib import Path
from typing import Any

import QuantLib as ql
from pydantic import PrivateAttr

if __package__ in {None, ""}:
    _PROJECT_ROOT = Path(__file__).resolve().parents[2]
    sys.path[:0] = [str(_PROJECT_ROOT / "src"), str(_PROJECT_ROOT)]

from msm_pricing.instruments import Instrument  # noqa: E402
from msm_pricing.scenarios.curves import (  # noqa: E402
    CurveBumpSpec,
    CurveScenario,
    LineCurveResolution,
    price_resolved_curve_scenario,
)
from msm_pricing.valuation import ValuationLine, ValuationPosition  # noqa: E402


class ThirtyDayDiscountInstrument(Instrument):
    """Small offline instrument that prices from an injected curve handle."""

    notional: float
    floating_rate_index_uid: uuid.UUID

    _curve_handle: ql.YieldTermStructureHandle | None = PrivateAttr(default=None)

    def reset_curve(self, curve_handle: ql.YieldTermStructureHandle) -> None:
        self._curve_handle = curve_handle

    def price(
        self, *, market_data_set: object = None, curve_quote_side: str | None = None
    ) -> float:
        if self.valuation_date is None:
            raise RuntimeError("valuation_date was not prepared")
        if self._curve_handle is None:
            raise RuntimeError("curve handle was not injected")
        ql.Settings.instance().evaluationDate = _ql_date(self.valuation_date)
        return self.notional * float(
            self._curve_handle.discount(_ql_date(self.valuation_date) + 30)
        )


def build_resolved_curve_scenario_example() -> dict[str, Any]:
    valuation_date = dt.datetime(2026, 1, 1, tzinfo=dt.UTC)
    index_uid = uuid.UUID("00000000-0000-4000-8000-000000000211")
    curve_uid = uuid.UUID("00000000-0000-4000-8000-000000000311")
    curve_identifier = "USD-SOFR-DEMO"
    base_handle = _flat_forward_handle(rate=0.05, valuation_date=valuation_date)
    scenario_handle = _flat_forward_handle(rate=0.0525, valuation_date=valuation_date)
    instrument = ThirtyDayDiscountInstrument(
        notional=1_000_000.0,
        floating_rate_index_uid=index_uid,
    )
    position = ValuationPosition(
        valuation_date=valuation_date,
        lines=[ValuationLine(instrument=instrument, units=1.0)],
    )

    result = price_resolved_curve_scenario(
        position,
        CurveScenario(
            name="parallel-up-25bp",
            shocks_by_curve_identifier={curve_identifier: CurveBumpSpec(parallel_bp=25.0)},
        ),
        line_curve_resolutions=[
            LineCurveResolution(
                line_index=0,
                role_key="projection",
                selector_type="index",
                selector_key=str(index_uid),
                quote_side=None,
                curve_uid=curve_uid,
                curve_identifier=curve_identifier,
                base_handle=base_handle,
                scenario_handle=scenario_handle,
            )
        ],
    )
    return {
        "scenario_name": result.scenario_name,
        "base_market_value": result.base_market_value,
        "scenario_market_value": result.scenario_market_value,
        "market_value_delta": result.market_value_delta,
        "curve_shocks": [dict(row) for row in result.curve_shocks],
        "line_impacts": [dict(row) for row in result.line_impacts],
        "errors": [error.to_dict() for error in result.errors],
    }


def _flat_forward_handle(
    *, rate: float, valuation_date: dt.datetime
) -> ql.YieldTermStructureHandle:
    ql.Settings.instance().evaluationDate = _ql_date(valuation_date)
    curve = ql.FlatForward(
        _ql_date(valuation_date),
        ql.QuoteHandle(ql.SimpleQuote(rate)),
        ql.Actual360(),
        ql.Continuous,
        ql.Annual,
    )
    curve.enableExtrapolation()
    return ql.YieldTermStructureHandle(curve)


def _ql_date(value: dt.datetime) -> ql.Date:
    return ql.Date(value.day, value.month, value.year)


if __name__ == "__main__":
    print(json.dumps(build_resolved_curve_scenario_example(), default=str, indent=2))
