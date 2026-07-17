from __future__ import annotations

import datetime as dt
import json
import math
import sys
import uuid
from pathlib import Path
from typing import Any

import QuantLib as ql
from pydantic import PrivateAttr

if __package__ in {None, ""}:
    _PROJECT_ROOT = Path(__file__).resolve().parents[2]
    sys.path[:0] = [str(_PROJECT_ROOT / "src"), str(_PROJECT_ROOT)]

from msm_pricing.api.curve_building_details import CurveBuildingDetails  # noqa: E402
from msm_pricing.api.curves import Curve  # noqa: E402
from msm_pricing.api.market_data_bindings import (  # noqa: E402
    PricingMarketDataSetCurveBinding,
    curve_binding_key,
)
from msm_pricing.instruments import Instrument  # noqa: E402
from msm_pricing.pricing_engine.resolvers import build_curve_from_curve_observation  # noqa: E402
from msm_pricing.scenarios.curves import CurveBumpSpec, CurveScenario  # noqa: E402
from msm_pricing.scenarios.valuation import (  # noqa: E402
    ValuationScenario,
    run_valuation_scenario_workflow,
)
from msm_pricing.valuation import (  # noqa: E402
    PricingValuationContext,
    ValuationLine,
    ValuationPosition,
)


class ThirtyDayDiscountInstrument(Instrument):
    """Small offline instrument that prices from an injected curve handle."""

    notional: float
    floating_rate_index_uid: uuid.UUID

    _curve_handle: ql.YieldTermStructureHandle | None = PrivateAttr(default=None)

    def reset_curve(self, curve_handle: ql.YieldTermStructureHandle) -> None:
        self._curve_handle = curve_handle

    def price(self, *, market_data_set: object = None) -> float:
        if self.valuation_date is None:
            raise RuntimeError("valuation_date was not prepared")
        if self._curve_handle is None:
            raise RuntimeError("curve handle was not injected")
        ql.Settings.instance().evaluationDate = _ql_date(self.valuation_date)
        return self.notional * float(
            self._curve_handle.discount(_ql_date(self.valuation_date) + 30)
        )

    def analytics(self, *, market_data_set: object = None) -> dict[str, float]:
        if self.valuation_date is None:
            raise RuntimeError("valuation_date was not prepared")
        return {"notional": self.notional}

    def get_cashflows(self, *, market_data_set: object = None) -> dict[str, list[dict[str, object]]]:
        if self.valuation_date is None:
            raise RuntimeError("valuation_date was not prepared")
        payment_date = self.valuation_date + dt.timedelta(days=30)
        return {
            "projected": [
                {
                    "payment_date": payment_date.date(),
                    "amount": self.price() - self.notional,
                }
            ]
        }

    def z_spread(self, target_dirty_price: float, *, discount_curve: object = None) -> float:
        if self.valuation_date is None:
            raise RuntimeError("valuation_date was not prepared")
        if not isinstance(discount_curve, ql.YieldTermStructureHandle):
            raise TypeError("discount_curve must be a QuantLib YieldTermStructureHandle")
        today = _ql_date(self.valuation_date)
        target = today + 30
        year_fraction = ql.Actual360().yearFraction(today, target)
        base_discount = float(discount_curve.discount(target))
        target_discount = float(target_dirty_price) / self.notional
        return -math.log(target_discount / base_discount) / year_fraction


def build_valuation_scenario_workflow_example() -> dict[str, Any]:
    valuation_date = dt.datetime(2026, 1, 1, tzinfo=dt.UTC)
    index_uid = uuid.UUID("00000000-0000-4000-8000-000000000221")
    curve_uid = uuid.UUID("00000000-0000-4000-8000-000000000321")
    curve = Curve(
        uid=curve_uid,
        unique_identifier="USD-SOFR-DEMO",
        display_name="USD SOFR Demo",
        curve_type="discount",
        currency_code="USD",
    )
    building_details = CurveBuildingDetails(
        curve_uid=curve.uid,
        builder_type="zero_rate_curve",
        quote_convention="zero_rate",
        rate_unit="decimal",
        day_counter_code="Actual360",
        calendar_code="TARGET",
        interpolation_method="log_linear_discount",
        compounding="simple",
        extrapolation_policy="enabled",
    )
    observation = {
        "curve_identifier": curve.unique_identifier,
        "time_index": valuation_date,
        "nodes": [
            {"days_to_maturity": 30, "zero": 0.05},
            {"days_to_maturity": 180, "zero": 0.052},
            {"days_to_maturity": 365, "zero": 0.054},
        ],
        "key_nodes": [
            {
                "days_to_maturity": 30,
                "quote": 0.05,
                "quote_type": "zero_rate",
                "quote_unit": "decimal",
            },
            {
                "days_to_maturity": 180,
                "quote": 0.052,
                "quote_type": "zero_rate",
                "quote_unit": "decimal",
            },
            {
                "days_to_maturity": 365,
                "quote": 0.054,
                "quote_type": "zero_rate",
                "quote_unit": "decimal",
            },
        ],
        "metadata_json": {"source": "offline-example"},
    }
    base_handle = build_curve_from_curve_observation(
        curve=curve,
        building_details=building_details,
        observation=observation,
        effective_curve_date=valuation_date,
    )
    instrument = ThirtyDayDiscountInstrument(
        notional=1_000_000.0,
        floating_rate_index_uid=index_uid,
    )
    position = ValuationPosition(
        valuation_date=valuation_date,
        lines=[
            ValuationLine(
                instrument=instrument,
                units=1.0,
                metadata_json={"observed_dirty_price": 996_000.0},
            )
        ],
    )
    context = PricingValuationContext.prepare_for_position(
        position,
        resolve_market_data_set=False,
    )
    binding = PricingMarketDataSetCurveBinding(
        uid=uuid.UUID("00000000-0000-4000-8000-000000000421"),
        market_data_set_uid=uuid.UUID("00000000-0000-4000-8000-000000000521"),
        binding_key=curve_binding_key(
            role_key="projection",
            selector_type="index",
            selector_key=str(index_uid),
            quote_side=None,
        ),
        role_key="projection",
        selector_type="index",
        selector_key=str(index_uid),
        curve_uid=curve.uid,
    )
    context.curve_bindings[binding.binding_key] = binding
    context.curves[curve.uid] = curve
    context.curve_building_details[curve.uid] = building_details
    context.curve_observations[curve.uid] = observation
    context.curve_observation_dates[curve.uid] = valuation_date
    context.curve_handles[curve.uid] = base_handle

    result = run_valuation_scenario_workflow(
        position,
        ValuationScenario(
            name="parallel-up-25bp",
            curve_scenario=CurveScenario(
                name="parallel-up-25bp",
                shocks_by_curve_identifier={
                    curve.unique_identifier: CurveBumpSpec(parallel_bp=25.0)
                },
            ),
        ),
        context=context,
        carry_days=30,
    )
    scenario = result.scenarios[0]
    return {
        "base_total_market_value": result.base.total_market_value,
        "scenario_name": scenario.scenario.name,
        "scenario_total_market_value": scenario.run.total_market_value,
        "line_impacts": [
            {
                "line_index": row.line_index,
                "base_market_value": row.base_market_value,
                "scenario_market_value": row.scenario_market_value,
                "market_value_delta": row.market_value_delta,
            }
            for row in scenario.impacts
        ],
        "carry_impacts": [
            {
                "line_index": row.line_index,
                "base_carry": row.base_carry,
                "scenario_carry": row.scenario_carry,
                "carry_impact": row.carry_impact,
            }
            for row in scenario.carry_impacts
        ],
        "observed_z_spread_overlays": [
            {
                "line_index": row.line_index,
                "target_dirty_price": row.target_dirty_price,
                "z_spread_decimal": row.z_spread_decimal,
                "curve_identifier": row.curve_identifier,
                "status": row.status,
            }
            for row in result.observed_z_spread_overlays
        ],
        "diagnostics": [
            {
                "stage": row.stage,
                "line_index": row.line_index,
                "message": row.message,
            }
            for row in result.diagnostics
        ],
    }


def _ql_date(value: dt.datetime) -> ql.Date:
    return ql.Date(value.day, value.month, value.year)


if __name__ == "__main__":
    print(json.dumps(build_valuation_scenario_workflow_example(), default=str, indent=2))
