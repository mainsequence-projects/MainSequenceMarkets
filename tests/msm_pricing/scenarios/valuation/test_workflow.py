from __future__ import annotations

import datetime as dt
import inspect
import uuid
from typing import Any

import pytest
from pydantic import PrivateAttr

import msm_pricing
from msm_pricing.api.curve_building_details import CurveBuildingDetails
from msm_pricing.api.curves import Curve
from msm_pricing.api.market_data_bindings import (
    PricingMarketDataSetCurveBinding,
    curve_binding_key,
)
from msm_pricing.instruments import Instrument
from msm_pricing.scenarios.curves import CurveBumpSpec, CurveScenario
from msm_pricing.scenarios.curves import engine as curve_engine
from msm_pricing.scenarios.valuation import (
    ValuationScenario,
    run_valuation_scenario_workflow,
)
from msm_pricing.scenarios.valuation import engine as workflow_engine
from msm_pricing.valuation import (
    PricingValuationContext,
    ValuationLine,
    ValuationPosition,
)


class WorkflowInstrument(Instrument):
    price_value: float = 100.0
    floating_rate_index_uid: uuid.UUID | None = None
    benchmark_rate_index_uid: uuid.UUID | None = None
    fixed_cashflow_amount: float = 3.0

    _curve_bump: float = PrivateAttr(default=0.0)

    def reset_curves(
        self,
        *,
        projection_curve: object | None = None,
        forwarding_curve: object | None = None,
        discount_curve: object | None = None,
    ) -> None:
        projection = projection_curve if projection_curve is not None else forwarding_curve
        if projection is None:
            raise ValueError("projection_curve is required")
        if discount_curve is None:
            raise ValueError("discount_curve is required")
        self._curve_bump = float(discount_curve)

    def price(self, *, market_data_set: object = None) -> float:
        if self.valuation_date is None:
            raise ValueError("valuation_date was not set")
        return self.price_value + self._curve_bump

    def analytics(self, *, market_data_set: object = None) -> dict[str, float]:
        return {"duration": 2.0}

    def get_cashflows(self, *, market_data_set: object = None) -> dict[str, list[dict[str, object]]]:
        return {
            "fixed": [
                {
                    "payment_date": dt.date(2026, 1, 10),
                    "amount": self.fixed_cashflow_amount + self._curve_bump,
                }
            ]
        }

    def z_spread(self, target_dirty_price: float, *, discount_curve: object = None) -> float:
        return (float(target_dirty_price) - self.price_value - float(discount_curve)) / 1000.0


def _curve(
    *,
    curve_uid: uuid.UUID | None = None,
    unique_identifier: str = "GENERIC-DISCOUNT",
    curve_type: str = "discount",
) -> Curve:
    return Curve(
        uid=curve_uid or uuid.uuid4(),
        unique_identifier=unique_identifier,
        display_name=unique_identifier,
        curve_type=curve_type,
    )


def _details(curve_uid: uuid.UUID) -> CurveBuildingDetails:
    return CurveBuildingDetails(
        curve_uid=curve_uid,
        builder_type="zero_rate_curve",
        quote_convention="zero_rate",
        rate_unit="decimal",
        day_counter_code="Actual360",
        calendar_code="TARGET",
        interpolation_method="log_linear_discount",
        compounding="simple",
        extrapolation_policy="enabled",
    )


def _binding(
    *,
    index_uid: uuid.UUID,
    curve_uid: uuid.UUID,
    role_key: str = "projection",
) -> PricingMarketDataSetCurveBinding:
    return PricingMarketDataSetCurveBinding(
        uid=uuid.uuid4(),
        market_data_set_uid=uuid.uuid4(),
        binding_key=curve_binding_key(
            role_key=role_key,
            selector_type="index",
            selector_key=str(index_uid),
            quote_side=None,
        ),
        role_key=role_key,
        selector_type="index",
        selector_key=str(index_uid),
        quote_side=None,
        curve_uid=curve_uid,
    )


def _observation(curve_identifier: str, quote: float = 0.05) -> dict[str, object]:
    return {
        "curve_identifier": curve_identifier,
        "time_index": dt.datetime(2026, 1, 1, tzinfo=dt.UTC),
        "nodes": [{"days_to_maturity": 30, "zero": quote}],
        "key_nodes": [
            {
                "days_to_maturity": 30,
                "quote": quote,
                "quote_type": "zero_rate",
                "quote_unit": "decimal",
            }
        ],
        "metadata_json": {"source": "unit-test"},
    }


def _context_with_curve(
    position: ValuationPosition,
    *,
    index_uid: uuid.UUID,
    curve: Curve,
    base_handle: object,
) -> PricingValuationContext:
    context = PricingValuationContext.prepare_for_position(
        position,
        resolve_market_data_set=False,
    )
    projection_curve = _curve(
        unique_identifier=f"{curve.unique_identifier}-PROJECTION",
        curve_type="projection",
    )
    projection_binding = _binding(index_uid=index_uid, curve_uid=projection_curve.uid)
    context.curve_bindings[projection_binding.binding_key] = projection_binding
    discount_binding = _binding(index_uid=index_uid, curve_uid=curve.uid, role_key="discount")
    context.curve_bindings[discount_binding.binding_key] = discount_binding
    for cached_curve in (projection_curve, curve):
        context.curves[cached_curve.uid] = cached_curve
        context.curve_building_details[cached_curve.uid] = _details(cached_curve.uid)
        context.curve_observations[cached_curve.uid] = _observation(cached_curve.unique_identifier)
        context.curve_observation_dates[cached_curve.uid] = dt.datetime(
            2026, 1, 1, tzinfo=dt.UTC
        )
        context.curve_handles[cached_curve.uid] = base_handle
    return context


def test_workflow_prices_base_scenario_impacts_and_carry(monkeypatch) -> None:
    index_uid = uuid.uuid4()
    curve = _curve()
    instrument = WorkflowInstrument(
        floating_rate_index_uid=index_uid,
        fixed_cashflow_amount=3.0,
    )
    position = ValuationPosition(
        valuation_date=dt.datetime(2026, 1, 1, tzinfo=dt.UTC),
        lines=[ValuationLine(instrument=instrument, units=2.0)],
    )
    context = _context_with_curve(
        position,
        index_uid=index_uid,
        curve=curve,
        base_handle=10.0,
    )
    build_calls: list[dict[str, Any]] = []

    def fake_build_curve_from_curve_observation(**kwargs: Any) -> float:
        build_calls.append(kwargs)
        return float(kwargs["observation"]["nodes"][0]["zero"]) * 1000.0

    monkeypatch.setattr(
        curve_engine,
        "build_curve_from_curve_observation",
        fake_build_curve_from_curve_observation,
    )

    result = run_valuation_scenario_workflow(
        position,
        ValuationScenario(
            name="up-100",
            curve_scenario=CurveScenario(
                name="up-100",
                shocks_by_curve_identifier={
                    curve.unique_identifier: CurveBumpSpec(parallel_bp=100.0)
                },
            ),
        ),
        context=context,
        carry_days=30,
    )

    assert len(build_calls) == 1
    assert result.base.total_market_value == pytest.approx(220.0)
    assert result.scenarios[0].run.total_market_value == pytest.approx(320.0)
    assert result.scenarios[0].impacts[0].market_value_delta == pytest.approx(100.0)
    assert result.scenarios[0].carry_impacts[0].base_carry == pytest.approx(26.0)
    assert result.scenarios[0].carry_impacts[0].scenario_carry == pytest.approx(126.0)
    assert [resolution.role_key for resolution in result.runtime_resolutions[:2]] == [
        "projection",
        "discount",
    ]
    assert result.runtime_resolutions[1].curve_identifier == curve.unique_identifier
    assert result.scenarios[0].runtime_overrides is not None
    assert result.scenarios[0].runtime_overrides.scenario_curve_handles == {
        0: {"projection": 10.0, "discount": pytest.approx(60.0)}
    }
    assert instrument._curve_bump == 0.0


def test_workflow_forwards_overnight_index_resolver(monkeypatch) -> None:
    index_uid = uuid.uuid4()
    curve = _curve()
    position = ValuationPosition(
        valuation_date=dt.datetime(2026, 1, 1, tzinfo=dt.UTC),
        lines=[
            ValuationLine(
                instrument=WorkflowInstrument(floating_rate_index_uid=index_uid),
                units=1.0,
            )
        ],
    )
    context = _context_with_curve(
        position,
        index_uid=index_uid,
        curve=curve,
        base_handle=10.0,
    )
    overnight_index = object()

    def overnight_index_resolver(_index_name: str | None, _node: object) -> object:
        return overnight_index

    build_calls: list[dict[str, Any]] = []

    def fake_build_scenario_curve_handle(**kwargs: Any) -> float:
        build_calls.append(kwargs)
        return 20.0

    monkeypatch.setattr(
        curve_engine,
        "build_scenario_curve_handle",
        fake_build_scenario_curve_handle,
    )

    result = run_valuation_scenario_workflow(
        position,
        ValuationScenario(
            name="up-100",
            curve_scenario=CurveScenario(
                name="up-100",
                shocks_by_curve_identifier={
                    curve.unique_identifier: CurveBumpSpec(parallel_bp=100.0)
                },
            ),
        ),
        context=context,
        overnight_index_resolver=overnight_index_resolver,
    )

    assert len(build_calls) == 1
    assert build_calls[0]["overnight_index_resolver"] is overnight_index_resolver
    assert result.scenarios[0].run.total_market_value == pytest.approx(120.0)


def test_observed_dirty_price_z_spread_overlay_is_explicit_and_runtime_only(
    monkeypatch,
) -> None:
    index_uid = uuid.uuid4()
    curve = _curve()
    line_metadata = {"observed_dirty_price": 115.0}
    instrument = WorkflowInstrument(floating_rate_index_uid=index_uid)
    position = ValuationPosition(
        valuation_date=dt.datetime(2026, 1, 1, tzinfo=dt.UTC),
        lines=[
            ValuationLine(
                instrument=instrument,
                units=1.0,
                metadata_json=line_metadata,
            )
        ],
    )
    context = _context_with_curve(
        position,
        index_uid=index_uid,
        curve=curve,
        base_handle=10.0,
    )
    monkeypatch.setattr(
        curve_engine,
        "build_curve_from_curve_observation",
        lambda **kwargs: float(kwargs["observation"]["nodes"][0]["zero"]) * 1000.0,
    )
    monkeypatch.setattr(
        workflow_engine,
        "apply_z_spread_to_curve",
        lambda handle, spread: float(handle) + float(spread) * 1000.0,
    )

    result = run_valuation_scenario_workflow(
        position,
        ValuationScenario(
            name="up-100",
            curve_scenario=CurveScenario(
                name="up-100",
                shocks_by_curve_identifier={
                    curve.unique_identifier: CurveBumpSpec(parallel_bp=100.0)
                },
            ),
        ),
        context=context,
    )

    assert len(result.observed_z_spread_overlays) == 1
    overlay = result.observed_z_spread_overlays[0]
    assert overlay.target_dirty_price == pytest.approx(115.0)
    assert overlay.z_spread_decimal == pytest.approx(0.005)
    assert result.base.total_market_value == pytest.approx(115.0)
    assert result.scenarios[0].run.total_market_value == pytest.approx(165.0)
    assert result.runtime_resolutions[0].observed_z_spread_decimal == pytest.approx(0.005)
    assert "observed_z_spread" not in line_metadata
    assert context.curve_handles[curve.uid] == 10.0
    assert instrument._curve_bump == 0.0


def test_public_valuation_scenario_exports_have_docstrings_and_annotations() -> None:
    for name in msm_pricing.scenarios.valuation.__all__:
        exported = getattr(msm_pricing.scenarios.valuation, name)
        assert inspect.getdoc(exported), name
        if inspect.isfunction(exported):
            signature = inspect.signature(exported)
            assert signature.return_annotation is not inspect.Signature.empty, name
            for parameter in signature.parameters.values():
                assert parameter.annotation is not inspect.Parameter.empty, (
                    name,
                    parameter.name,
                )
