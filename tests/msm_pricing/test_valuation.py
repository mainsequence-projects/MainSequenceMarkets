from __future__ import annotations

import datetime as dt
import uuid
from dataclasses import FrozenInstanceError
from typing import Any

import pandas as pd
import pytest
from pydantic import PrivateAttr

import msm_pricing
from msm.api.indices import Index
from msm_pricing.api.curve_building_details import CurveBuildingDetails
from msm_pricing.api.curves import Curve
from msm_pricing.api.index_convention_details import IndexConventionDetails
from msm_pricing.api.market_data_bindings import (
    PricingMarketDataSetBinding,
    PricingMarketDataSetCurveBinding,
    curve_binding_key,
)
from msm_pricing.data_interface.data_interface import MSDataInterface
from msm_pricing.instruments import Instrument
from msm_pricing.settings import (
    PRICING_CONCEPT_DISCOUNT_CURVES,
    PRICING_CONCEPT_INTEREST_RATE_INDEX_FIXINGS,
)
from msm_pricing.valuation import (
    PricingValuationContext,
    PricingValuationContextSpec,
    ValuationLine,
    ValuationPosition,
    price_scenario,
)


class FakePricedInstrument(Instrument):
    price_value: float = 10.0
    analytics_value: dict[str, float] | None = None

    _market_data_sets: list[Any] = PrivateAttr(default_factory=list)
    _price_calls: int = PrivateAttr(default=0)

    def _apply_market_data_set(self, market_data_set=None) -> None:
        self._market_data_sets.append(market_data_set)

    def price(self, *, market_data_set=None) -> float:
        self._price_calls += 1
        if self.valuation_date is None:
            raise ValueError("valuation date was not set")
        self._market_data_sets.append(market_data_set)
        return self.price_value

    def analytics(self, *, market_data_set=None) -> dict[str, float]:
        if self.valuation_date is None:
            raise ValueError("valuation date was not set")
        self._market_data_sets.append(market_data_set)
        return self.analytics_value or {"clean_price": self.price_value, "accrued_amount": 1.5}

    def get_cashflows(self, *, market_data_set=None) -> dict[str, list[dict[str, Any]]]:
        if self.valuation_date is None:
            raise ValueError("valuation date was not set")
        self._market_data_sets.append(market_data_set)
        return {
            "fixed": [
                {"payment_date": dt.date(2026, 7, 1), "amount": 2.0},
                {"payment_date": dt.date(2026, 8, 1), "amount": 3.0},
            ]
        }

    def get_net_cashflows(self) -> pd.Series:
        if self.valuation_date is None:
            raise ValueError("valuation date was not set")
        return pd.Series(
            {
                dt.date(2026, 7, 1): 2.0,
                dt.date(2026, 8, 1): 3.0,
            },
            name="net_cashflow",
        )


class NoAnalyticsInstrument(Instrument):
    def price(self) -> float:
        return 1.0


class CashflowOnlyInstrument(Instrument):
    def price(self) -> float:
        return 1.0

    def get_cashflows(self) -> dict[str, list[dict[str, Any]]]:
        if self.valuation_date is None:
            raise ValueError("valuation date was not set")
        return {
            "fixed": [
                {"payment_date": dt.date(2026, 9, 1), "amount": 4.0},
            ]
        }


class IndexedFakePricedInstrument(FakePricedInstrument):
    floating_rate_index_uid: uuid.UUID | None = None
    float_leg_index_uid: uuid.UUID | None = None
    benchmark_rate_index_uid: uuid.UUID | None = None


class CurveOverrideInstrument(FakePricedInstrument):
    _curve_bump: float = PrivateAttr(default=0.0)

    def reset_curve(self, curve_handle) -> None:
        self._curve_bump = float(curve_handle)

    def price(self, *, market_data_set=None) -> float:
        return super().price(market_data_set=market_data_set) + self._curve_bump


def test_valuation_position_prices_lines_with_context_and_units() -> None:
    valuation_date = dt.datetime(2026, 5, 27, tzinfo=dt.UTC)
    market_data_set_uid = uuid.uuid4()
    first = FakePricedInstrument(price_value=10.0)
    second = FakePricedInstrument(price_value=4.0)

    position = ValuationPosition(
        valuation_date=valuation_date,
        market_data_set=market_data_set_uid,
        lines=[
            ValuationLine(instrument=first, units=3.0, asset_uid=uuid.uuid4()),
            ValuationLine(instrument=second, units=-2.0),
        ],
    )

    assert position.price() == 22.0
    assert first.valuation_date is None
    assert second.valuation_date is None
    assert first._market_data_sets == []
    assert second._market_data_sets == []


def test_price_breakdown_preserves_input_order_and_asset_uid() -> None:
    asset_uid = uuid.uuid4()
    instrument = FakePricedInstrument(price_value=7.0)
    position = ValuationPosition(
        valuation_date=dt.datetime(2026, 5, 27, tzinfo=dt.UTC),
        market_data_set=uuid.uuid4(),
        lines=[
            ValuationLine(
                instrument=instrument,
                units=5.0,
                asset_uid=asset_uid,
                metadata_json={"source": "unit-test"},
            )
        ],
    )

    assert position.price_breakdown() == [
        {
            "line_index": 0,
            "instrument_type": "FakePricedInstrument",
            "asset_uid": asset_uid,
            "units": 5.0,
            "unit_price": 7.0,
            "market_value": 35.0,
            "metadata_json": {"source": "unit-test"},
        }
    ]


def test_valuation_position_scales_analytics_and_cashflows() -> None:
    position = ValuationPosition(
        valuation_date=dt.datetime(2026, 5, 27, tzinfo=dt.UTC),
        market_data_set=uuid.uuid4(),
        lines=[
            ValuationLine(
                instrument=FakePricedInstrument(
                    price_value=11.0,
                    analytics_value={"clean_price": 100.0, "accrued_amount": 2.0},
                ),
                units=2.0,
            )
        ],
    )

    assert position.analytics()["totals"] == {
        "clean_price": 200.0,
        "accrued_amount": 4.0,
    }
    assert position.get_cashflows()["fixed"] == [
        {
            "payment_date": dt.date(2026, 7, 1),
            "amount": 4.0,
            "line_index": 0,
            "instrument_type": "FakePricedInstrument",
            "asset_uid": None,
            "units": 2.0,
        },
        {
            "payment_date": dt.date(2026, 8, 1),
            "amount": 6.0,
            "line_index": 0,
            "instrument_type": "FakePricedInstrument",
            "asset_uid": None,
            "units": 2.0,
        },
    ]
    net_cashflows = position.get_net_cashflows()
    assert net_cashflows.to_dict() == {
        dt.date(2026, 7, 1): 4.0,
        dt.date(2026, 8, 1): 6.0,
    }


def test_valuation_position_net_cashflows_falls_back_to_cashflow_rows() -> None:
    position = ValuationPosition(
        valuation_date=dt.datetime(2026, 5, 27, tzinfo=dt.UTC),
        market_data_set=uuid.uuid4(),
        lines=[ValuationLine(instrument=CashflowOnlyInstrument(), units=3.0)],
    )

    assert position.get_net_cashflows().to_dict() == {
        dt.date(2026, 9, 1): 12.0,
    }


def test_valuation_position_rejects_non_finite_units() -> None:
    with pytest.raises(ValueError, match="units must be finite"):
        ValuationLine(instrument=FakePricedInstrument(), units=float("nan"))


def test_valuation_position_fails_for_unsupported_requested_output() -> None:
    position = ValuationPosition(
        valuation_date=dt.datetime(2026, 5, 27, tzinfo=dt.UTC),
        lines=[ValuationLine(instrument=NoAnalyticsInstrument(), units=1.0)],
    )

    with pytest.raises(TypeError, match="does not support analytics"):
        position.analytics()


def test_legacy_position_export_is_removed() -> None:
    assert not hasattr(msm_pricing, "Position")
    assert not hasattr(msm_pricing, "PositionLine")


def test_pricing_valuation_context_prepares_distinct_instrument_copy() -> None:
    valuation_date = dt.datetime(2026, 5, 27, tzinfo=dt.UTC)
    instrument = FakePricedInstrument(price_value=12.0)
    context = PricingValuationContext.prepare(
        valuation_date=valuation_date,
        market_data_set="eod",
        instruments=[instrument],
        resolve_market_data_set=False,
    )

    prepared = context.prepare_instrument(instrument)

    assert prepared is context.prepare_instrument(instrument)
    assert prepared is not instrument
    assert prepared.instrument is not instrument
    assert prepared.instrument.valuation_date == valuation_date
    assert instrument.valuation_date is None
    assert instrument._market_data_sets == []
    assert prepared.price() == 12.0
    assert instrument._price_calls == 0


def test_pricing_valuation_context_freezes_prepared_input_contract() -> None:
    valuation_date = dt.datetime(2026, 5, 27, tzinfo=dt.UTC)
    market_data_set_uid = uuid.uuid4()
    instrument = FakePricedInstrument(price_value=12.0)
    context = PricingValuationContext.prepare(
        valuation_date=valuation_date,
        market_data_set=market_data_set_uid,
        instruments=[instrument],
        curve_quote_side="MID",
    )

    assert isinstance(context.spec, PricingValuationContextSpec)
    assert context.valuation_date == valuation_date
    assert context.market_data_set == market_data_set_uid
    assert context.market_data_set_uid == market_data_set_uid
    assert context.curve_quote_side == "mid"
    assert len(context.spec.instruments) == 1
    assert context.spec.instruments[0].source_id == id(instrument)
    assert context.spec.requested_roles == ()

    with pytest.raises(FrozenInstanceError):
        context.spec = context.spec
    with pytest.raises(FrozenInstanceError):
        context.spec.valuation_date = valuation_date + dt.timedelta(days=1)
    with pytest.raises(FrozenInstanceError):
        context.market_data_set_uid = uuid.uuid4()


def test_pricing_valuation_context_rejects_mutated_instrument_terms() -> None:
    valuation_date = dt.datetime(2026, 5, 27, tzinfo=dt.UTC)
    market_data_set_uid = uuid.uuid4()
    instrument = FakePricedInstrument(price_value=12.0)
    position = ValuationPosition(
        valuation_date=valuation_date,
        market_data_set=market_data_set_uid,
        lines=[ValuationLine(instrument=instrument, units=1.0)],
    )
    context = PricingValuationContext.prepare_for_position(position)

    instrument.price_value = 13.0

    with pytest.raises(ValueError, match="Instrument terms changed"):
        context.prepare_instrument(instrument)
    with pytest.raises(ValueError, match="Instrument terms changed"):
        position.price(context=context)


def test_pricing_valuation_context_rejects_instrument_outside_prepared_universe() -> None:
    context = PricingValuationContext.prepare(
        valuation_date=dt.datetime(2026, 5, 27, tzinfo=dt.UTC),
        market_data_set=uuid.uuid4(),
        instruments=[FakePricedInstrument(price_value=12.0)],
    )

    with pytest.raises(ValueError, match="not part of the prepared"):
        context.prepare_instrument(FakePricedInstrument(price_value=13.0))


def test_valuation_position_rejects_context_for_different_instrument_universe() -> None:
    valuation_date = dt.datetime(2026, 5, 27, tzinfo=dt.UTC)
    market_data_set_uid = uuid.uuid4()
    context = PricingValuationContext.prepare(
        valuation_date=valuation_date,
        market_data_set=market_data_set_uid,
        instruments=[FakePricedInstrument(price_value=12.0)],
    )
    other_position = ValuationPosition(
        valuation_date=valuation_date,
        market_data_set=market_data_set_uid,
        lines=[ValuationLine(instrument=FakePricedInstrument(price_value=12.0), units=1.0)],
    )

    with pytest.raises(ValueError, match="instrument universe"):
        other_position.price(context=context)


def test_valuation_position_rejects_context_for_different_line_shape() -> None:
    valuation_date = dt.datetime(2026, 5, 27, tzinfo=dt.UTC)
    market_data_set_uid = uuid.uuid4()
    instrument = FakePricedInstrument(price_value=12.0)
    position = ValuationPosition(
        valuation_date=valuation_date,
        market_data_set=market_data_set_uid,
        lines=[
            ValuationLine(instrument=instrument, units=1.0),
            ValuationLine(instrument=instrument, units=2.0),
        ],
    )
    context = PricingValuationContext.prepare_for_position(position)
    smaller_position = ValuationPosition(
        valuation_date=valuation_date,
        market_data_set=market_data_set_uid,
        lines=[ValuationLine(instrument=instrument, units=3.0)],
    )

    with pytest.raises(ValueError, match="instrument universe"):
        smaller_position.price(context=context)


def test_pricing_valuation_context_resolves_market_data_set_once(monkeypatch) -> None:
    calls: list[Any] = []
    market_data_set_uid = uuid.uuid4()

    monkeypatch.setattr(
        "msm_pricing.api.market_data_bindings.PricingMarketDataSet.resolve_uid",
        staticmethod(lambda selector: calls.append(selector) or market_data_set_uid),
    )

    context = PricingValuationContext.prepare(
        valuation_date=dt.datetime(2026, 5, 27, tzinfo=dt.UTC),
        market_data_set="eod",
        instruments=[
            FakePricedInstrument(price_value=1.0),
            FakePricedInstrument(price_value=2.0),
        ],
    )

    assert context.market_data_set_uid == market_data_set_uid
    assert calls == ["eod"]


def test_pricing_valuation_context_bulk_resolves_fixed_income_rows(monkeypatch) -> None:
    market_data_set_uid = uuid.uuid4()
    index_uid = uuid.uuid4()
    curve_uid = uuid.uuid4()
    binding_key = curve_binding_key(
        role_key="projection",
        selector_type="index",
        selector_key=str(index_uid),
        quote_side="mid",
    )
    calls: list[tuple[str, Any]] = []

    monkeypatch.setattr(
        "msm_pricing.api.market_data_bindings.PricingMarketDataSet.resolve_uid",
        staticmethod(lambda selector: calls.append(("market_data_set", selector)) or market_data_set_uid),
    )
    monkeypatch.setattr(
        "msm_pricing.api.market_data_bindings.PricingMarketDataSetBinding.filter_for_set_and_concepts",
        staticmethod(
            lambda **kwargs: calls.append(("concept_bindings", kwargs))
            or [
                PricingMarketDataSetBinding(
                    uid=uuid.uuid4(),
                    market_data_set_uid=market_data_set_uid,
                    concept_key=PRICING_CONCEPT_DISCOUNT_CURVES,
                    data_node_uid=uuid.uuid4(),
                ),
                PricingMarketDataSetBinding(
                    uid=uuid.uuid4(),
                    market_data_set_uid=market_data_set_uid,
                    concept_key=PRICING_CONCEPT_INTEREST_RATE_INDEX_FIXINGS,
                    data_node_uid=uuid.uuid4(),
                ),
            ]
        ),
    )
    monkeypatch.setattr(
        Index,
        "filter_by_uids",
        staticmethod(
            lambda index_uids: calls.append(("indexes", index_uids))
            or [
                Index(
                    uid=index_uid,
                    unique_identifier="USD-SOFR",
                    index_type="interest_rate",
                    display_name="USD SOFR",
                )
            ]
        ),
    )
    monkeypatch.setattr(
        "msm_pricing.api.index_convention_details.IndexConventionDetails.filter_by_index_uids",
        staticmethod(
            lambda index_uids: calls.append(("index_conventions", index_uids))
            or [
                IndexConventionDetails(
                    index_uid=index_uid,
                    index_family="ibor",
                    convention_dump={
                        "currency_code": "USD",
                        "day_counter_code": "Actual360",
                        "calendar_code": "TARGET",
                        "business_day_convention": "ModifiedFollowing",
                        "settlement_days": 2,
                        "period": "3M",
                    },
                )
            ]
        ),
    )
    monkeypatch.setattr(
        "msm_pricing.api.market_data_bindings.PricingMarketDataSetCurveBinding.filter_by_binding_keys",
        staticmethod(
            lambda **kwargs: calls.append(("curve_bindings", kwargs))
            or [
                PricingMarketDataSetCurveBinding(
                    uid=uuid.uuid4(),
                    market_data_set_uid=market_data_set_uid,
                    binding_key=binding_key,
                    role_key="projection",
                    selector_type="index",
                    selector_key=str(index_uid),
                    quote_side="mid",
                    curve_uid=curve_uid,
                )
            ]
        ),
    )
    monkeypatch.setattr(
        "msm_pricing.api.curves.Curve.filter_by_uids",
        staticmethod(
            lambda curve_uids: calls.append(("curves", curve_uids))
            or [
                Curve(
                    uid=curve_uid,
                    unique_identifier="USD-SOFR-PROJECTION",
                    display_name="USD SOFR Projection",
                    curve_type="projection",
                )
            ]
        ),
    )
    monkeypatch.setattr(
        "msm_pricing.api.curve_building_details.CurveBuildingDetails.filter_by_curve_uids",
        staticmethod(
            lambda curve_uids: calls.append(("curve_building_details", curve_uids))
            or [
                CurveBuildingDetails(
                    curve_uid=curve_uid,
                    builder_type="zero_rate_curve",
                    quote_convention="zero_rate",
                    rate_unit="decimal",
                    day_counter_code="Actual360",
                    calendar_code="TARGET",
                    interpolation_method="linear_zero",
                    compounding="simple",
                    extrapolation_policy="enabled",
                )
            ]
        ),
    )
    monkeypatch.setattr(
        MSDataInterface,
        "get_historical_discount_curve_observations",
        lambda self, curve_names, target_date, *, market_data_set=None: calls.append(
            ("curve_observations", curve_names, target_date, market_data_set)
        )
        or {
            "USD-SOFR-PROJECTION": (
                {
                    "curve_identifier": "USD-SOFR-PROJECTION",
                    "time_index": target_date,
                    "nodes": [{"days_to_maturity": 365, "zero": 0.05}],
                    "key_nodes": None,
                    "metadata_json": None,
                },
                target_date,
            )
        },
    )
    monkeypatch.setattr(
        MSDataInterface,
        "get_historical_fixings_for_identifiers",
        lambda self, identifiers, start_date, end_date, *, market_data_set=None: calls.append(
            ("fixings", identifiers, start_date, end_date, market_data_set)
        )
        or {"USD-SOFR": {dt.date(2026, 5, 26): 0.0525}},
    )

    context = PricingValuationContext.prepare(
        valuation_date=dt.datetime(2026, 5, 27, tzinfo=dt.UTC),
        market_data_set="eod",
        instruments=[IndexedFakePricedInstrument(floating_rate_index_uid=index_uid)],
        curve_quote_side="mid",
    )

    assert context.market_data_set_uid == market_data_set_uid
    assert set(context.market_data_bindings) == {
        PRICING_CONCEPT_DISCOUNT_CURVES,
        PRICING_CONCEPT_INTEREST_RATE_INDEX_FIXINGS,
    }
    assert context.get_index_convention(index_uid).index_family == "ibor"
    assert context.get_index_curve_binding(role_key="projection", index_uid=index_uid).curve_uid == curve_uid
    assert context.get_curve(curve_uid).unique_identifier == "USD-SOFR-PROJECTION"
    assert context.get_curve_building_details(curve_uid).curve_uid == curve_uid
    assert context.spec.requested_roles == ("projection",)
    assert context.spec.requirements[0].binding_key == binding_key
    assert calls == [
        ("market_data_set", "eod"),
        (
            "concept_bindings",
            {
                "market_data_set_uid": market_data_set_uid,
                "concept_keys": (
                    PRICING_CONCEPT_DISCOUNT_CURVES,
                    PRICING_CONCEPT_INTEREST_RATE_INDEX_FIXINGS,
                ),
            },
        ),
        ("indexes", (index_uid,)),
        ("index_conventions", (index_uid,)),
        (
            "curve_bindings",
            {
                "market_data_set_uid": market_data_set_uid,
                "binding_keys": (binding_key,),
                "status": "ACTIVE",
            },
        ),
        ("curves", (curve_uid,)),
        ("curve_building_details", (curve_uid,)),
        (
            "curve_observations",
            ("USD-SOFR-PROJECTION",),
            dt.datetime(2026, 5, 27, tzinfo=dt.UTC),
            None,
        ),
        (
            "fixings",
            ("USD-SOFR",),
            dt.datetime(2025, 5, 27, tzinfo=dt.UTC),
            dt.datetime(2026, 5, 27, tzinfo=dt.UTC),
            None,
        ),
    ]


def test_pricing_valuation_context_fails_before_mutating_original_on_missing_rows(
    monkeypatch,
) -> None:
    market_data_set_uid = uuid.uuid4()
    index_uid = uuid.uuid4()
    instrument = IndexedFakePricedInstrument(floating_rate_index_uid=index_uid)

    monkeypatch.setattr(
        "msm_pricing.api.market_data_bindings.PricingMarketDataSet.resolve_uid",
        staticmethod(lambda _selector: market_data_set_uid),
    )
    monkeypatch.setattr(
        "msm_pricing.api.market_data_bindings.PricingMarketDataSetBinding.filter_for_set_and_concepts",
        staticmethod(
            lambda **_kwargs: [
                PricingMarketDataSetBinding(
                    uid=uuid.uuid4(),
                    market_data_set_uid=market_data_set_uid,
                    concept_key=PRICING_CONCEPT_DISCOUNT_CURVES,
                    data_node_uid=uuid.uuid4(),
                ),
                PricingMarketDataSetBinding(
                    uid=uuid.uuid4(),
                    market_data_set_uid=market_data_set_uid,
                    concept_key=PRICING_CONCEPT_INTEREST_RATE_INDEX_FIXINGS,
                    data_node_uid=uuid.uuid4(),
                ),
            ]
        ),
    )
    monkeypatch.setattr(
        Index,
        "filter_by_uids",
        staticmethod(
            lambda index_uids: [
                Index(
                    uid=index_uids[0],
                    unique_identifier="USD-SOFR",
                    index_type="interest_rate",
                    display_name="USD SOFR",
                )
            ]
        ),
    )
    monkeypatch.setattr(
        "msm_pricing.api.index_convention_details.IndexConventionDetails.filter_by_index_uids",
        staticmethod(lambda _index_uids: []),
    )

    with pytest.raises(LookupError, match="index conventions"):
        PricingValuationContext.prepare(
            valuation_date=dt.datetime(2026, 5, 27, tzinfo=dt.UTC),
            market_data_set="eod",
            instruments=[instrument],
        )

    assert instrument.valuation_date is None
    assert instrument._market_data_sets == []


def test_prepared_floating_bond_hot_loop_uses_context_without_backend_resolution(
    monkeypatch,
) -> None:
    ql = pytest.importorskip("QuantLib")
    from msm_pricing.instruments import FloatingRateBond
    from msm_pricing.pricing_engine import resolvers

    valuation_date = dt.datetime(2026, 5, 27, tzinfo=dt.UTC)
    market_data_set_uid = uuid.uuid4()
    index_uid = uuid.uuid4()
    curve_uid = uuid.uuid4()
    discount_curves_uid = uuid.uuid4()
    fixings_uid = uuid.uuid4()
    binding_key = curve_binding_key(
        role_key="projection",
        selector_type="index",
        selector_key=str(index_uid),
        quote_side="mid",
    )

    monkeypatch.setattr(
        "msm_pricing.api.market_data_bindings.PricingMarketDataSet.resolve_uid",
        staticmethod(lambda _selector: market_data_set_uid),
    )
    monkeypatch.setattr(
        "msm_pricing.api.market_data_bindings.PricingMarketDataSetBinding.filter_for_set_and_concepts",
        staticmethod(
            lambda **_kwargs: [
                PricingMarketDataSetBinding(
                    uid=uuid.uuid4(),
                    market_data_set_uid=market_data_set_uid,
                    concept_key=PRICING_CONCEPT_DISCOUNT_CURVES,
                    data_node_uid=discount_curves_uid,
                ),
                PricingMarketDataSetBinding(
                    uid=uuid.uuid4(),
                    market_data_set_uid=market_data_set_uid,
                    concept_key=PRICING_CONCEPT_INTEREST_RATE_INDEX_FIXINGS,
                    data_node_uid=fixings_uid,
                ),
            ]
        ),
    )
    monkeypatch.setattr(
        Index,
        "filter_by_uids",
        staticmethod(
            lambda index_uids: [
                Index(
                    uid=index_uids[0],
                    unique_identifier="USD-SOFR",
                    index_type="interest_rate",
                    display_name="USD SOFR",
                )
            ]
        ),
    )
    monkeypatch.setattr(
        "msm_pricing.api.index_convention_details.IndexConventionDetails.filter_by_index_uids",
        staticmethod(
            lambda index_uids: [
                IndexConventionDetails(
                    index_uid=index_uids[0],
                    index_family="ibor",
                    convention_dump={
                        "currency_code": "USD",
                        "day_counter_code": "Actual360",
                        "calendar_code": "TARGET",
                        "business_day_convention": "ModifiedFollowing",
                        "settlement_days": 2,
                        "period": "3M",
                    },
                )
            ]
        ),
    )
    monkeypatch.setattr(
        "msm_pricing.api.market_data_bindings.PricingMarketDataSetCurveBinding.filter_by_binding_keys",
        staticmethod(
            lambda **_kwargs: [
                PricingMarketDataSetCurveBinding(
                    uid=uuid.uuid4(),
                    market_data_set_uid=market_data_set_uid,
                    binding_key=binding_key,
                    role_key="projection",
                    selector_type="index",
                    selector_key=str(index_uid),
                    quote_side="mid",
                    curve_uid=curve_uid,
                )
            ]
        ),
    )
    monkeypatch.setattr(
        "msm_pricing.api.curves.Curve.filter_by_uids",
        staticmethod(
            lambda curve_uids: [
                Curve(
                    uid=curve_uids[0],
                    unique_identifier="USD-SOFR-PROJECTION",
                    display_name="USD SOFR Projection",
                    curve_type="projection",
                )
            ]
        ),
    )
    monkeypatch.setattr(
        "msm_pricing.api.curve_building_details.CurveBuildingDetails.filter_by_curve_uids",
        staticmethod(
            lambda curve_uids: [
                CurveBuildingDetails(
                    curve_uid=curve_uids[0],
                    builder_type="zero_rate_curve",
                    quote_convention="zero_rate",
                    rate_unit="decimal",
                    day_counter_code="Actual360",
                    calendar_code="TARGET",
                    interpolation_method="linear_zero",
                    compounding="simple",
                    extrapolation_policy="enabled",
                )
            ]
        ),
    )
    monkeypatch.setattr(
        MSDataInterface,
        "get_historical_discount_curve_observations",
        lambda self, curve_names, target_date, *, market_data_set=None: {
            "USD-SOFR-PROJECTION": (
                {
                    "curve_identifier": "USD-SOFR-PROJECTION",
                    "time_index": target_date,
                    "nodes": [
                        {"days_to_maturity": 365, "zero": 0.05},
                        {"days_to_maturity": 3650, "zero": 0.052},
                    ],
                    "key_nodes": None,
                    "metadata_json": None,
                },
                target_date,
            )
        },
    )
    monkeypatch.setattr(
        MSDataInterface,
        "get_historical_fixings_for_identifiers",
        lambda self, identifiers, start_date, end_date, *, market_data_set=None: {
            "USD-SOFR": {dt.date(2026, 5, 26): 0.0525}
        },
    )

    instrument = FloatingRateBond(
        face_value=100.0,
        issue_date=dt.date(2026, 6, 1),
        maturity_date=dt.date(2027, 6, 1),
        day_count=ql.Actual360(),
        calendar=ql.TARGET(),
        business_day_convention=ql.ModifiedFollowing,
        settlement_days=2,
        coupon_frequency=ql.Period("3M"),
        floating_rate_index_uid=index_uid,
        spread=0.001,
    )
    position = ValuationPosition(
        valuation_date=valuation_date,
        market_data_set="eod",
        lines=[ValuationLine(instrument=instrument, units=1.0)],
    )
    context = PricingValuationContext.prepare_for_position(
        position,
        curve_quote_side="mid",
    )
    direct_instrument = FloatingRateBond(
        face_value=100.0,
        issue_date=dt.date(2026, 6, 1),
        maturity_date=dt.date(2027, 6, 1),
        day_count=ql.Actual360(),
        calendar=ql.TARGET(),
        business_day_convention=ql.ModifiedFollowing,
        settlement_days=2,
        coupon_frequency=ql.Period("3M"),
        floating_rate_index_uid=index_uid,
        spread=0.001,
    )
    direct_instrument.set_valuation_date(valuation_date)
    monkeypatch.setattr(
        Index,
        "get_by_uid",
        staticmethod(
            lambda uid: Index(
                uid=uid,
                unique_identifier="USD-SOFR",
                index_type="interest_rate",
                display_name="USD SOFR",
            )
        ),
    )
    monkeypatch.setattr(
        IndexConventionDetails,
        "get_by_index_uid",
        staticmethod(
            lambda uid: IndexConventionDetails(
                index_uid=uid,
                index_family="ibor",
                convention_dump={
                    "currency_code": "USD",
                    "day_counter_code": "Actual360",
                    "calendar_code": "TARGET",
                    "business_day_convention": "ModifiedFollowing",
                    "settlement_days": 2,
                    "period": "3M",
                },
            )
        ),
    )
    monkeypatch.setattr(
        PricingMarketDataSetCurveBinding,
        "resolve_index_curve_uid",
        staticmethod(lambda **_kwargs: curve_uid),
    )
    monkeypatch.setattr(
        Curve,
        "get_by_uid",
        staticmethod(
            lambda uid: Curve(
                uid=uid,
                unique_identifier="USD-SOFR-PROJECTION",
                display_name="USD SOFR Projection",
                curve_type="projection",
            )
        ),
    )
    monkeypatch.setattr(
        CurveBuildingDetails,
        "get_by_curve_uid",
        staticmethod(
            lambda uid: CurveBuildingDetails(
                curve_uid=uid,
                builder_type="zero_rate_curve",
                quote_convention="zero_rate",
                rate_unit="decimal",
                day_counter_code="Actual360",
                calendar_code="TARGET",
                interpolation_method="linear_zero",
                compounding="simple",
                extrapolation_policy="enabled",
            )
        ),
    )
    monkeypatch.setattr(
        resolvers.data_interface,
        "get_historical_discount_curve",
        lambda curve_name, target_date, *, market_data_set=None: (
            [
                {"days_to_maturity": 365, "zero": 0.05},
                {"days_to_maturity": 3650, "zero": 0.052},
            ],
            target_date,
        ),
    )
    monkeypatch.setattr(
        resolvers.data_interface,
        "get_historical_fixings",
        lambda reference_rate_uid, start_date, end_date, *, market_data_set=None: {
            dt.date(2026, 5, 26): 0.0525
        },
    )
    direct_price = direct_instrument.price(
        market_data_set=market_data_set_uid,
        curve_quote_side="mid",
    )

    def forbidden(*_args, **_kwargs):
        raise AssertionError("hot loop called backend resolver")

    monkeypatch.setattr(Index, "get_by_uid", staticmethod(forbidden))
    monkeypatch.setattr(IndexConventionDetails, "get_by_index_uid", staticmethod(forbidden))
    monkeypatch.setattr(
        PricingMarketDataSetCurveBinding,
        "resolve_index_curve_uid",
        staticmethod(forbidden),
    )
    monkeypatch.setattr(Curve, "get_by_uid", staticmethod(forbidden))
    monkeypatch.setattr(CurveBuildingDetails, "get_by_curve_uid", staticmethod(forbidden))
    monkeypatch.setattr(resolvers.data_interface, "get_historical_discount_curve", forbidden)
    monkeypatch.setattr(resolvers, "add_historical_fixings", forbidden)

    assert position.price(context=context) == pytest.approx(direct_price)
    assert instrument.valuation_date is None


def test_valuation_position_accepts_explicit_pricing_context() -> None:
    valuation_date = dt.datetime(2026, 5, 27, tzinfo=dt.UTC)
    instrument = FakePricedInstrument(price_value=8.0)
    position = ValuationPosition(
        valuation_date=valuation_date,
        market_data_set="eod",
        lines=[ValuationLine(instrument=instrument, units=2.0)],
    )
    context = PricingValuationContext.prepare_for_position(
        position,
        resolve_market_data_set=False,
    )

    assert position.price(context=context) == 16.0
    assert instrument.valuation_date is None
    assert instrument._market_data_sets == []


def test_price_scenario_uses_line_scoped_curve_handle_copies() -> None:
    valuation_date = dt.datetime(2026, 5, 27, tzinfo=dt.UTC)
    instrument = CurveOverrideInstrument(price_value=100.0)
    position = ValuationPosition(
        valuation_date=valuation_date,
        market_data_set=uuid.uuid4(),
        lines=[ValuationLine(instrument=instrument, units=2.0)],
    )
    context = PricingValuationContext.prepare_for_position(position)

    result = price_scenario(
        position=position,
        context=context,
        line_curve_handles={0: 1.0},
        scenario_curve_handles={0: 3.0},
    )

    assert result["base_market_value"] == 202.0
    assert result["scenario_market_value"] == 206.0
    assert result["market_value_delta"] == 4.0
    assert instrument.valuation_date is None
    assert instrument._curve_bump == 0.0
    assert context.prepare_instrument(instrument).price() == 100.0


def test_package_exports_pricing_valuation_context() -> None:
    assert msm_pricing.PricingValuationContext is PricingValuationContext
    assert msm_pricing.PricingValuationContextSpec is PricingValuationContextSpec
    assert msm_pricing.price_scenario is price_scenario
