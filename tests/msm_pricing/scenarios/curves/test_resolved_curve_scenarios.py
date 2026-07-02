from __future__ import annotations

import datetime as dt
import uuid
from typing import Any

import pytest
from pydantic import PrivateAttr

from msm_pricing.api.curve_building_details import CurveBuildingDetails
from msm_pricing.api.curves import Curve
from msm_pricing.api.market_data_bindings import (
    PricingMarketDataSetCurveBinding,
    curve_binding_key,
)
from msm_pricing.instruments import Instrument
from msm_pricing.scenarios.curves import (
    CurveBumpSpec,
    CurveScenario,
    LineCurveResolution,
    price_curve_scenario,
    price_resolved_curve_scenario,
)
from msm_pricing.scenarios.curves import engine
from msm_pricing.valuation import PricingValuationContext, ValuationLine, ValuationPosition


class CurveOverrideInstrument(Instrument):
    price_value: float = 100.0
    floating_rate_index_uid: uuid.UUID | None = None
    benchmark_rate_index_uid: uuid.UUID | None = None

    _curve_bump: float = PrivateAttr(default=0.0)

    def reset_curve(self, curve_handle: object) -> None:
        self._curve_bump = float(curve_handle)

    def price(
        self, *, market_data_set: object = None, curve_quote_side: str | None = None
    ) -> float:
        if self.valuation_date is None:
            raise ValueError("valuation_date was not set")
        return self.price_value + self._curve_bump


def _position(*instruments: CurveOverrideInstrument) -> ValuationPosition:
    return ValuationPosition(
        valuation_date=dt.datetime(2026, 1, 1, tzinfo=dt.UTC),
        lines=[
            ValuationLine(instrument=instrument, units=float(index + 1))
            for index, instrument in enumerate(instruments)
        ],
    )


def _resolution(
    *,
    line_index: int,
    curve_identifier: str,
    base_handle: object,
    scenario_handle: object | None = None,
    role_key: str = "projection",
    curve_uid: uuid.UUID | None = None,
    selector_key: str | None = None,
    observed_z_spread_decimal: float | None = None,
) -> LineCurveResolution:
    return LineCurveResolution(
        line_index=line_index,
        role_key=role_key,
        selector_type="index",
        selector_key=selector_key or str(uuid.uuid4()),
        quote_side=None,
        curve_uid=curve_uid or uuid.uuid5(uuid.NAMESPACE_DNS, curve_identifier),
        curve_identifier=curve_identifier,
        base_handle=base_handle,
        scenario_handle=scenario_handle,
        observed_z_spread_decimal=observed_z_spread_decimal,
    )


def _curve(
    *,
    curve_uid: uuid.UUID,
    unique_identifier: str,
) -> Curve:
    return Curve(
        uid=curve_uid,
        unique_identifier=unique_identifier,
        display_name=unique_identifier,
        curve_type="discount",
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


def _observation(curve_identifier: str) -> dict[str, object]:
    return {
        "curve_identifier": curve_identifier,
        "time_index": dt.datetime(2026, 1, 1, tzinfo=dt.UTC),
        "nodes": [{"days_to_maturity": 30, "zero": 0.05}],
        "key_nodes": [
            {
                "days_to_maturity": 30,
                "quote": 0.05,
                "quote_type": "zero_rate",
                "quote_unit": "decimal",
            }
        ],
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
    binding = _binding(index_uid=index_uid, curve_uid=curve.uid)
    context.curve_bindings[binding.binding_key] = binding
    context.curves[curve.uid] = curve
    context.curve_building_details[curve.uid] = _details(curve.uid)
    context.curve_observations[curve.uid] = _observation(curve.unique_identifier)
    context.curve_observation_dates[curve.uid] = dt.datetime(2026, 1, 1, tzinfo=dt.UTC)
    context.curve_handles[curve.uid] = base_handle
    return context


def test_resolved_empty_scenario_reuses_base_handles() -> None:
    curve_identifier = "USD-SOFR"
    position = _position(CurveOverrideInstrument(floating_rate_index_uid=uuid.uuid4()))

    result = price_resolved_curve_scenario(
        position,
        CurveScenario(name="empty"),
        line_curve_resolutions=[
            _resolution(
                line_index=0,
                curve_identifier=curve_identifier,
                base_handle=10.0,
            )
        ],
    )

    assert result.base_market_value == pytest.approx(110.0)
    assert result.scenario_market_value == pytest.approx(110.0)
    assert result.market_value_delta == pytest.approx(0.0)


def test_resolved_shocked_curve_uses_supplied_scenario_handle(monkeypatch) -> None:
    curve_identifier = "USD-SOFR"
    position = _position(CurveOverrideInstrument(floating_rate_index_uid=uuid.uuid4()))
    monkeypatch.setattr(
        engine,
        "resolve_line_curve_resolutions",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("no resolution")),
    )
    monkeypatch.setattr(
        engine,
        "build_scenario_curve_handle",
        lambda **_kwargs: (_ for _ in ()).throw(AssertionError("no build")),
    )

    result = price_resolved_curve_scenario(
        position,
        CurveScenario(
            name="up",
            shocks_by_curve_identifier={curve_identifier: CurveBumpSpec(parallel_bp=25.0)},
        ),
        line_curve_resolutions=[
            _resolution(
                line_index=0,
                curve_identifier=curve_identifier,
                base_handle=10.0,
                scenario_handle=20.0,
            )
        ],
    )

    assert result.base_market_value == pytest.approx(110.0)
    assert result.scenario_market_value == pytest.approx(120.0)
    assert result.market_value_delta == pytest.approx(10.0)


def test_resolved_shared_curve_reuses_supplied_handles_across_lines() -> None:
    curve_identifier = "USD-SOFR"
    curve_uid = uuid.uuid4()
    position = _position(
        CurveOverrideInstrument(floating_rate_index_uid=uuid.uuid4()),
        CurveOverrideInstrument(floating_rate_index_uid=uuid.uuid4()),
    )

    result = price_resolved_curve_scenario(
        position,
        CurveScenario(
            shocks_by_curve_identifier={curve_identifier: CurveBumpSpec(parallel_bp=25.0)}
        ),
        line_curve_resolutions=[
            _resolution(
                line_index=0,
                curve_identifier=curve_identifier,
                curve_uid=curve_uid,
                base_handle=10.0,
                scenario_handle=20.0,
            ),
            _resolution(
                line_index=1,
                curve_identifier=curve_identifier,
                curve_uid=curve_uid,
                base_handle=10.0,
                scenario_handle=20.0,
            ),
        ],
    )

    assert result.base_market_value == pytest.approx(330.0)
    assert result.scenario_market_value == pytest.approx(360.0)
    assert result.curve_shocks == (
        {
            "curve_identifier": curve_identifier,
            "parallel_bp": 25.0,
            "keyrate_bp": {},
            "line_count": 2,
        },
    )


def test_resolved_mapping_input_selects_projection_for_floating_lines() -> None:
    projection_curve = "USD-PROJECTION"
    benchmark_curve = "USD-BENCHMARK"
    position = _position(
        CurveOverrideInstrument(
            floating_rate_index_uid=uuid.uuid4(),
            benchmark_rate_index_uid=uuid.uuid4(),
        )
    )

    result = price_resolved_curve_scenario(
        position,
        CurveScenario(
            shocks_by_curve_identifier={projection_curve: CurveBumpSpec(parallel_bp=25.0)}
        ),
        line_curve_resolutions={
            0: [
                _resolution(
                    line_index=0,
                    curve_identifier=benchmark_curve,
                    role_key="z_spread_base",
                    base_handle=90.0,
                    scenario_handle=95.0,
                ),
                _resolution(
                    line_index=0,
                    curve_identifier=projection_curve,
                    role_key="projection",
                    base_handle=10.0,
                    scenario_handle=20.0,
                ),
            ]
        },
    )

    assert result.base_market_value == pytest.approx(110.0)
    assert result.scenario_market_value == pytest.approx(120.0)


def test_resolved_missing_scenario_handle_is_strict_failure() -> None:
    curve_identifier = "USD-SOFR"
    position = _position(CurveOverrideInstrument(floating_rate_index_uid=uuid.uuid4()))

    with pytest.raises(RuntimeError, match="no scenario handle"):
        price_resolved_curve_scenario(
            position,
            CurveScenario(
                shocks_by_curve_identifier={curve_identifier: CurveBumpSpec(parallel_bp=25.0)}
            ),
            line_curve_resolutions=[
                _resolution(
                    line_index=0,
                    curve_identifier=curve_identifier,
                    base_handle=10.0,
                    scenario_handle=None,
                )
            ],
        )


def test_resolved_unselected_shock_is_structured_diagnostic() -> None:
    projection_curve = "USD-PROJECTION"
    benchmark_curve = "USD-BENCHMARK"
    position = _position(
        CurveOverrideInstrument(
            floating_rate_index_uid=uuid.uuid4(),
            benchmark_rate_index_uid=uuid.uuid4(),
        )
    )

    result = price_resolved_curve_scenario(
        position,
        CurveScenario(
            shocks_by_curve_identifier={benchmark_curve: CurveBumpSpec(parallel_bp=25.0)}
        ),
        line_curve_resolutions=[
            _resolution(
                line_index=0,
                curve_identifier=projection_curve,
                role_key="projection",
                base_handle=10.0,
            ),
            _resolution(
                line_index=0,
                curve_identifier=benchmark_curve,
                role_key="z_spread_base",
                base_handle=90.0,
                scenario_handle=95.0,
            ),
        ],
        strict=False,
    )

    assert result.errors
    assert result.errors[0].stage == "line_curve_selection"
    assert result.base_market_value == pytest.approx(110.0)
    assert result.scenario_market_value == pytest.approx(110.0)


def test_resolved_observed_z_spread_overlay_is_line_local(monkeypatch) -> None:
    curve_identifier = "USD-SOFR"
    first = CurveOverrideInstrument(floating_rate_index_uid=uuid.uuid4())
    second = CurveOverrideInstrument(floating_rate_index_uid=uuid.uuid4())
    position = ValuationPosition(
        valuation_date=dt.datetime(2026, 1, 1, tzinfo=dt.UTC),
        lines=[
            ValuationLine(
                instrument=first,
                units=1.0,
                metadata_json={"observed_z_spread_decimal": 0.0025},
            ),
            ValuationLine(instrument=second, units=1.0),
        ],
    )
    captured: dict[str, Any] = {}
    monkeypatch.setattr(
        engine,
        "apply_z_spread_to_curve",
        lambda handle, spread: f"overlay:{handle}:{spread}",
    )

    def fake_price_scenario(**kwargs: Any) -> dict[str, Any]:
        captured.update(kwargs)
        return {
            "lines": [],
            "base_market_value": 1.0,
            "scenario_market_value": 2.0,
            "market_value_delta": 1.0,
        }

    monkeypatch.setattr(engine, "price_scenario", fake_price_scenario)

    result = price_resolved_curve_scenario(
        position,
        CurveScenario(
            shocks_by_curve_identifier={curve_identifier: CurveBumpSpec(parallel_bp=25.0)}
        ),
        line_curve_resolutions=[
            _resolution(
                line_index=0,
                curve_identifier=curve_identifier,
                base_handle=10.0,
                scenario_handle=20.0,
            ),
            _resolution(
                line_index=1,
                curve_identifier=curve_identifier,
                base_handle=30.0,
                scenario_handle=40.0,
            ),
        ],
    )

    assert captured["line_curve_handles"] == {0: "overlay:10.0:0.0025", 1: 30.0}
    assert captured["scenario_curve_handles"] == {0: "overlay:20.0:0.0025", 1: 40.0}
    assert result.market_value_delta == 1.0


def test_resolved_path_does_not_prepare_backend_curve_observations(monkeypatch) -> None:
    curve_identifier = "USD-SOFR"
    position = ValuationPosition(
        valuation_date=dt.datetime(2026, 1, 1, tzinfo=dt.UTC),
        market_data_set=uuid.uuid4(),
        lines=[
            ValuationLine(
                instrument=CurveOverrideInstrument(floating_rate_index_uid=uuid.uuid4()),
                units=1.0,
            )
        ],
    )
    monkeypatch.setattr(
        PricingValuationContext,
        "_prepare_resolution_caches",
        lambda _self: (_ for _ in ()).throw(AssertionError("no backend resolution")),
    )
    monkeypatch.setattr(
        engine,
        "build_scenario_curve_handle",
        lambda **_kwargs: (_ for _ in ()).throw(AssertionError("no build")),
    )

    result = price_resolved_curve_scenario(
        position,
        CurveScenario(
            shocks_by_curve_identifier={curve_identifier: CurveBumpSpec(parallel_bp=25.0)}
        ),
        line_curve_resolutions=[
            _resolution(
                line_index=0,
                curve_identifier=curve_identifier,
                base_handle=10.0,
                scenario_handle=20.0,
            )
        ],
    )

    assert result.market_value_delta == pytest.approx(10.0)


def test_resolved_and_context_workflows_delegate_equivalent_inputs(monkeypatch) -> None:
    curve_identifier = "USD-SOFR"
    index_uid = uuid.uuid4()
    curve_uid = uuid.uuid4()
    curve = _curve(curve_uid=curve_uid, unique_identifier=curve_identifier)
    instrument = CurveOverrideInstrument(floating_rate_index_uid=index_uid)
    position = _position(instrument)
    context = _context_with_curve(
        position,
        index_uid=index_uid,
        curve=curve,
        base_handle=10.0,
    )
    captured: list[tuple[object, object]] = []
    monkeypatch.setattr(engine, "build_scenario_curve_handle", lambda **_kwargs: 20.0)

    def fake_price_scenario(**kwargs: Any) -> dict[str, Any]:
        captured.append((kwargs["line_curve_handles"], kwargs["scenario_curve_handles"]))
        return {
            "lines": [],
            "base_market_value": 1.0,
            "scenario_market_value": 2.0,
            "market_value_delta": 1.0,
        }

    monkeypatch.setattr(engine, "price_scenario", fake_price_scenario)
    scenario = CurveScenario(
        shocks_by_curve_identifier={curve_identifier: CurveBumpSpec(parallel_bp=25.0)}
    )

    price_curve_scenario(position, scenario, context=context)
    price_resolved_curve_scenario(
        position,
        scenario,
        context=context,
        line_curve_resolutions=[
            _resolution(
                line_index=0,
                curve_identifier=curve_identifier,
                curve_uid=curve_uid,
                selector_key=str(index_uid),
                base_handle=10.0,
                scenario_handle=20.0,
            )
        ],
    )

    assert captured == [({0: 10.0}, {0: 20.0}), ({0: 10.0}, {0: 20.0})]
