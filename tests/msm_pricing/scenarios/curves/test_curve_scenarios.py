from __future__ import annotations

import datetime as dt
import inspect
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
from msm_pricing.scenarios import curves
from msm_pricing.scenarios.curves import (
    CurveBumpSpec,
    CurveScenario,
    price_curve_scenario,
)
from msm_pricing.scenarios.curves import engine
from msm_pricing.valuation import (
    PricingValuationContext,
    ValuationLine,
    ValuationPosition,
)


class CurveOverrideInstrument(Instrument):
    price_value: float = 100.0
    floating_rate_index_uid: uuid.UUID | None = None
    float_leg_index_uid: uuid.UUID | None = None
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


def _curve(
    *,
    curve_uid: uuid.UUID | None = None,
    unique_identifier: str = "USD-SOFR-DISCOUNT",
) -> Curve:
    return Curve(
        uid=curve_uid or uuid.uuid4(),
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
    quote_side: str | None = None,
) -> PricingMarketDataSetCurveBinding:
    return PricingMarketDataSetCurveBinding(
        uid=uuid.uuid4(),
        market_data_set_uid=uuid.uuid4(),
        binding_key=curve_binding_key(
            role_key=role_key,
            selector_type="index",
            selector_key=str(index_uid),
            quote_side=quote_side,
        ),
        role_key=role_key,
        selector_type="index",
        selector_key=str(index_uid),
        quote_side=quote_side,
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
    role_key: str = "projection",
) -> PricingValuationContext:
    context = PricingValuationContext.prepare_for_position(
        position,
        resolve_market_data_set=False,
    )
    binding = _binding(index_uid=index_uid, curve_uid=curve.uid, role_key=role_key)
    context.curve_bindings[binding.binding_key] = binding
    context.curves[curve.uid] = curve
    context.curve_building_details[curve.uid] = _details(curve.uid)
    context.curve_observations[curve.uid] = _observation(curve.unique_identifier)
    context.curve_observation_dates[curve.uid] = dt.datetime(2026, 1, 1, tzinfo=dt.UTC)
    context.curve_handles[curve.uid] = base_handle
    return context


def test_price_curve_scenario_builds_shared_curve_once_and_delegates(monkeypatch) -> None:
    index_uid = uuid.uuid4()
    curve = _curve()
    first = CurveOverrideInstrument(floating_rate_index_uid=index_uid)
    second = CurveOverrideInstrument(floating_rate_index_uid=index_uid)
    position = ValuationPosition(
        valuation_date=dt.datetime(2026, 1, 1, tzinfo=dt.UTC),
        lines=[
            ValuationLine(instrument=first, units=1.0),
            ValuationLine(instrument=second, units=2.0),
        ],
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
        engine,
        "build_curve_from_curve_observation",
        fake_build_curve_from_curve_observation,
    )

    result = price_curve_scenario(
        position,
        CurveScenario(
            name="up-100",
            shocks_by_curve_identifier={curve.unique_identifier: CurveBumpSpec(parallel_bp=100.0)},
        ),
        context=context,
    )

    assert len(build_calls) == 1
    assert build_calls[0]["observation"]["nodes"] == [
        {"days_to_maturity": 30, "zero": pytest.approx(0.06)}
    ]
    assert context.curve_observations[curve.uid]["key_nodes"][0]["quote"] == 0.05
    assert result.base_market_value == pytest.approx(330.0)
    assert result.scenario_market_value == pytest.approx(480.0)
    assert result.market_value_delta == pytest.approx(150.0)
    assert len(result.line_impacts) == 2
    assert result.curve_shocks[0]["curve_identifier"] == curve.unique_identifier
    assert first._curve_bump == 0.0
    assert second._curve_bump == 0.0


def test_empty_curve_scenario_reuses_base_handles(monkeypatch) -> None:
    index_uid = uuid.uuid4()
    curve = _curve()
    instrument = CurveOverrideInstrument(floating_rate_index_uid=index_uid)
    position = ValuationPosition(
        valuation_date=dt.datetime(2026, 1, 1, tzinfo=dt.UTC),
        lines=[ValuationLine(instrument=instrument, units=1.0)],
    )
    context = _context_with_curve(
        position,
        index_uid=index_uid,
        curve=curve,
        base_handle=10.0,
    )
    monkeypatch.setattr(
        engine,
        "build_curve_from_curve_observation",
        lambda **_kwargs: (_ for _ in ()).throw(AssertionError("no rebuild")),
    )

    result = price_curve_scenario(position, CurveScenario(name="empty"), context=context)

    assert result.base_market_value == pytest.approx(110.0)
    assert result.scenario_market_value == pytest.approx(110.0)
    assert result.market_value_delta == pytest.approx(0.0)


def test_non_empty_unmatched_curve_shock_is_strict_preflight_failure() -> None:
    position = ValuationPosition(
        valuation_date=dt.datetime(2026, 1, 1, tzinfo=dt.UTC),
        lines=[ValuationLine(instrument=CurveOverrideInstrument(), units=1.0)],
    )
    context = PricingValuationContext.prepare_for_position(position)

    with pytest.raises(RuntimeError, match="not resolved"):
        price_curve_scenario(
            position,
            CurveScenario(
                shocks_by_curve_identifier={"UNRESOLVED": CurveBumpSpec(parallel_bp=1.0)}
            ),
            context=context,
        )


def test_unselected_related_curve_shock_is_not_silently_dropped(monkeypatch) -> None:
    projection_index_uid = uuid.uuid4()
    benchmark_index_uid = uuid.uuid4()
    projection_curve = _curve(unique_identifier="USD-PROJECTION")
    benchmark_curve = _curve(unique_identifier="USD-BENCHMARK")
    instrument = CurveOverrideInstrument(
        floating_rate_index_uid=projection_index_uid,
        benchmark_rate_index_uid=benchmark_index_uid,
    )
    position = ValuationPosition(
        valuation_date=dt.datetime(2026, 1, 1, tzinfo=dt.UTC),
        lines=[ValuationLine(instrument=instrument, units=1.0)],
    )
    context = _context_with_curve(
        position,
        index_uid=projection_index_uid,
        curve=projection_curve,
        base_handle=10.0,
    )
    benchmark_binding = _binding(
        index_uid=benchmark_index_uid,
        curve_uid=benchmark_curve.uid,
        role_key="z_spread_base",
    )
    context.curve_bindings[benchmark_binding.binding_key] = benchmark_binding
    context.curves[benchmark_curve.uid] = benchmark_curve
    context.curve_building_details[benchmark_curve.uid] = _details(benchmark_curve.uid)
    context.curve_observations[benchmark_curve.uid] = _observation(
        benchmark_curve.unique_identifier
    )
    context.curve_observation_dates[benchmark_curve.uid] = dt.datetime(
        2026,
        1,
        1,
        tzinfo=dt.UTC,
    )
    context.curve_handles[benchmark_curve.uid] = 20.0
    monkeypatch.setattr(
        engine,
        "build_curve_from_curve_observation",
        lambda **kwargs: float(kwargs["observation"]["nodes"][0]["zero"]) * 1000.0,
    )

    with pytest.raises(RuntimeError, match="single reset_curve"):
        price_curve_scenario(
            position,
            CurveScenario(
                shocks_by_curve_identifier={
                    benchmark_curve.unique_identifier: CurveBumpSpec(parallel_bp=100.0)
                }
            ),
            context=context,
        )


def test_diagnostic_mode_collects_unmatched_shock_errors() -> None:
    position = ValuationPosition(
        valuation_date=dt.datetime(2026, 1, 1, tzinfo=dt.UTC),
        lines=[ValuationLine(instrument=CurveOverrideInstrument(), units=1.0)],
    )
    context = PricingValuationContext.prepare_for_position(position)

    result = price_curve_scenario(
        position,
        CurveScenario(shocks_by_curve_identifier={"UNRESOLVED": CurveBumpSpec(parallel_bp=1.0)}),
        context=context,
        strict=False,
    )

    assert result.errors
    assert result.errors[0].stage == "preflight"
    assert result.raw_price_scenario_result["market_value_delta"] == 0.0


def test_z_spread_overlays_are_runtime_line_handles_only(monkeypatch) -> None:
    index_uid = uuid.uuid4()
    curve = _curve()
    instrument = CurveOverrideInstrument(floating_rate_index_uid=index_uid)
    position = ValuationPosition(
        valuation_date=dt.datetime(2026, 1, 1, tzinfo=dt.UTC),
        lines=[
            ValuationLine(
                instrument=instrument,
                units=1.0,
                metadata_json={"observed_z_spread_decimal": 0.0025},
            )
        ],
    )
    context = _context_with_curve(
        position,
        index_uid=index_uid,
        curve=curve,
        base_handle=10.0,
    )
    captured: dict[str, Any] = {}

    monkeypatch.setattr(
        engine,
        "build_curve_from_curve_observation",
        lambda **kwargs: float(kwargs["observation"]["nodes"][0]["zero"]) * 1000.0,
    )
    monkeypatch.setattr(
        engine,
        "apply_z_spread_to_curve",
        lambda handle, spread: f"overlay:{round(float(handle), 10)}:{spread}",
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

    result = price_curve_scenario(
        position,
        CurveScenario(
            shocks_by_curve_identifier={curve.unique_identifier: CurveBumpSpec(parallel_bp=100.0)}
        ),
        context=context,
    )

    assert captured["line_curve_handles"] == {0: "overlay:10.0:0.0025"}
    assert captured["scenario_curve_handles"] == {0: "overlay:60.0:0.0025"}
    assert context.curve_handles[curve.uid] == 10.0
    assert result.market_value_delta == 1.0


def test_curve_scenarios_do_not_import_connector_rebuilds() -> None:
    source = inspect.getsource(engine)

    assert "valmer_connectors" not in source
    assert "local_valmer" not in source
    assert "DEFAULT_CURVE_QUOTE_SIDE" not in source


def test_public_curve_scenario_exports_have_docstrings_and_annotations() -> None:
    for name in curves.__all__:
        exported = getattr(curves, name)
        if name == "LineCurveResolutionInput":
            continue
        assert inspect.getdoc(exported), name
        if inspect.isfunction(exported):
            signature = inspect.signature(exported)
            assert signature.return_annotation is not inspect.Signature.empty, name
            for parameter in signature.parameters.values():
                assert parameter.annotation is not inspect.Parameter.empty, (
                    name,
                    parameter.name,
                )
