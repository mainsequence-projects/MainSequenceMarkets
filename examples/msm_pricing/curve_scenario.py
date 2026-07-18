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

from msm_pricing.api.curve_building_details import CurveBuildingDetails  # noqa: E402
from msm_pricing.api.curves import Curve  # noqa: E402
from msm_pricing.api.market_data_bindings import (  # noqa: E402
    PricingMarketDataSetCurveBinding,
    curve_binding_key,
)
from msm_pricing.instruments import Instrument  # noqa: E402
from msm_pricing.pricing_engine.resolvers import build_curve_from_curve_observation  # noqa: E402
from msm_pricing.scenarios.curves import (  # noqa: E402
    CurveBumpSpec,
    CurveScenario,
    price_curve_scenario,
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

    _discount_curve_handle: ql.YieldTermStructureHandle | None = PrivateAttr(default=None)

    def reset_curves(
        self,
        *,
        projection_curve: ql.YieldTermStructureHandle | None = None,
        forwarding_curve: ql.YieldTermStructureHandle | None = None,
        discount_curve: ql.YieldTermStructureHandle | None = None,
    ) -> None:
        projection = projection_curve if projection_curve is not None else forwarding_curve
        if projection is None:
            raise RuntimeError("projection curve was not injected")
        if discount_curve is None:
            raise RuntimeError("discount curve was not injected")
        self._discount_curve_handle = discount_curve

    def price(self, *, market_data_set: object = None, curve_quote_side: str | None = None) -> float:
        if self.valuation_date is None:
            raise RuntimeError("valuation_date was not prepared")
        if self._discount_curve_handle is None:
            raise RuntimeError("discount curve handle was not injected")
        ql.Settings.instance().evaluationDate = ql.Date(
            self.valuation_date.day,
            self.valuation_date.month,
            self.valuation_date.year,
        )
        target = ql.Settings.instance().evaluationDate + 30
        return self.notional * float(self._discount_curve_handle.discount(target))


def build_curve_scenario_example() -> dict[str, Any]:
    valuation_date = dt.datetime(2026, 1, 1, tzinfo=dt.UTC)
    index_uid = uuid.UUID("00000000-0000-4000-8000-000000000201")
    curve_uid = uuid.UUID("00000000-0000-4000-8000-000000000301")
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
        lines=[ValuationLine(instrument=instrument, units=1.0)],
    )
    context = PricingValuationContext.prepare_for_position(
        position,
        resolve_market_data_set=False,
    )
    binding = PricingMarketDataSetCurveBinding(
        uid=uuid.UUID("00000000-0000-4000-8000-000000000401"),
        market_data_set_uid=uuid.UUID("00000000-0000-4000-8000-000000000501"),
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
    discount_binding = PricingMarketDataSetCurveBinding(
        uid=uuid.UUID("00000000-0000-4000-8000-000000000402"),
        market_data_set_uid=uuid.UUID("00000000-0000-4000-8000-000000000501"),
        binding_key=curve_binding_key(
            role_key="discount",
            selector_type="index",
            selector_key=str(index_uid),
            quote_side=None,
        ),
        role_key="discount",
        selector_type="index",
        selector_key=str(index_uid),
        curve_uid=curve.uid,
    )
    context.curve_bindings[discount_binding.binding_key] = discount_binding
    context.curves[curve.uid] = curve
    context.curve_building_details[curve.uid] = building_details
    context.curve_observations[curve.uid] = observation
    context.curve_observation_dates[curve.uid] = valuation_date
    context.curve_handles[curve.uid] = base_handle

    result = price_curve_scenario(
        position,
        CurveScenario(
            name="parallel-up-25bp",
            shocks_by_curve_identifier={
                curve.unique_identifier: CurveBumpSpec(parallel_bp=25.0)
            },
        ),
        context=context,
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


if __name__ == "__main__":
    print(json.dumps(build_curve_scenario_example(), default=str, indent=2))
