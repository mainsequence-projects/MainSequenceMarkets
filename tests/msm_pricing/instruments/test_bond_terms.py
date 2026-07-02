from __future__ import annotations

# ruff: noqa: E402

import datetime as dt
import inspect
import uuid

import pytest

ql = pytest.importorskip("QuantLib")

import msm_pricing.instruments as instruments
from msm_pricing.instruments import (
    BondInstrumentTerms,
    FixedRateBond,
    FloatingRateBond,
    ZeroCouponBond,
    build_bond_instrument_from_terms,
)
from msm_pricing.instruments import bond_terms


def _base_terms(instrument_type: str, **overrides: object) -> BondInstrumentTerms:
    values: dict[str, object] = {
        "instrument_type": instrument_type,
        "valuation_date": dt.date(2026, 1, 2),
        "issue_date": dt.date(2025, 1, 2),
        "maturity_date": dt.date(2027, 1, 2),
        "face_value": 100.0,
        "day_count": ql.Actual360(),
        "calendar": ql.TARGET(),
        "business_day_convention": ql.Following,
        "settlement_days": 2,
    }
    values.update(overrides)
    return BondInstrumentTerms(**values)


def test_public_instrument_exports_include_bond_terms_factory() -> None:
    assert instruments.BondInstrumentTerms is BondInstrumentTerms
    assert instruments.build_bond_instrument_from_terms is build_bond_instrument_from_terms


def test_build_zero_coupon_bond_terms_allows_missing_benchmark_uid() -> None:
    instrument = build_bond_instrument_from_terms(_base_terms("zero_coupon_bond"))

    assert isinstance(instrument, ZeroCouponBond)
    assert instrument.benchmark_rate_index_uid is None
    assert instrument.valuation_date == dt.date(2026, 1, 2)
    assert "benchmark_rate_index_name" not in instrument.model_dump()


def test_build_fixed_rate_bond_terms_uses_optional_benchmark_uid() -> None:
    benchmark_uid = uuid.uuid4()

    instrument = build_bond_instrument_from_terms(
        _base_terms(
            "fixed_rate_bond",
            benchmark_rate_index_uid=benchmark_uid,
            coupon_rate=0.05,
            coupon_frequency=ql.Period(6, ql.Months),
        )
    )

    assert isinstance(instrument, FixedRateBond)
    assert instrument.benchmark_rate_index_uid == benchmark_uid
    assert instrument.coupon_rate == pytest.approx(0.05)
    assert "benchmark_rate_index_name" not in instrument.model_dump()


def test_build_floating_rate_bond_terms_requires_floating_index_uid() -> None:
    with pytest.raises(ValueError, match="floating_rate_index_uid"):
        build_bond_instrument_from_terms(
            _base_terms(
                "floating_rate_bond",
                coupon_frequency=ql.Period(28, ql.Days),
            )
        )


def test_build_floating_rate_bond_terms_defaults_benchmark_to_floating_uid() -> None:
    index_uid = uuid.uuid4()

    instrument = build_bond_instrument_from_terms(
        _base_terms(
            "floating_rate_bond",
            floating_rate_index_uid=index_uid,
            coupon_frequency=ql.Period(28, ql.Days),
            spread=0.0025,
        )
    )

    assert isinstance(instrument, FloatingRateBond)
    assert instrument.floating_rate_index_uid == index_uid
    assert instrument.benchmark_rate_index_uid == index_uid
    assert instrument.spread == pytest.approx(0.0025)
    payload = instrument.model_dump()
    assert "floating_rate_index_name" not in payload
    assert "benchmark_rate_index_name" not in payload


def test_build_fixed_rate_bond_terms_requires_coupon_fields() -> None:
    with pytest.raises(ValueError, match="coupon_rate"):
        build_bond_instrument_from_terms(
            _base_terms(
                "fixed_rate_bond",
                coupon_frequency=ql.Period(6, ql.Months),
            )
        )

    with pytest.raises(ValueError, match="coupon_frequency"):
        build_bond_instrument_from_terms(
            _base_terms(
                "fixed_rate_bond",
                coupon_rate=0.05,
            )
        )


def test_bond_terms_module_has_no_provider_adapter_dependencies() -> None:
    source = inspect.getsource(bond_terms)

    forbidden = (
        "val" + "mer",
        "SUB" + "YACENTE_TO_INDEX_MAP",
        "resolve_" + "reference_index_uid",
        "vector_" + "to_asset",
        "upsert_" + "mex" + "ican_reference_indexes",
    )
    for token in forbidden:
        assert token not in source


def test_build_bond_instrument_from_terms_restores_quantlib_settings() -> None:
    settings = ql.Settings.instance()
    previous_evaluation_date = ql.Date(2, ql.January, 2024)
    previous_include_reference_date_events = True
    settings.evaluationDate = previous_evaluation_date
    settings.includeReferenceDateEvents = previous_include_reference_date_events
    has_enforce_todays_historic_fixings = hasattr(
        settings,
        "enforceTodaysHistoricFixings",
    )
    if has_enforce_todays_historic_fixings:
        previous_enforce_todays_historic_fixings = True
        settings.enforceTodaysHistoricFixings = previous_enforce_todays_historic_fixings

    build_bond_instrument_from_terms(
        _base_terms(
            "fixed_rate_bond",
            coupon_rate=0.05,
            coupon_frequency=ql.Period(6, ql.Months),
        ),
        include_reference_date_events=False,
        enforce_todays_historic_fixings=False,
    )

    assert settings.evaluationDate == previous_evaluation_date
    assert settings.includeReferenceDateEvents == previous_include_reference_date_events
    if has_enforce_todays_historic_fixings:
        assert settings.enforceTodaysHistoricFixings == previous_enforce_todays_historic_fixings
