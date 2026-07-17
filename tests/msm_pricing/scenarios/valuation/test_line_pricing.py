from __future__ import annotations

import datetime as dt
import uuid

import pytest
from pydantic import PrivateAttr

from msm_pricing.instruments import Instrument
from msm_pricing.scenarios.valuation import price_valuation_lines
from msm_pricing.valuation import PricingValuationContext, ValuationLine, ValuationPosition


class LinePricingInstrument(Instrument):
    price_value: float = 100.0
    fail_price: bool = False
    fail_analytics: bool = False
    fail_cashflows: bool = False

    _curve_bump: float = PrivateAttr(default=0.0)

    def reset_curve(self, curve_handle: object) -> None:
        self._curve_bump = float(curve_handle)

    def price(self, *, market_data_set: object = None) -> float:
        if self.fail_price:
            raise ValueError("fixture price failure")
        if self.valuation_date is None:
            raise ValueError("valuation_date was not set")
        return self.price_value + self._curve_bump

    def analytics(self, *, market_data_set: object = None) -> dict[str, float]:
        if self.fail_analytics:
            raise ValueError("fixture analytics failure")
        return {"duration": 2.0, "label": "ignored"}  # type: ignore[dict-item]

    def get_cashflows(self, *, market_data_set: object = None) -> dict[str, list[dict[str, object]]]:
        if self.fail_cashflows:
            raise ValueError("fixture cashflow failure")
        return {
            "fixed": [
                {
                    "payment_date": dt.date(2026, 7, 1),
                    "amount": 3.0,
                }
            ]
        }


def test_price_valuation_lines_keeps_successful_lines_and_diagnostics() -> None:
    valuation_date = dt.datetime(2026, 1, 1, tzinfo=dt.UTC)
    asset_uid = uuid.uuid4()
    good = LinePricingInstrument(price_value=100.0)
    bad = LinePricingInstrument(price_value=200.0, fail_price=True)
    position = ValuationPosition(
        valuation_date=valuation_date,
        market_data_set="eod",
        lines=[
            ValuationLine(
                instrument=good,
                units=2.0,
                asset_uid=asset_uid,
                metadata_json={"line_id": "good"},
            ),
            ValuationLine(
                instrument=bad,
                units=3.0,
                metadata_json={"line_id": "bad"},
            ),
        ],
    )
    context = PricingValuationContext.prepare_for_position(
        position,
        resolve_market_data_set=False,
    )

    result = price_valuation_lines(
        position,
        context=context,
        curve_handles_by_line={0: 5.0, 1: 7.0},
        scenario_name="base",
    )

    assert result.total_market_value == pytest.approx(210.0)
    assert result.line_prices[0].status == "priced"
    assert result.line_prices[0].unit_price == pytest.approx(105.0)
    assert result.line_prices[0].market_value == pytest.approx(210.0)
    assert result.line_prices[1].status == "error"
    assert result.line_prices[1].error == "fixture price failure"
    assert result.diagnostics[0].stage == "price"
    assert result.diagnostics[0].line_index == 1
    assert result.line_analytics[0].scaled_analytics == {"duration": 4.0}
    assert result.cashflows[0].amount == pytest.approx(6.0)
    assert result.cashflows[0].line_index == 0
    assert good._curve_bump == 0.0
    assert bad._curve_bump == 0.0


def test_price_valuation_lines_strict_raises_on_failed_line() -> None:
    valuation_date = dt.datetime(2026, 1, 1, tzinfo=dt.UTC)
    position = ValuationPosition(
        valuation_date=valuation_date,
        lines=[
            ValuationLine(
                instrument=LinePricingInstrument(fail_price=True),
                units=1.0,
            )
        ],
    )

    with pytest.raises(RuntimeError, match="fixture price failure"):
        price_valuation_lines(position, strict=True)
